use std::{
    env,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    net::{Shutdown, TcpListener, TcpStream, UdpSocket},
    path::Path,
    process::{Child, Command, ExitCode, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const HOST_HEALTH_ADDR: &str = "127.0.0.1:18080";
/// Offline stand-ins for internet services. The guest reaches them through
/// QEMU's gateway 10.0.2.2, which user networking maps to host loopback.
const TEST_DNS_ADDR: &str = "127.0.0.1:15353";
const TEST_TCP_ADDR: &str = "127.0.0.1:15380";
const TEST_DNS_NAME: &[u8] = b"test.nos";
const TEST_HOST_IPV4: [u8; 4] = [10, 0, 2, 2];

/// Boot checks now run workflow tasks (including two MicroPython interpreter
/// starts and a 1-second runtime-limit test) before networking comes up.
const BOOT_CHECK_TIMEOUT: Duration = Duration::from_secs(120);

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let mode = args.next().unwrap_or_else(|| "run".to_owned());
    if mode == "--help" || mode == "-h" {
        println!("Usage: cargo run -- [run|check|check-slaac]");
        println!("Run boots the OS and keeps its HTTP health service running.");
        println!("Check boots the OS, verifies dual-stack connectivity, and tests /health.");
        println!(
            "Run and check answer the guest's DNS and TCP tests locally; no internet is needed."
        );
        println!("Check-slaac boots it against a loopback-only test router that sends a real RA.");
        return ExitCode::SUCCESS;
    }
    if !matches!(mode.as_str(), "run" | "check" | "check-slaac") || args.next().is_some() {
        eprintln!("Usage: cargo run -- [run|check|check-slaac|--help]");
        return ExitCode::from(2);
    }

    let image = env!("BIOS_IMAGE");
    let data_disk = match prepare_data_disk() {
        Ok(path) => path,
        Err(error) => {
            eprintln!("{error}");
            return ExitCode::from(1);
        }
    };
    if mode == "check-slaac" {
        return match run_slaac_integration_check(image, &data_disk) {
            Ok(()) => {
                println!("QEMU SLAAC router-advertisement check passed.");
                ExitCode::SUCCESS
            }
            Err(error) => {
                eprintln!("{error}");
                ExitCode::from(1)
            }
        };
    }

    if let Err(error) = start_offline_test_services() {
        eprintln!("{error}");
        return ExitCode::from(1);
    }
    let network = "user,id=net0,ipv4=on,ipv6=on,ipv6-net=fd00::/64,ipv6-host=fd00::2,hostfwd=tcp:127.0.0.1:18080-:8080";
    let mut qemu = qemu_command(image, network, &data_disk);

    if mode == "check" {
        match run_integration_check(&mut qemu) {
            Ok(()) => {
                println!("QEMU dual-stack HTTP service check passed.");
                ExitCode::SUCCESS
            }
            Err(error) => {
                eprintln!("{error}");
                ExitCode::from(1)
            }
        }
    } else {
        match qemu.status() {
            Ok(status) => {
                eprintln!("QEMU service stopped unexpectedly with status: {status}");
                ExitCode::from(1)
            }
            Err(error) => {
                report_qemu_start_error(error);
                ExitCode::from(1)
            }
        }
    }
}

/// Starts the loopback DNS responder and TCP echo service the kernel's
/// network checks use, so `run` and `check` work without internet access.
fn start_offline_test_services() -> Result<(), String> {
    let dns = UdpSocket::bind(TEST_DNS_ADDR).map_err(|error| {
        format!("Could not start the offline DNS test service on {TEST_DNS_ADDR}: {error}")
    })?;
    let tcp = TcpListener::bind(TEST_TCP_ADDR).map_err(|error| {
        format!("Could not start the offline TCP test service on {TEST_TCP_ADDR}: {error}")
    })?;
    thread::spawn(move || {
        let mut request = [0; 512];
        loop {
            let Ok((length, peer)) = dns.recv_from(&mut request) else {
                continue;
            };
            if let Some(response) = answer_dns_query(&request[..length]) {
                let _ = dns.send_to(&response, peer);
            }
        }
    });
    thread::spawn(move || {
        for stream in tcp.incoming().flatten() {
            thread::spawn(move || echo_tcp(stream));
        }
    });
    Ok(())
}

/// Answers an A query for TEST_DNS_NAME with TEST_HOST_IPV4 and anything else
/// with NXDOMAIN. Returns None for packets that are not a single-question
/// standard query.
fn answer_dns_query(request: &[u8]) -> Option<Vec<u8>> {
    if request.len() < 17 || request[2] & 0xf8 != 0 || request[4..6] != [0, 1] {
        return None;
    }
    let mut offset = 12;
    let mut name = Vec::new();
    loop {
        let length = *request.get(offset)? as usize;
        offset += 1;
        if length == 0 {
            break;
        }
        if length > 63 {
            return None;
        }
        if !name.is_empty() {
            name.push(b'.');
        }
        name.extend_from_slice(request.get(offset..offset + length)?);
        offset += length;
    }
    let question_end = offset.checked_add(4)?;
    let question_type = request.get(offset..question_end)?;
    let found = name.eq_ignore_ascii_case(TEST_DNS_NAME) && question_type == [0, 1, 0, 1];
    let mut response = request[..question_end].to_vec();
    response[2] = 0x80 | (request[2] & 0x01);
    response[3] = if found { 0x80 } else { 0x83 };
    response[6..12].copy_from_slice(&[0, u8::from(found), 0, 0, 0, 0]);
    if found {
        response.extend_from_slice(&[0xc0, 0x0c, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4]);
        response.extend_from_slice(&TEST_HOST_IPV4);
    }
    Some(response)
}

fn echo_tcp(mut stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
    let mut buffer = [0; 1024];
    while let Ok(length) = stream.read(&mut buffer) {
        if length == 0 || stream.write_all(&buffer[..length]).is_err() {
            break;
        }
    }
}

fn prepare_data_disk() -> Result<std::path::PathBuf, String> {
    const DATA_DISK_SIZE: u64 = 2 * 1024 * 1024;
    let target = Path::new(env!("CARGO_MANIFEST_DIR")).join("target");
    std::fs::create_dir_all(&target)
        .map_err(|error| format!("Could not create OS target directory: {error}"))?;
    let path = target.join("network-os-persistent.img");
    match OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(file) => file
            .set_len(DATA_DISK_SIZE)
            .map_err(|error| format!("Could not initialize QEMU test disk: {error}"))?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let metadata = std::fs::metadata(&path)
                .map_err(|error| format!("Could not inspect QEMU test disk: {error}"))?;
            if metadata.len() < DATA_DISK_SIZE {
                return Err(format!(
                    "Existing QEMU test disk is too small ({} bytes); refusing to resize it.",
                    metadata.len()
                ));
            }
        }
        Err(error) => return Err(format!("Could not create QEMU test disk: {error}")),
    }
    Ok(path)
}

fn qemu_command(image: &str, network: &str, data_disk: &Path) -> Command {
    let mut qemu = Command::new("qemu-system-x86_64");
    qemu.args([
        "-machine",
        "pc",
        "-m",
        "256M",
        "-display",
        "none",
        "-serial",
        "stdio",
        "-no-reboot",
        "-device",
        "isa-debug-exit,iobase=0xf4,iosize=0x04",
        "-drive",
        &format!("format=raw,file={image}"),
        "-drive",
        &format!("format=raw,file={},if=ide,index=2", data_disk.display()),
        "-netdev",
        network,
        "-device",
        "e1000,netdev=net0",
    ]);
    qemu
}

fn run_integration_check(qemu: &mut Command) -> Result<(), String> {
    qemu.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = qemu.spawn().map_err(|error| {
        report_qemu_start_error(error);
        "QEMU could not be started.".to_owned()
    })?;
    let (sender, receiver) = mpsc::channel();
    forward_output(child.stdout.take(), sender.clone());
    forward_output(child.stderr.take(), sender.clone());
    drop(sender);

    let mut output = Vec::new();
    let deadline = Instant::now() + BOOT_CHECK_TIMEOUT;
    let mut service_ready = false;
    while Instant::now() < deadline {
        match receiver.recv_timeout(Duration::from_millis(250)) {
            Ok(line) => {
                service_ready |= line.contains("HTTP health service listening on port 8080");
                output.push(line);
                if service_ready {
                    break;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {}
            Err(error) => {
                let cleanup = terminate_qemu(&mut child, &mut output, &receiver);
                print_output(&output, "check-slaac");
                return match cleanup {
                    Ok(()) => Err(format!("Could not inspect QEMU process: {error}")),
                    Err(cleanup_error) => Err(format!(
                        "Could not inspect QEMU process: {error}; cleanup also failed: {cleanup_error}"
                    )),
                };
            }
        }
    }

    if !service_ready {
        let cleanup = terminate_qemu(&mut child, &mut output, &receiver);
        print_output(&output, "check-slaac");
        cleanup?;
        return Err(
            "QEMU did not reach the network-service-ready state within 120 seconds.".into(),
        );
    }

    let first_response = request_health_endpoint();
    let second_response = request_health_endpoint();
    let cleanup = terminate_qemu(&mut child, &mut output, &receiver);
    print_output(&output, "check");
    cleanup?;
    for response in [first_response?, second_response?] {
        if !response.starts_with("HTTP/1.1 200 OK\r\n") || !response.ends_with("\r\n\r\nok\n") {
            return Err(format!(
                "The QEMU health endpoint returned an unexpected response: {response:?}"
            ));
        }
    }
    let ipv6_setup_reported = output.iter().any(|line| {
        line.contains("IPv6 SLAAC configured: ")
            || line.contains("IPv6 configured (static fallback): ")
    });
    if !output
        .iter()
        .any(|line| line.contains("PIT timer verified: "))
        || !output
            .iter()
            .any(|line| line.contains("Physical frame allocator verified: "))
        || !output
            .iter()
            .any(|line| line.contains("Virtual memory verified: "))
        || !output
            .iter()
            .any(|line| line.contains("Kernel heap verified: Vec/Box allocation"))
        || !output
            .iter()
            .any(|line| line.contains("Kernel task verified: separate 16-KiB stack"))
        || !output
            .iter()
            .any(|line| line.contains("Guest checkpoints active: boot "))
        || !output.iter().any(|line| {
            line.contains(
                "Guest checkpoint failback verified: intact prior copy selected after simulated corruption",
            )
        })
        || !output
            .iter()
            .any(|line| {
                line.contains(
                    "Address spaces verified: separate roots, 16 private user pages, and supervisor kernel mappings",
                )
            })
        || !output
            .iter()
            .any(|line| {
                line.contains(
                    "ELF process verified: dedicated CR3, exit 42, page-fault and invalid-opcode recovery, and page reclamation",
                )
            })
        || !output.iter().any(|line| {
            line.contains(
                "Ring-3 syscalls verified: bounded stdout echo of BOOT.JSON; supervisor read and write pointers rejected",
            )
        })
        || !output.iter().any(|line| {
            line.contains(
                "Ring-3 DNS syscall verified: test.nos resolved through the kernel-owned UDP service",
            )
        })
        || !output.iter().any(|line| {
            line.contains(
                "Ring-3 TCP socket ABI verified: bounded connect/send/receive/close calls and invalid endpoint rejection",
            )
        })
        || !output
            .iter()
            .any(|line| line.contains("NOSFS workflow execution verified:"))
        || !output
            .iter()
            .any(|line| line.contains("Remission bundle verified in ring-3 MicroPython"))
        || !output.iter().any(|line| {
            line.contains(
                "Ring-3 UDP datagram verified: user bind/sendto/recvfrom resolved DNS through the kernel network owner",
            )
        })
        || !output.iter().any(|line| {
            line.contains(r#"{"schema":"network-os.fs-smoke.v1","purpose":"persistent filesystem test"}"#)
        })
        || !output.iter().any(|line| {
            line.contains(
                "Ring-3 protections verified: supervisor read, NX fetch, and read-only text write faults recovered",
            )
        })
        || !output.iter().any(|line| {
            line.contains(
                "NOSFS workflow dispatcher verified: topological plan, bounded status events, dependency wakeup, and failure policies; tasks not executed.",
            )
        })
        || !output.iter().any(|line| {
            line.contains("Cooperative scheduler verified: 5 A/B/A/B/A steps")
        })
        || !output.iter().any(|line| {
            line.contains("Block device verified: 4096 sectors; persistent test record generation ")
        })
        || !output.iter().any(|line| {
            line.contains(
                "Filesystem verified: NOSFS v2 persisted BOOT.JSON and a 24-KiB RUNTIME.TEST file",
            )
        })
        || !output
            .iter()
            .any(|line| line.contains("DHCP configured: IPv4 "))
        || !output
            .iter()
            .any(|line| line.contains("ICMP echo reply from 10.0.2.2"))
        || !output
            .iter()
            .any(|line| line.contains("DNS verified: test.nos resolved to 10.0.2.2"))
        || !output
            .iter()
            .any(|line| line.contains("Ring-3 TCP connection verified: "))
        || !output
            .iter()
            .any(|line| line.contains("ICMPv6 echo reply from fd00::2"))
        || !ipv6_setup_reported
    {
        return Err("QEMU was reachable over HTTP, but one or more network checks were missing from the serial log.".into());
    }
    Ok(())
}

fn run_slaac_integration_check(image: &str, data_disk: &Path) -> Result<(), String> {
    let router_port = reserve_udp_port()?;
    let guest_port = reserve_udp_port()?;
    if router_port == guest_port {
        return Err("Could not reserve distinct UDP ports for the SLAAC test router.".into());
    }

    let router_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tools")
        .join("slaac_test_router.py");
    let mut router = Command::new("python")
        .arg(router_path)
        .arg("--port")
        .arg(router_port.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|error| format!("Could not start the local SLAAC test router: {error}"))?;
    let router_stdout = router
        .stdout
        .take()
        .ok_or("Could not capture the test router startup message")?;
    let mut router_stdout = BufReader::new(router_stdout);
    let mut ready_message = String::new();
    if let Err(error) = router_stdout.read_line(&mut ready_message) {
        let cleanup = stop_process(&mut router, "SLAAC test router");
        return Err(format!(
            "Could not read the test router startup message: {error}{}",
            cleanup
                .err()
                .map(|error| format!("; cleanup failed: {error}"))
                .unwrap_or_default()
        ));
    }
    if !ready_message.contains("QEMU SLAAC test router ready") {
        let cleanup = stop_process(&mut router, "SLAAC test router");
        return Err(format!(
            "The test router did not start correctly.{}",
            cleanup
                .err()
                .map(|error| format!(" Cleanup failed: {error}"))
                .unwrap_or_default()
        ));
    }
    println!("{}", ready_message.trim_end());

    let network =
        format!("socket,id=net0,udp=127.0.0.1:{router_port},localaddr=127.0.0.1:{guest_port}");
    let mut qemu = qemu_command(image, &network, data_disk);
    qemu.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = match qemu.spawn() {
        Ok(child) => child,
        Err(error) => {
            let cleanup = stop_process(&mut router, "SLAAC test router");
            report_qemu_start_error(error);
            return Err(format!(
                "QEMU could not be started for the SLAAC check.{}",
                cleanup
                    .err()
                    .map(|error| format!(" Router cleanup failed: {error}"))
                    .unwrap_or_default()
            ));
        }
    };
    let (sender, receiver) = mpsc::channel();
    forward_output(child.stdout.take(), sender.clone());
    forward_output(child.stderr.take(), sender.clone());
    drop(sender);

    let mut output = Vec::new();
    let mut saw_dhcp = false;
    let mut saw_timer = false;
    let mut saw_memory = false;
    let mut saw_virtual_memory = false;
    let mut saw_heap = false;
    let mut saw_kernel_task = false;
    let mut saw_guest_checkpoint = false;
    let mut saw_address_spaces = false;
    let mut saw_user_syscall = false;
    let mut saw_user_filesystem_read = false;
    let mut saw_user_task_output = false;
    let mut saw_user_dns = false;
    let mut saw_user_tcp_abi = false;
    let mut saw_workflow_execution = false;
    let mut saw_user_fault_recovery = false;
    let mut saw_task_bundle = false;
    let mut saw_scheduler = false;
    let mut saw_storage = false;
    let mut saw_filesystem = false;
    let mut saw_ipv4_echo = false;
    let mut saw_slaac = false;
    let mut saw_default_route = false;
    let mut saw_ipv6_echo = false;
    let mut saw_service_ready = false;
    let deadline = Instant::now() + BOOT_CHECK_TIMEOUT;
    while Instant::now() < deadline {
        match receiver.recv_timeout(Duration::from_millis(250)) {
            Ok(line) => {
                saw_dhcp |= line.contains("DHCP configured: IPv4 ");
                saw_timer |= line.contains("PIT timer verified: ");
                saw_memory |= line.contains("Physical frame allocator verified: ");
                saw_virtual_memory |= line.contains("Virtual memory verified: ");
                saw_heap |= line.contains("Kernel heap verified: Vec/Box allocation");
                saw_kernel_task |= line.contains("Kernel task verified: separate 16-KiB stack");
                saw_guest_checkpoint |= line.contains("Guest checkpoints active: boot ");
                saw_address_spaces |= line.contains(
                    "Address spaces verified: separate roots, 16 private user pages, and supervisor kernel mappings",
                );
                saw_user_syscall |=
                    line.contains(
                        "ELF process verified: dedicated CR3, exit 42, page-fault and invalid-opcode recovery, and page reclamation",
                    );
                saw_user_filesystem_read |= line.contains(
                    "Ring-3 syscalls verified: bounded stdout echo of BOOT.JSON; supervisor read and write pointers rejected",
                );
                saw_user_task_output |= line.contains(
                    r#"{"schema":"network-os.fs-smoke.v1","purpose":"persistent filesystem test"}"#,
                );
                saw_user_dns |= line.contains(
                    "Ring-3 DNS syscall verified: test.nos resolved through the kernel-owned UDP service",
                ) || line.contains(
                    "Ring-3 DNS syscall unavailable: configured resolver returned no IPv4 result",
                );
                saw_user_tcp_abi |= line.contains(
                    "Ring-3 TCP socket ABI verified: bounded connect/send/receive/close calls and invalid endpoint rejection",
                );
                saw_workflow_execution |=
                    line.contains("Remission bundle verified in ring-3 MicroPython");
                saw_user_fault_recovery |= line.contains(
                    "Ring-3 protections verified: supervisor read, NX fetch, and read-only text write faults recovered",
                );
                saw_task_bundle |= line.contains(
                    "NOSFS workflow dispatcher verified: topological plan, bounded status events, dependency wakeup, and failure policies; tasks not executed.",
                );
                saw_scheduler |= line.contains("Cooperative scheduler verified: 5 A/B/A/B/A steps");
                saw_storage |= line.contains(
                    "Block device verified: 4096 sectors; persistent test record generation ",
                );
                saw_filesystem |= line.contains(
                    "Filesystem verified: NOSFS v2 persisted BOOT.JSON and a 24-KiB RUNTIME.TEST file",
                );
                saw_ipv4_echo |= line.contains("ICMP echo reply from 10.0.2.2");
                saw_slaac |= line.contains("IPv6 SLAAC configured: fd00::");
                saw_default_route |= line.contains("IPv6 default gateway: fe80::1");
                saw_ipv6_echo |= line.contains("ICMPv6 echo reply from fe80::1");
                saw_service_ready |= line.contains("HTTP health service listening on port 8080");
                output.push(line);
                if saw_timer
                    && saw_memory
                    && saw_virtual_memory
                    && saw_heap
                    && saw_kernel_task
                    && saw_guest_checkpoint
                    && saw_address_spaces
                    && saw_user_syscall
                    && saw_user_filesystem_read
                    && saw_user_task_output
                    && saw_user_dns
                    && saw_user_tcp_abi
                    && saw_workflow_execution
                    && saw_user_fault_recovery
                    && saw_task_bundle
                    && saw_scheduler
                    && saw_storage
                    && saw_filesystem
                    && saw_dhcp
                    && saw_ipv4_echo
                    && saw_slaac
                    && saw_default_route
                    && saw_ipv6_echo
                    && saw_service_ready
                {
                    break;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {}
            Err(error) => {
                let cleanup = terminate_qemu(&mut child, &mut output, &receiver);
                let router_cleanup = stop_process(&mut router, "SLAAC test router");
                print_output(&output, "check");
                return Err(format!(
                    "Could not inspect QEMU process: {error}{}{}",
                    cleanup
                        .err()
                        .map(|error| format!("; QEMU cleanup failed: {error}"))
                        .unwrap_or_default(),
                    router_cleanup
                        .err()
                        .map(|error| format!("; router cleanup failed: {error}"))
                        .unwrap_or_default()
                ));
            }
        }
    }

    let qemu_cleanup = terminate_qemu(&mut child, &mut output, &receiver);
    let router_cleanup = stop_process(&mut router, "SLAAC test router");
    print_output(&output, "check");
    qemu_cleanup?;
    router_cleanup?;
    if !(saw_timer
        && saw_memory
        && saw_virtual_memory
        && saw_heap
        && saw_kernel_task
        && saw_guest_checkpoint
        && saw_address_spaces
        && saw_user_syscall
        && saw_user_filesystem_read
        && saw_user_task_output
        && saw_user_dns
        && saw_user_tcp_abi
        && saw_workflow_execution
        && saw_user_fault_recovery
        && saw_task_bundle
        && saw_scheduler
        && saw_storage
        && saw_filesystem
        && saw_dhcp
        && saw_ipv4_echo
        && saw_slaac
        && saw_default_route
        && saw_ipv6_echo
        && saw_service_ready)
    {
        return Err(format!(
            "The controlled-router check did not verify all expected behavior (PIT timer: {saw_timer}, persistent storage: {saw_storage}, filesystem: {saw_filesystem}, physical frame allocator: {saw_memory}, virtual memory: {saw_virtual_memory}, growing kernel heap: {saw_heap}, separate kernel task stack: {saw_kernel_task}, guest checkpoints: {saw_guest_checkpoint}, address spaces: {saw_address_spaces}, ELF user process: {saw_user_syscall}, ring-3 filesystem/stdout: {saw_user_filesystem_read}, guest task output: {saw_user_task_output}, ring-3 DNS: {saw_user_dns}, ring-3 TCP ABI: {saw_user_tcp_abi}, workflow execution: {saw_workflow_execution}, user protection-fault recovery: {saw_user_fault_recovery}, task bundle: {saw_task_bundle}, cooperative scheduler: {saw_scheduler}, DHCP: {saw_dhcp}, IPv4 echo: {saw_ipv4_echo}, SLAAC address: {saw_slaac}, RA default route: {saw_default_route}, IPv6 echo: {saw_ipv6_echo}, service ready: {saw_service_ready})."
        ));
    }
    Ok(())
}

fn reserve_udp_port() -> Result<u16, String> {
    let socket = UdpSocket::bind("127.0.0.1:0")
        .map_err(|error| format!("Could not reserve a loopback UDP port: {error}"))?;
    socket
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("Could not read the reserved UDP port: {error}"))
}

fn forward_output<R>(stream: Option<R>, sender: mpsc::Sender<String>)
where
    R: Read + Send + 'static,
{
    if let Some(stream) = stream {
        thread::spawn(move || {
            for line in BufReader::new(stream).lines() {
                match line {
                    Ok(line) => {
                        if sender.send(line).is_err() {
                            break;
                        }
                    }
                    Err(error) => {
                        let _ = sender.send(format!("QEMU output read failed: {error}"));
                        break;
                    }
                }
            }
        });
    }
}

fn request_health_endpoint() -> Result<String, String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut last_error = None;
    let address = HOST_HEALTH_ADDR
        .parse()
        .map_err(|error| format!("Invalid local health-check address: {error}"))?;
    while Instant::now() < deadline {
        let attempt = match TcpStream::connect_timeout(&address, Duration::from_millis(500)) {
            Ok(mut stream) => {
                let attempt = (|| {
                    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                    stream.write_all(
                        b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
                    )?;
                    stream.shutdown(Shutdown::Write)?;
                    let mut response = String::new();
                    stream.read_to_string(&mut response)?;
                    Ok(response)
                })();
                attempt.map_err(|error: std::io::Error| error.to_string())
            }
            Err(error) => Err(error.to_string()),
        };
        match attempt {
            Ok(response) => return Ok(response),
            Err(error) => last_error = Some(error),
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err(format!(
        "Could not complete an HTTP health request through QEMU's loopback-only forward at {HOST_HEALTH_ADDR}: {}",
        last_error
            .map(|error| error)
            .unwrap_or_else(|| "connection timed out".to_owned())
    ))
}

fn terminate_qemu(
    child: &mut Child,
    output: &mut Vec<String>,
    receiver: &mpsc::Receiver<String>,
) -> Result<(), String> {
    match child.try_wait() {
        Ok(Some(_)) => {}
        Ok(None) => {
            if let Err(kill_error) = child.kill() {
                match child.try_wait() {
                    Ok(Some(_)) => {}
                    Ok(None) => {
                        return Err(format!(
                            "Could not stop QEMU integration process: {kill_error}"
                        ));
                    }
                    Err(status_error) => {
                        return Err(format!(
                            "Could not stop QEMU integration process: {kill_error}; process status check failed: {status_error}"
                        ));
                    }
                }
            }
        }
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            while let Ok(line) = receiver.try_recv() {
                output.push(line);
            }
            return Err(format!("Could not inspect QEMU during cleanup: {error}"));
        }
    }
    child
        .wait()
        .map_err(|error| format!("Could not wait for QEMU to stop: {error}"))?;
    while let Ok(line) = receiver.try_recv() {
        output.push(line);
    }
    Ok(())
}

fn stop_process(child: &mut Child, label: &str) -> Result<(), String> {
    match child.try_wait() {
        Ok(Some(_)) => return Ok(()),
        Ok(None) => {}
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("Could not inspect {label} during cleanup: {error}"));
        }
    }
    if let Err(kill_error) = child.kill() {
        match child.try_wait() {
            Ok(Some(_)) => {}
            Ok(None) => return Err(format!("Could not stop {label}: {kill_error}")),
            Err(status_error) => {
                return Err(format!(
                    "Could not stop {label}: {kill_error}; process status check failed: {status_error}"
                ));
            }
        }
    }
    child
        .wait()
        .map_err(|error| format!("Could not wait for {label} to stop: {error}"))?;
    Ok(())
}

fn print_output(output: &[String], mode: &str) {
    for line in output {
        println!("{line}");
    }
    match persist_qemu_log(output, mode) {
        Ok(path) => println!("Engineering transcript saved: {}", path.display()),
        Err(error) => eprintln!("Could not persist QEMU engineering transcript: {error}"),
    }
}

fn persist_qemu_log(output: &[String], mode: &str) -> Result<std::path::PathBuf, String> {
    let log_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("logs");
    fs::create_dir_all(&log_dir)
        .map_err(|error| format!("could not create {}: {error}", log_dir.display()))?;
    let slots = [
        log_dir.join(format!("qemu-{mode}-a.log")),
        log_dir.join(format!("qemu-{mode}-b.log")),
    ];
    let target = match (slots[0].exists(), slots[1].exists()) {
        (false, _) => slots[0].clone(),
        (true, false) => slots[1].clone(),
        (true, true) => {
            let first = fs::metadata(&slots[0])
                .and_then(|metadata| metadata.modified())
                .map_err(|error| format!("could not inspect {}: {error}", slots[0].display()))?;
            let second = fs::metadata(&slots[1])
                .and_then(|metadata| metadata.modified())
                .map_err(|error| format!("could not inspect {}: {error}", slots[1].display()))?;
            if first <= second {
                slots[0].clone()
            } else {
                slots[1].clone()
            }
        }
    };
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock is before the Unix epoch: {error}"))?;
    let temporary = log_dir.join(format!(
        ".qemu-{mode}-{}-{}.tmp",
        std::process::id(),
        timestamp.as_nanos()
    ));
    let write_result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|error| format!("could not create {}: {error}", temporary.display()))?;
        writeln!(
            file,
            "mode={mode} unix_seconds={} duration_nanos={}",
            timestamp.as_secs(),
            timestamp.subsec_nanos()
        )
        .map_err(|error| format!("could not write {}: {error}", temporary.display()))?;
        for line in output {
            writeln!(file, "{line}")
                .map_err(|error| format!("could not write {}: {error}", temporary.display()))?;
        }
        file.sync_all()
            .map_err(|error| format!("could not flush {}: {error}", temporary.display()))?;
        fs::rename(&temporary, &target)
            .map_err(|error| format!("could not commit {}: {error}", target.display()))?;
        Ok(target.clone())
    })();
    if write_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    write_result
}

fn report_qemu_start_error(error: std::io::Error) {
    eprintln!("Could not start qemu-system-x86_64: {error}");
    eprintln!("Install QEMU and ensure qemu-system-x86_64 is on PATH.");
}
/*
 * Copyright (c) 2026 Chase Allen Ringquist. All rights reserved.
 *
 * This file is part of an operating system, software, and network Work
 * conceived and authored by Chase Allen Ringquist. It is the intellectual and
 * digital property of the Author, except where an open-source license
 * accompanying this file expressly grants other rights.
 *
 * Do not remove or alter this notice or any record of origin.
 * See NOTICE.md in the project root for full terms.
 * See LICENSE for the applicable license.
 *
 * Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 */
