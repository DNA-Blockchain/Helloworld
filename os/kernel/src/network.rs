use crate::{Serial, e1000::E1000};
use bootloader_api::BootInfo;
use core::fmt::Write;
use smoltcp::{
    iface::{Config, Interface, SocketSet, SocketStorage},
    phy::Device,
    socket::{dhcpv4, icmp, tcp},
    time::Instant,
    wire::{
        EthernetAddress, Icmpv4Packet, Icmpv4Repr, Icmpv6Packet, Icmpv6Repr, IpAddress, IpCidr,
        Ipv4Address, Ipv6Address,
    },
};

const DHCP_WAIT_MS: i64 = 15_000;
const SLAAC_WAIT_MS: i64 = 5_000;
const PING_WAIT_MS: i64 = 3_000;
const HTTP_PORT: u16 = 8080;
const HTTP_REQUEST_CAPACITY: usize = 512;
const IPV6_TEST_GATEWAY: Ipv6Address = Ipv6Address::new(0xfd00, 0, 0, 0, 0, 0, 0, 2);

pub(crate) fn run(boot_info: &'static mut BootInfo) -> Result<(), &'static str> {
    let mut device = E1000::initialize(boot_info)?;
    crate::memory::initialize(boot_info)?;
    crate::memory::verify_allocate_and_release()?;
    let _ = writeln!(
        Serial,
        "Physical frame allocator verified: allocate, map, release, reuse."
    );
    let physical_memory_offset = boot_info
        .physical_memory_offset
        .into_option()
        .ok_or("bootloader did not map physical memory for virtual memory")?;
    crate::virtual_memory::initialize(physical_memory_offset)?;
    crate::virtual_memory::verify_mapping_lifecycle()?;
    let _ = writeln!(
        Serial,
        "Virtual memory verified: map, read/write, unmap, and reuse."
    );
    crate::heap::initialize()?;
    let heap_pages = crate::heap::verify_allocation_lifecycle()?;
    let _ = writeln!(
        Serial,
        "Kernel heap verified: Vec/Box allocation, release, and growth to {} KiB.",
        heap_pages * 4
    );
    crate::task::verify_separate_kernel_stack()?;
    let _ = writeln!(
        Serial,
        "Kernel task verified: separate 16-KiB stack and heap allocation."
    );
    crate::address_space::initialize(physical_memory_offset)?;
    crate::address_space::verify_isolation()?;
    let _ = writeln!(
        Serial,
        "Address spaces verified: private user mappings and supervisor kernel mappings (CPL0 test)."
    );
    let user_exit_code = crate::address_space::verify_user_syscall()?;
    let _ = writeln!(
        Serial,
        "ELF user process verified: static x86_64 TEST.ELF loaded from NOSFS, NX/write protections applied, and exited with code {}.",
        user_exit_code
    );
    let _ = writeln!(
        Serial,
        "Ring-3 syscalls verified: BOOT.JSON read into validated user memory and process exit."
    );
    let _ = writeln!(
        Serial,
        "Ring-3 protections verified: supervisor read, NX fetch, and read-only text write faults recovered."
    );
    let scheduled_steps = crate::scheduler::verify_cooperative_round_robin()?;
    let _ = writeln!(
        Serial,
        "Cooperative context switching verified: {} A/B/A/B/A resumptions on saved task stacks.",
        scheduled_steps
    );
    let mut config = Config::new(EthernetAddress(device.mac()).into());
    config.random_seed = 0x4e45_5457;
    config.slaac = true;
    let mut interface = Interface::new(config, &mut device, Instant::from_millis(now_ms()));

    let link_local = link_local_address(device.mac());
    let mut link_local_error = false;
    interface.update_ip_addrs(|addresses| {
        if addresses
            .push(IpCidr::new(IpAddress::Ipv6(link_local), 64))
            .is_err()
        {
            link_local_error = true;
        }
    });
    if link_local_error {
        return Err("could not configure the IPv6 link-local address");
    }

    let dhcp_socket = dhcpv4::Socket::new();
    let mut icmp_rx_metadata = [icmp::PacketMetadata::EMPTY; 2];
    let mut icmp_rx_data = [0; 512];
    let mut icmp_tx_metadata = [icmp::PacketMetadata::EMPTY; 2];
    let mut icmp_tx_data = [0; 512];
    let icmp_socket = icmp::Socket::new(
        icmp::PacketBuffer::new(&mut icmp_rx_metadata[..], &mut icmp_rx_data[..]),
        icmp::PacketBuffer::new(&mut icmp_tx_metadata[..], &mut icmp_tx_data[..]),
    );
    let mut tcp_rx_data = [0; 1024];
    let mut tcp_tx_data = [0; 1024];
    let tcp_socket = tcp::Socket::new(
        tcp::SocketBuffer::new(&mut tcp_rx_data[..]),
        tcp::SocketBuffer::new(&mut tcp_tx_data[..]),
    );

    let mut storage = [SocketStorage::EMPTY; 3];
    let mut sockets = SocketSet::new(&mut storage[..]);
    let dhcp_handle = sockets.add(dhcp_socket);
    let icmp_handle = sockets.add(icmp_socket);
    let tcp_handle = sockets.add(tcp_socket);

    let dhcp_deadline = now_ms().saturating_add(DHCP_WAIT_MS);
    let mut dhcp_config = None;
    loop {
        interface.poll(Instant::from_millis(now_ms()), &mut device, &mut sockets);
        match sockets.get_mut::<dhcpv4::Socket>(dhcp_handle).poll() {
            Some(dhcpv4::Event::Configured(config)) => {
                dhcp_config = Some(config);
                break;
            }
            Some(dhcpv4::Event::Deconfigured) | None => {}
        }
        if device.take_tx_error() {
            return Err("E1000 transmit descriptor did not complete");
        }
        if now_ms() >= dhcp_deadline {
            break;
        }
        crate::timer::wait_for_ticks(crate::timer::ticks().saturating_add(1));
    }

    let Some(config) = dhcp_config else {
        device.report_status();
        return Err("DHCP lease was not received from QEMU's user network");
    };
    let mut address_error = false;
    interface.update_ip_addrs(|addresses| {
        if addresses.push(IpCidr::Ipv4(config.address)).is_err() {
            address_error = true;
        }
    });
    if address_error {
        return Err("could not configure the DHCP-assigned IPv4 address");
    }
    let _ = writeln!(Serial, "DHCP configured: IPv4 {}", config.address);

    let gateway = config
        .router
        .ok_or("DHCP did not provide a default gateway")?;
    if interface
        .routes_mut()
        .add_default_ipv4_route(gateway)
        .is_err()
    {
        return Err("could not configure the DHCP default route");
    }
    let _ = writeln!(Serial, "IPv4 default gateway: {}", gateway);
    verify_ipv4_gateway_echo(
        &mut interface,
        &mut device,
        &mut sockets,
        icmp_handle,
        gateway,
    )?;

    let ipv6_address = wait_for_slaac_address(&mut interface, &mut device, &mut sockets)?;
    let ipv6_gateway = if let Some(address) = ipv6_address {
        let _ = writeln!(Serial, "IPv6 SLAAC configured: {}", address);
        let gateway = interface
            .routes()
            .get_default_ipv6_route()
            .map(|route| route.via_router)
            .ok_or("router advertisement did not install an IPv6 default route")?;
        let IpAddress::Ipv6(gateway) = gateway else {
            return Err("router advertisement installed a non-IPv6 default route");
        };
        let _ = writeln!(Serial, "IPv6 default gateway: {}", gateway);
        gateway
    } else {
        let static_address = unique_local_address(device.mac());
        let mut ipv6_address_error = false;
        interface.update_ip_addrs(|addresses| {
            if addresses
                .push(IpCidr::new(IpAddress::Ipv6(static_address), 64))
                .is_err()
            {
                ipv6_address_error = true;
            }
        });
        if ipv6_address_error {
            return Err("could not configure the static IPv6 test address");
        }
        interface
            .routes_mut()
            .add_default_ipv6_route(IPV6_TEST_GATEWAY)
            .map_err(|_| "could not configure the static IPv6 test route")?;
        let _ = writeln!(
            Serial,
            "IPv6 SLAAC unavailable: QEMU user networking sent no router advertisement."
        );
        let _ = writeln!(
            Serial,
            "IPv6 configured (static fallback): {}/64",
            static_address
        );
        IPV6_TEST_GATEWAY
    };
    verify_ipv6_gateway_echo(
        &mut interface,
        &mut device,
        &mut sockets,
        icmp_handle,
        ipv6_gateway,
    )?;
    if device.take_tx_error() {
        return Err("E1000 transmit descriptor did not complete");
    }

    let _ = writeln!(Serial, "HTTP health service listening on port {HTTP_PORT}");
    serve_http(
        &mut interface,
        &mut device,
        &mut sockets,
        tcp_handle,
        HTTP_PORT,
    )
}

fn unique_local_address(mac: [u8; 6]) -> Ipv6Address {
    let eui64 = [
        mac[0] ^ 0x02,
        mac[1],
        mac[2],
        0xff,
        0xfe,
        mac[3],
        mac[4],
        mac[5],
    ];
    Ipv6Address::new(
        0xfd00,
        0,
        0,
        0,
        u16::from_be_bytes([eui64[0], eui64[1]]),
        u16::from_be_bytes([eui64[2], eui64[3]]),
        u16::from_be_bytes([eui64[4], eui64[5]]),
        u16::from_be_bytes([eui64[6], eui64[7]]),
    )
}

fn link_local_address(mac: [u8; 6]) -> Ipv6Address {
    let eui64 = [
        mac[0] ^ 0x02,
        mac[1],
        mac[2],
        0xff,
        0xfe,
        mac[3],
        mac[4],
        mac[5],
    ];
    Ipv6Address::new(
        0xfe80,
        0,
        0,
        0,
        u16::from_be_bytes([eui64[0], eui64[1]]),
        u16::from_be_bytes([eui64[2], eui64[3]]),
        u16::from_be_bytes([eui64[4], eui64[5]]),
        u16::from_be_bytes([eui64[6], eui64[7]]),
    )
}

fn now_ms() -> i64 {
    crate::timer::milliseconds().min(i64::MAX as u64) as i64
}

fn wait_for_slaac_address(
    interface: &mut Interface,
    device: &mut E1000,
    sockets: &mut SocketSet<'_>,
) -> Result<Option<Ipv6Address>, &'static str> {
    let deadline = now_ms().saturating_add(SLAAC_WAIT_MS);
    loop {
        interface.poll(Instant::from_millis(now_ms()), device, sockets);
        if let Some(address) = interface.ip_addrs().iter().find_map(|cidr| match cidr {
            IpCidr::Ipv6(cidr) if !cidr.address().is_unicast_link_local() => Some(cidr.address()),
            _ => None,
        }) {
            return Ok(Some(address));
        }
        if device.take_tx_error() {
            return Err("E1000 transmit descriptor did not complete");
        }
        if now_ms() >= deadline {
            return Ok(None);
        }
        crate::timer::wait_for_ticks(crate::timer::ticks().saturating_add(1));
    }
}

fn serve_http(
    interface: &mut Interface,
    device: &mut E1000,
    sockets: &mut SocketSet<'_>,
    handle: smoltcp::iface::SocketHandle,
    port: u16,
) -> Result<(), &'static str> {
    let mut request = [0; HTTP_REQUEST_CAPACITY];
    let mut request_len = 0;
    loop {
        interface.poll(Instant::from_millis(now_ms()), device, sockets);
        let socket = sockets.get_mut::<tcp::Socket>(handle);
        if !socket.is_open() {
            socket
                .listen(port)
                .map_err(|_| "could not listen on the HTTP health port")?;
            request_len = 0;
        }

        if socket.can_recv() {
            let copied = socket
                .recv(|incoming| {
                    let length = incoming.len().min(request.len() - request_len);
                    request[request_len..request_len + length].copy_from_slice(&incoming[..length]);
                    (length, length)
                })
                .map_err(|_| "failed to read the HTTP request")?;
            request_len += copied;

            if request_len == request.len()
                && !request[..request_len].windows(4).any(|w| w == b"\r\n\r\n")
            {
                socket
                    .send_slice(b"HTTP/1.1 431 Request Header Fields Too Large\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    .map_err(|_| "could not queue the HTTP error response")?;
                socket.close();
                continue;
            }

            if request[..request_len]
                .windows(4)
                .any(|window| window == b"\r\n\r\n")
            {
                let response = if request[..request_len].starts_with(b"GET /health ") {
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\nConnection: close\r\n\r\nok\n".as_slice()
                } else {
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                        .as_slice()
                };
                socket
                    .send_slice(response)
                    .map_err(|_| "could not queue the HTTP response")?;
                socket.close();
                request_len = 0;
            }
        }

        if device.take_tx_error() {
            return Err("E1000 transmit descriptor did not complete");
        }
        crate::timer::wait_for_ticks(crate::timer::ticks().saturating_add(1));
    }
}

fn verify_ipv4_gateway_echo(
    interface: &mut Interface,
    device: &mut E1000,
    sockets: &mut SocketSet<'_>,
    handle: smoltcp::iface::SocketHandle,
    gateway: Ipv4Address,
) -> Result<(), &'static str> {
    let ident = 0x4244;
    let sequence = 1;
    {
        let socket = sockets.get_mut::<icmp::Socket>(handle);
        socket
            .bind(icmp::Endpoint::Ident(ident))
            .map_err(|_| "could not bind the ICMP echo socket")?;
        let data = b"network-os";
        let packet_buffer = socket
            .send(
                Icmpv4Repr::EchoRequest {
                    ident,
                    seq_no: sequence,
                    data,
                }
                .buffer_len(),
                IpAddress::Ipv4(gateway),
            )
            .map_err(|_| "could not queue an ICMP echo request")?;
        let mut packet = Icmpv4Packet::new_unchecked(packet_buffer);
        Icmpv4Repr::EchoRequest {
            ident,
            seq_no: sequence,
            data,
        }
        .emit(&mut packet, &device.capabilities().checksum);
    }

    let deadline = now_ms().saturating_add(PING_WAIT_MS);
    loop {
        interface.poll(Instant::from_millis(now_ms()), device, sockets);
        let socket = sockets.get_mut::<icmp::Socket>(handle);
        if socket.can_recv() {
            let (packet, source) = socket
                .recv()
                .map_err(|_| "failed to read the ICMP echo response")?;
            if source == IpAddress::Ipv4(gateway) {
                let packet = Icmpv4Packet::new_checked(packet)
                    .map_err(|_| "received a malformed ICMP packet")?;
                if matches!(
                    Icmpv4Repr::parse(&packet, &device.capabilities().checksum),
                    Ok(Icmpv4Repr::EchoReply {
                        ident: reply_ident,
                        seq_no: reply_sequence,
                        ..
                    }) if reply_ident == ident && reply_sequence == sequence
                ) {
                    let _ = writeln!(Serial, "ICMP echo reply from {}", gateway);
                    return Ok(());
                }
            }
        }
        if device.take_tx_error() {
            return Err("E1000 transmit descriptor did not complete");
        }
        if now_ms() >= deadline {
            return Err("no ICMP echo reply received from the QEMU IPv4 gateway");
        }
        crate::timer::wait_for_ticks(crate::timer::ticks().saturating_add(1));
    }
}

fn verify_ipv6_gateway_echo(
    interface: &mut Interface,
    device: &mut E1000,
    sockets: &mut SocketSet<'_>,
    handle: smoltcp::iface::SocketHandle,
    gateway: Ipv6Address,
) -> Result<(), &'static str> {
    let ident = 0x4244;
    let sequence = 1;
    let source = interface.get_source_address_ipv6(&gateway);
    {
        let socket = sockets.get_mut::<icmp::Socket>(handle);
        let data = b"network-os-ipv6";
        let packet_buffer = socket
            .send(
                Icmpv6Repr::EchoRequest {
                    ident,
                    seq_no: sequence,
                    data,
                }
                .buffer_len(),
                IpAddress::Ipv6(gateway),
            )
            .map_err(|_| "could not queue an ICMPv6 echo request")?;
        let mut packet = Icmpv6Packet::new_unchecked(packet_buffer);
        Icmpv6Repr::EchoRequest {
            ident,
            seq_no: sequence,
            data,
        }
        .emit(
            &source,
            &gateway,
            &mut packet,
            &device.capabilities().checksum,
        );
    }

    let deadline = now_ms().saturating_add(PING_WAIT_MS);
    loop {
        interface.poll(Instant::from_millis(now_ms()), device, sockets);
        let socket = sockets.get_mut::<icmp::Socket>(handle);
        if socket.can_recv() {
            let (packet, source_address) = socket
                .recv()
                .map_err(|_| "failed to read the ICMPv6 echo response")?;
            if source_address == IpAddress::Ipv6(gateway) {
                let packet = Icmpv6Packet::new_checked(packet)
                    .map_err(|_| "received a malformed ICMPv6 packet")?;
                let parsed =
                    Icmpv6Repr::parse(&gateway, &source, &packet, &device.capabilities().checksum);
                if matches!(
                    parsed,
                    Ok(Icmpv6Repr::EchoReply {
                        ident: reply_ident,
                        seq_no: reply_sequence,
                        ..
                    }) if reply_ident == ident && reply_sequence == sequence
                ) {
                    let _ = writeln!(Serial, "ICMPv6 echo reply from {}", gateway);
                    return Ok(());
                }
            }
        }
        if device.take_tx_error() {
            return Err("E1000 transmit descriptor did not complete");
        }
        if now_ms() >= deadline {
            return Err("no ICMPv6 echo reply received from the QEMU IPv6 gateway");
        }
        crate::timer::wait_for_ticks(crate::timer::ticks().saturating_add(1));
    }
}
