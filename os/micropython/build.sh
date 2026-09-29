#!/bin/sh
# Builds os/micropython/MPY.ELF, the ring-3 MicroPython runtime that the
# kernel embeds. Run in Ubuntu/WSL (needs gcc, make, python3, git):
#
#   sh os/micropython/build.sh
#
# MICROPY_TOP may point at an existing checkout; otherwise the pinned
# revision is cloned into ~/.cache. The build runs in a Linux-local
# directory because building on /mnt/c is slow.
set -eu

MICROPY_REVISION=09f5bb447504a058376c62fe991b3613531837e6
PORT_DIR=$(cd "$(dirname "$0")" && pwd)
MICROPY_TOP=${MICROPY_TOP:-$HOME/.cache/network-os-micropython-src}
WORK=$HOME/.cache/network-os-micropython-port

if [ ! -d "$MICROPY_TOP/py" ]; then
    git clone --filter=blob:none https://github.com/micropython/micropython.git "$MICROPY_TOP"
fi
if [ "$(git -C "$MICROPY_TOP" rev-parse HEAD)" != "$MICROPY_REVISION" ]; then
    git -C "$MICROPY_TOP" checkout --quiet "$MICROPY_REVISION"
fi

rm -rf "$WORK"
mkdir -p "$WORK"
cp "$PORT_DIR"/Makefile "$PORT_DIR"/link.ld "$PORT_DIR"/*.c "$PORT_DIR"/*.h "$WORK"/
make -C "$WORK" MICROPY_TOP="$MICROPY_TOP" -j2
strip --strip-all -o "$PORT_DIR/MPY.ELF" "$WORK/build/firmware.elf"
# ld labels the image ET_EXEC because link.ld replaces the default program
# headers, but the code is -fPIE and _start applies its own RELATIVE
# relocations, so mark it ET_DYN for the kernel loader to place anywhere.
printf '\003\000' | dd of="$PORT_DIR/MPY.ELF" bs=1 seek=16 conv=notrunc status=none
if [ "$(readelf -rW "$PORT_DIR/MPY.ELF" | grep -c 'R_X86_64_' )" != \
     "$(readelf -rW "$PORT_DIR/MPY.ELF" | grep -c 'R_X86_64_RELATIVE')" ]; then
    echo "MPY.ELF has non-RELATIVE relocations; the self-relocator cannot apply them" >&2
    exit 1
fi
readelf -lW "$PORT_DIR/MPY.ELF" | sed -n '/Program Headers/,/Section to Segment/p'
sha256sum "$PORT_DIR/MPY.ELF"
