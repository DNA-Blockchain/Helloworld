#!/usr/bin/env python3
"""Builds a small Alpine Linux image that boots in QEMU and runs a network node.

Output (in $NOS_LINUX_BUILD, default ~/.cache/network-os-linux):
  vmlinuz          Alpine's prebuilt linux-virt kernel
  initramfs.gz     the whole root filesystem, loaded into RAM at boot

Nothing is compiled: the kernel, busybox and Python come from Alpine's
signed package repositories, so a rebuild takes a few minutes. Needs root
(chroot) and network access. Run it from WSL/Linux, not Windows:

  sudo python3 linux/build.py
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ALPINE_VERSION = os.environ.get("ALPINE_VERSION", "3.24.2")
ALPINE_BRANCH = "v" + ALPINE_VERSION.rsplit(".", 1)[0]
MIRROR = os.environ.get("ALPINE_MIRROR", "https://dl-cdn.alpinelinux.org/alpine")
ARCH = "x86_64"
PACKAGES = ["linux-virt", "python3", "py3-cryptography", "py3-requests", "py3-certifi"]
# Kernel module folders a headless VM never loads.
UNUSED_MODULES = {"sound", "gpu", "media", "infiniband", "wireless", "bluetooth", "isdn", "staging", "usb",
                  "iio", "hid", "input"}


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


def fetch(url: str, retries: int = 3) -> bytes:
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except OSError:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def download(url: str, dest: Path) -> None:
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(fetch(url))
    part.replace(dest)


def check_sha256(path: Path, published: str) -> None:
    """published is the mirror's .sha256 file: '<hex>  <name>'."""
    expected = published.split()[0].lower()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{path.name}: SHA-256 {actual} does not match the published {expected}")
    print(f"{path.name}: OK")


def node_modules(repo: Path) -> list[str]:
    """The repository modules run_node_cli.py imports, directly or through each other."""
    seen: set[str] = set()
    todo = ["run_node_cli"]
    while todo:
        mod = todo.pop()
        path = repo / f"{mod}.py"
        if mod in seen or not path.exists():
            continue
        seen.add(mod)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                todo.append(node.module.split(".")[0])
    return sorted(seen)


def apply_umask(tree: Path) -> None:
    """copytree keeps source modes, and /mnt/c shows every file as 777; cp -r would mask them to 755."""
    umask = os.umask(0)
    os.umask(umask)
    for path in [tree, *tree.rglob("*")]:
        path.chmod(path.stat().st_mode & 0o7777 & ~umask)


def mounts_under(root: Path) -> list[str]:
    prefix = str(root.resolve()) + "/"
    with open("/proc/mounts", encoding="utf-8") as f:
        return [p for p in (line.split()[1] for line in f) if p.startswith(prefix)]


def unmount(rootfs: Path) -> None:
    for m in ("dev", "proc"):
        if os.path.ismount(rootfs / m):
            subprocess.run(["umount", str(rootfs / m)], check=True)


def chroot(rootfs: Path, *cmd: str) -> None:
    subprocess.run(["chroot", str(rootfs), *cmd], check=True)


def human(size: float) -> str:
    """Size as ls -lh prints it: 49M, 12M, 105."""
    for unit in ("", "K", "M"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}G"


def build(out: Path) -> None:
    rootfs = out / "rootfs"
    tarball = out / f"alpine-minirootfs-{ALPINE_VERSION}-{ARCH}.tar.gz"
    release = f"{MIRROR}/{ALPINE_BRANCH}/releases/{ARCH}/{tarball.name}"
    out.mkdir(parents=True, exist_ok=True)

    # 1. Alpine's base system, checked against the published SHA-256.
    if not tarball.is_file():
        step(f"downloading {tarball.name}")
        download(release, tarball)
    published = fetch(release + ".sha256").decode()
    (out / f"{tarball.name}.sha256").write_text(published)
    check_sha256(tarball, published)

    # 2. Fresh root filesystem every build, so nothing from an old build leaks in.
    #    Never delete through a mount: that would delete the host's /dev.
    unmount(rootfs)
    if rootfs.exists() and mounts_under(rootfs):
        raise SystemExit(f"still mounted under {rootfs}: {mounts_under(rootfs)}; unmount them first")
    if rootfs.exists():
        shutil.rmtree(rootfs)
    rootfs.mkdir(parents=True)
    subprocess.run(["tar", "-xzf", str(tarball), "-C", str(rootfs)], check=True)

    try:
        # 3. Packages, installed by Alpine's own apk inside the chroot. apk checks
        #    every package against the signing keys shipped in the base system.
        (rootfs / "etc/apk/repositories").write_text(
            f"{MIRROR}/{ALPINE_BRANCH}/main\n{MIRROR}/{ALPINE_BRANCH}/community\n")
        shutil.copy("/etc/resolv.conf", rootfs / "etc/resolv.conf")
        subprocess.run(["mount", "--bind", "/dev", str(rootfs / "dev")], check=True)
        subprocess.run(["mount", "-t", "proc", "proc", str(rootfs / "proc")], check=True)
        step(f"installing: {' '.join(PACKAGES)}")
        chroot(rootfs, "/sbin/apk", "add", "--no-cache", "--quiet", *PACKAGES)
    finally:
        unmount(rootfs)

    # 4. The node software: only the modules run_node_cli.py actually imports.
    app = rootfs / "opt/network-os"
    app.mkdir(parents=True, exist_ok=True)
    modules = node_modules(REPO)
    for mod in modules:
        shutil.copy(REPO / f"{mod}.py", app)
    print(f"==> copied {len(modules)} node modules", flush=True)
    shutil.copytree(REPO / "schemas", app / "schemas", dirs_exist_ok=True)
    apply_umask(app / "schemas")
    chroot(rootfs, "/usr/bin/python3", "-m", "compileall", "-q", "/opt/network-os")

    # 5. Boot script, config and trimming.
    shutil.copy(HERE / "init", rootfs / "init")
    (rootfs / "init").chmod(0o755)
    (rootfs / "etc/hostname").write_text("network-os\n")
    (rootfs / "etc/resolv.conf").write_text("nameserver 10.0.2.3\n")
    shutil.copy(rootfs / "boot/vmlinuz-virt", out / "vmlinuz")
    kernels = sorted(p.name for p in (rootfs / "lib/modules").iterdir())
    if len(kernels) != 1:
        raise SystemExit(f"expected one kernel in lib/modules, found {kernels}")
    kmod = kernels[0]
    for folder, subdirs, _ in os.walk(rootfs / "lib/modules" / kmod):
        for d in [d for d in subdirs if d in UNUSED_MODULES]:
            shutil.rmtree(Path(folder) / d)
            subdirs.remove(d)
    chroot(rootfs, "/sbin/depmod", kmod)         # before /boot goes: depmod reads it
    trash = [rootfs / "boot", rootfs / "usr/share/doc", rootfs / "usr/share/man"]
    for python in (rootfs / "usr/lib").glob("python3*"):
        trash += [python / "test", python / "idlelib", python / "tkinter"]
    for path in trash:
        shutil.rmtree(path, ignore_errors=True)
    for cached in (rootfs / "var/cache/apk").glob("*"):
        if cached.is_dir() and not cached.is_symlink():
            shutil.rmtree(cached)
        else:
            cached.unlink()

    # 6. Pack the root filesystem with busybox cpio from inside the chroot.
    step("packing initramfs")
    part = out / "initramfs.gz.part"
    pack = subprocess.Popen(["chroot", str(rootfs), "/bin/sh", "-c",
                             "cd / && find . -xdev | cpio -o -H newc 2>/dev/null"], stdout=subprocess.PIPE)
    with gzip.open(part, "wb", compresslevel=6) as gz:
        shutil.copyfileobj(pack.stdout, gz, 1 << 20)
    if pack.wait() != 0:
        part.unlink()
        raise SystemExit(f"packing the initramfs failed (cpio exit {pack.returncode})")
    part.replace(out / "initramfs.gz")

    print(f"==> done: Alpine {ALPINE_VERSION}, kernel {kmod}")
    for name in ("vmlinuz", "initramfs.gz"):
        print(f"{human((out / name).stat().st_size):>7}  {out / name}")
    print(f"boot it with: python3 {HERE / 'run.py'}")


def main() -> int:
    if sys.platform != "linux" or os.geteuid() != 0:
        print("build.py needs root on Linux for chroot; run it from WSL with sudo", file=sys.stderr)
        return 1
    sys.path.insert(0, str(HERE))
    import run
    build(run.build_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
