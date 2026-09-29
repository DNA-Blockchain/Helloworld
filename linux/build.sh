#!/bin/sh
# Builds a small Alpine Linux image that boots in QEMU and runs a network node.
#
# Output (in $NOS_LINUX_BUILD, default ~/.cache/network-os-linux):
#   vmlinuz          Alpine's prebuilt linux-virt kernel
#   initramfs.gz     the whole root filesystem, loaded into RAM at boot
#
# Nothing is compiled: the kernel, busybox and Python come from Alpine's
# signed package repositories, so a rebuild takes a few minutes. Needs root
# (chroot) and network access. Run it from WSL/Linux, not Windows.
set -eu

ALPINE_VERSION=${ALPINE_VERSION:-3.24.2}
ALPINE_BRANCH=v${ALPINE_VERSION%.*}
MIRROR=${ALPINE_MIRROR:-https://dl-cdn.alpinelinux.org/alpine}
ARCH=x86_64
PACKAGES="linux-virt python3 py3-cryptography py3-requests py3-certifi"

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
BUILD=${NOS_LINUX_BUILD:-$HOME/.cache/network-os-linux}
ROOTFS=$BUILD/rootfs
TARBALL=alpine-minirootfs-$ALPINE_VERSION-$ARCH.tar.gz

if [ "$(id -u)" -ne 0 ]; then
    echo "build.sh needs root for chroot; run it with sudo" >&2
    exit 1
fi

mkdir -p "$BUILD"
cd "$BUILD"

# 1. Alpine's base system, checked against the published SHA-256.
if [ ! -f "$TARBALL" ]; then
    echo "==> downloading $TARBALL"
    curl -fL --retry 3 -o "$TARBALL.part" "$MIRROR/$ALPINE_BRANCH/releases/$ARCH/$TARBALL"
    mv "$TARBALL.part" "$TARBALL"
fi
curl -fsSL --retry 3 -o "$TARBALL.sha256" "$MIRROR/$ALPINE_BRANCH/releases/$ARCH/$TARBALL.sha256"
sha256sum -c "$TARBALL.sha256"

# 2. Fresh root filesystem every build, so nothing from an old build leaks in.
cleanup() {
    for m in dev proc; do
        mountpoint -q "$ROOTFS/$m" && umount "$ROOTFS/$m"
    done
    return 0
}
trap cleanup EXIT
cleanup
rm -rf "$ROOTFS"
mkdir -p "$ROOTFS"
tar -xzf "$TARBALL" -C "$ROOTFS"

# 3. Packages, installed by Alpine's own apk inside the chroot. apk checks
#    every package against the signing keys shipped in the base system.
printf '%s/%s/main\n%s/%s/community\n' "$MIRROR" "$ALPINE_BRANCH" "$MIRROR" "$ALPINE_BRANCH" \
    > "$ROOTFS/etc/apk/repositories"
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
mount --bind /dev "$ROOTFS/dev"
mount -t proc proc "$ROOTFS/proc"
echo "==> installing: $PACKAGES"
chroot "$ROOTFS" /sbin/apk add --no-cache --quiet $PACKAGES
cleanup

# 4. The node software: only the modules run_node_cli.py actually imports.
APP=$ROOTFS/opt/network-os
mkdir -p "$APP"
python3 - "$REPO" "$APP" <<'EOF'
import ast, os, shutil, sys
repo, dest = sys.argv[1], sys.argv[2]
seen, todo = set(), ["run_node_cli"]
while todo:
    mod = todo.pop()
    path = os.path.join(repo, mod + ".py")
    if mod in seen or not os.path.exists(path):
        continue
    seen.add(mod)
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            todo += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            todo.append(node.module.split(".")[0])
for mod in sorted(seen):
    shutil.copy(os.path.join(repo, mod + ".py"), dest)
print(f"==> copied {len(seen)} node modules")
EOF
cp -r "$REPO/schemas" "$APP/"
chroot "$ROOTFS" /usr/bin/python3 -m compileall -q /opt/network-os

# 5. Boot script, config and trimming.
cp "$HERE/init" "$ROOTFS/init"
chmod 755 "$ROOTFS/init"
echo network-os > "$ROOTFS/etc/hostname"
printf 'nameserver 10.0.2.3\n' > "$ROOTFS/etc/resolv.conf"
cp "$ROOTFS"/boot/vmlinuz-virt "$BUILD/vmlinuz"
KMOD=$(ls "$ROOTFS/lib/modules")
for d in sound gpu media infiniband wireless bluetooth isdn staging usb iio hid input; do
    find "$ROOTFS/lib/modules/$KMOD" -type d -name "$d" -prune -exec rm -rf {} +
done
chroot "$ROOTFS" /sbin/depmod "$KMOD"   # before /boot goes: depmod reads it
rm -rf "$ROOTFS/boot" "$ROOTFS/usr/share/doc" "$ROOTFS/usr/share/man" \
       "$ROOTFS/usr/lib/python3"*/test "$ROOTFS/usr/lib/python3"*/idlelib \
       "$ROOTFS/usr/lib/python3"*/tkinter "$ROOTFS/var/cache/apk"/*

# 6. Pack the root filesystem with busybox cpio from inside the chroot.
echo "==> packing initramfs"
chroot "$ROOTFS" /bin/sh -c 'cd / && find . -xdev | cpio -o -H newc 2>/dev/null' \
    | gzip -6 > "$BUILD/initramfs.gz.part"
mv "$BUILD/initramfs.gz.part" "$BUILD/initramfs.gz"

echo "==> done: Alpine $ALPINE_VERSION, kernel $KMOD"
ls -lh "$BUILD/vmlinuz" "$BUILD/initramfs.gz"
echo "boot it with: $HERE/run.sh"
