# Network OS ring-3 MicroPython runtime. Run through build.sh, which pins
# the MicroPython revision and builds outside /mnt/c.

ifndef MICROPY_TOP
$(error MICROPY_TOP must point at a MicroPython checkout)
endif

include $(MICROPY_TOP)/py/mkenv.mk

QSTR_DEFS = qstrdefsport.h
# Compression inflates x86-64 code about tenfold at -Os; plain strings are smaller.
MICROPY_ROM_TEXT_COMPRESSION = 0

include $(TOP)/py/py.mk

INC += -I.
INC += -I$(TOP)
INC += -I$(BUILD)

CFLAGS += $(INC) -Wall -std=gnu99 -Os -DNDEBUG
CFLAGS += -ffreestanding -fPIE -fvisibility=hidden -mgeneral-regs-only
CFLAGS += -fno-stack-protector -fcf-protection=none -fno-asynchronous-unwind-tables
CFLAGS += -fdata-sections -ffunction-sections
CSUPEROPT = -Os

LD = $(CC)
LDFLAGS += -nostdlib -static-pie -T link.ld
LDFLAGS += -Wl,--no-dynamic-linker,-z,norelro,-z,max-page-size=4096,--gc-sections
LDFLAGS += -Wl,-Map=$(BUILD)/firmware.map
LIBS = -lgcc

SRC_C = \
	main.c \
	shared/libc/printf.c \
	shared/libc/string0.c \
	shared/libc/abort_.c \
	shared/runtime/stdout_helpers.c \
	shared/runtime/gchelper_generic.c \
	extmod/modjson.c \
	extmod/modhashlib.c \
	extmod/modbinascii.c \

# Scan the port and the extra modules for qstrs and module registrations.
SRC_QSTR += main.c extmod/modjson.c extmod/modhashlib.c extmod/modbinascii.c

OBJ += $(PY_CORE_O)
OBJ += $(addprefix $(BUILD)/, $(SRC_C:.c=.o))

all: $(BUILD)/firmware.elf

$(BUILD)/firmware.elf: $(OBJ)
	$(ECHO) "LINK $@"
	$(Q)$(LD) $(LDFLAGS) -o $@ $^ $(LIBS)
	$(Q)$(SIZE) $@

include $(TOP)/py/mkrules.mk
