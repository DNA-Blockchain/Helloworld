#!/bin/sh
# Boots the image from build.sh in QEMU, with its console in this terminal.
#   run.sh [--id N] [--port P] [--peers host:port,...] [--tofu]
#          [--duration S] [--mem 512M] [--ram-only]
# The node's port is forwarded from the host, so localhost:P reaches it. Its
# data lives in $NOS_LINUX_BUILD/node-data/node-N unless --ram-only is given.
# Leave the console with Ctrl-A then X.
set -eu

BUILD=${NOS_LINUX_BUILD:-$HOME/.cache/network-os-linux}
ID=1 PORT= PEERS= TOFU= DURATION=0 MEM=512M RAM_ONLY=
while [ $# -gt 0 ]; do
    case $1 in
        --id) ID=$2; shift ;;
        --port) PORT=$2; shift ;;
        --peers) PEERS=$2; shift ;;
        --tofu) TOFU=1 ;;
        --duration) DURATION=$2; shift ;;
        --mem) MEM=$2; shift ;;
        --ram-only) RAM_ONLY=1 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
PORT=${PORT:-$((9600 + ID))}

for f in vmlinuz initramfs.gz; do
    [ -f "$BUILD/$f" ] || { echo "no $BUILD/$f; run linux/build.sh first" >&2; exit 1; }
done

# Peers on the host are reached from inside the VM through 10.0.2.2.
PEERS=$(printf '%s' "$PEERS" | sed 's/\(localhost\|127\.0\.0\.1\):/10.0.2.2:/g')

APPEND="console=ttyS0 quiet nos.id=$ID nos.port=$PORT nos.duration=$DURATION"
[ -n "$PEERS" ] && APPEND="$APPEND nos.peers=$PEERS"
[ -n "$TOFU" ] && APPEND="$APPEND nos.tofu=1"

if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL="-machine q35,accel=kvm -cpu host"
else
    echo "(no KVM access: using slow emulation)" >&2
    ACCEL="-machine q35"
fi

set -- -kernel "$BUILD/vmlinuz" -initrd "$BUILD/initramfs.gz" -append "$APPEND" \
    -m "$MEM" -smp 2 -nographic -no-reboot \
    -netdev "user,id=n0,hostfwd=tcp::$PORT-:$PORT" -device virtio-net-pci,netdev=n0
if [ -z "$RAM_ONLY" ]; then
    DATA=$BUILD/node-data/node-$ID
    mkdir -p "$DATA"
    set -- "$@" -virtfs "local,path=$DATA,mount_tag=nosdata,security_model=none,id=d0"
fi

# shellcheck disable=SC2086
exec qemu-system-x86_64 $ACCEL "$@"
