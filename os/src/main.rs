use std::env;
use std::process::{Command, ExitCode};

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let mode = args.next().unwrap_or_else(|| "run".to_owned());
    if mode == "--help" || mode == "-h" {
        println!("Usage: cargo run -- [run|check]");
        println!(
            "Boot the x86_64 prototype in QEMU; check also verifies the expected serial output."
        );
        return ExitCode::SUCCESS;
    }
    if !matches!(mode.as_str(), "run" | "check") || args.next().is_some() {
        eprintln!("Usage: cargo run -- [run|check|--help]");
        return ExitCode::from(2);
    }

    let image = env!("BIOS_IMAGE");
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
        "-netdev",
        "user,id=net0",
        "-device",
        "e1000,netdev=net0",
    ]);

    if mode == "check" {
        match qemu.output() {
            Ok(output) => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let stderr = String::from_utf8_lossy(&output.stderr);
                print!("{stdout}");
                eprint!("{stderr}");

                if output.status.code() != Some(33) {
                    eprintln!("QEMU exited unexpectedly with status: {}", output.status);
                    return ExitCode::from(1);
                }
                if !stdout.contains("Network OS prototype: booted in x86_64 QEMU.")
                    || !stdout.contains("network controller: 8086:100e")
                    || !stdout.contains("Detected 1 PCI network controller(s).")
                {
                    eprintln!(
                        "QEMU booted, but expected boot or network-device output was missing."
                    );
                    return ExitCode::from(1);
                }

                println!("QEMU boot check passed.");
                ExitCode::SUCCESS
            }
            Err(error) => {
                report_qemu_start_error(error);
                ExitCode::from(1)
            }
        }
    } else {
        match qemu.status() {
            Ok(status) if status.code() == Some(33) => ExitCode::SUCCESS,
            Ok(status) => {
                eprintln!("QEMU exited unexpectedly with status: {status}");
                ExitCode::from(1)
            }
            Err(error) => {
                report_qemu_start_error(error);
                ExitCode::from(1)
            }
        }
    }
}

fn report_qemu_start_error(error: std::io::Error) {
    eprintln!("Could not start qemu-system-x86_64: {error}");
    eprintln!("Install QEMU and ensure qemu-system-x86_64 is on PATH.");
}
