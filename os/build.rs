use std::path::PathBuf;

fn main() {
    let out_dir = PathBuf::from(std::env::var_os("OUT_DIR").expect("Cargo must provide OUT_DIR"));
    let kernel = PathBuf::from(
        std::env::var_os("CARGO_BIN_FILE_KERNEL_kernel")
            .expect("Cargo must build the kernel artifact"),
    );
    let bios_image = out_dir.join("network-os-bios.img");

    bootloader::BiosBoot::new(&kernel)
        .create_disk_image(&bios_image)
        .expect("failed to create BIOS boot image");

    println!("cargo:rustc-env=BIOS_IMAGE={}", bios_image.display());
    println!("cargo:rerun-if-changed=kernel/src");
}
