use crate::{Serial, e1000::E1000};
use bootloader_api::BootInfo;
use core::fmt::Write;
use smoltcp::{
    iface::{Config, Interface, SocketSet, SocketStorage},
    phy::Device,
    socket::{dhcpv4, icmp},
    time::Instant,
    wire::{EthernetAddress, Icmpv4Packet, Icmpv4Repr, IpAddress, IpCidr, Ipv4Address},
};

const DHCP_WAIT_MS: i64 = 15_000;
const PING_WAIT_MS: i64 = 3_000;
const QEMU_NETWORK_SETTLE_SPINS: usize = 10_000_000;

pub(crate) fn run(boot_info: &'static mut BootInfo) -> Result<(), &'static str> {
    let mut device = E1000::initialize(boot_info)?;
    let mut config = Config::new(EthernetAddress(device.mac()).into());
    config.random_seed = 0x4e45_5457;
    let mut interface = Interface::new(config, &mut device, Instant::from_millis(0));

    let dhcp_socket = dhcpv4::Socket::new();
    let mut icmp_rx_metadata = [icmp::PacketMetadata::EMPTY; 2];
    let mut icmp_rx_data = [0; 512];
    let mut icmp_tx_metadata = [icmp::PacketMetadata::EMPTY; 2];
    let mut icmp_tx_data = [0; 512];
    let icmp_socket = icmp::Socket::new(
        icmp::PacketBuffer::new(&mut icmp_rx_metadata[..], &mut icmp_rx_data[..]),
        icmp::PacketBuffer::new(&mut icmp_tx_metadata[..], &mut icmp_tx_data[..]),
    );

    let mut storage = [SocketStorage::EMPTY; 2];
    let mut sockets = SocketSet::new(&mut storage[..]);
    let dhcp_handle = sockets.add(dhcp_socket);
    let icmp_handle = sockets.add(icmp_socket);

    let mut dhcp_config = None;
    for milliseconds in 0..DHCP_WAIT_MS {
        let timestamp = Instant::from_millis(milliseconds);
        interface.poll(timestamp, &mut device, &mut sockets);
        if milliseconds == 0 {
            // The kernel has no timer interrupt yet; give QEMU's user-mode network backend time
            // to process the first DHCP Discover before the guest's polling timeout advances.
            for _ in 0..QEMU_NETWORK_SETTLE_SPINS {
                core::hint::spin_loop();
            }
        }
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
        core::hint::spin_loop();
    }

    let Some(config) = dhcp_config else {
        device.report_status();
        return Err("DHCP lease was not received from QEMU's user network");
    };
    let mut address_error = false;
    interface.update_ip_addrs(|addresses| {
        addresses.clear();
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

    verify_gateway_echo(
        &mut interface,
        &mut device,
        &mut sockets,
        icmp_handle,
        gateway,
        DHCP_WAIT_MS,
    )?;
    if device.take_tx_error() {
        return Err("E1000 transmit descriptor did not complete");
    }
    Ok(())
}

fn verify_gateway_echo(
    interface: &mut Interface,
    device: &mut E1000,
    sockets: &mut SocketSet<'_>,
    handle: smoltcp::iface::SocketHandle,
    gateway: Ipv4Address,
    start_ms: i64,
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

    for milliseconds in start_ms..start_ms + PING_WAIT_MS {
        let timestamp = Instant::from_millis(milliseconds);
        interface.poll(timestamp, device, sockets);
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
        core::hint::spin_loop();
    }
    Err("no ICMP echo reply received from the QEMU gateway")
}
