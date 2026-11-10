"""Known format-15 audio migration on caller-owned checkpoint bytes."""
import math
import struct


def enable_checkpoint_sound(raw):
    """Repair only disabled APU clocks in a supported in-memory checkpoint.

    PyBoy saves disabled sound clocks as MAX_CYCLES and restores them even when
    sound_emulated=True. Old files are never rewritten. The offsets below follow
    the pinned PyBoy 2.7.0 DMG v15 CPU, LCD, and Sound serializers. Unknown formats
    pass through untouched. A real-ROM round-trip test guards this adapter.
    """
    # Motherboard header, CPU registers, then monochrome LCD state.
    apu = 5 + 26 + 8192 + 160 + 11 + 144 * 5 + 5 + 24 + 1
    clocks = apu + 24 + 1602 + 1
    if (len(raw) < clocks + 67
            or raw[0] != 15 or raw[4] != 0):
        return raw
    head, samples, period = struct.unpack_from('<QQd', raw, apu)
    targets = struct.unpack_from('<ddQ', raw, clocks)
    if (head != 0 or samples != 800 or not math.isclose(period, 70224 / 800)
            or targets != (float(1 << 31), float(1 << 31), 1 << 31)):
        return raw
    data = bytearray(raw)
    cycles = struct.unpack_from('<Q', raw, clocks + 24)[0]
    struct.pack_into('<ddQ', data, clocks, cycles + period, cycles + 8192, math.ceil(cycles + period))
    # Disabled emulation ignored all register writes. Power on and route future
    # game music to both channels. Notes resume when the game next writes them.
    data[clocks + 56] = 0x80
    data[clocks + 58:clocks + 66] = bytes((128, 64, 32, 16, 8, 4, 2, 1))
    data[clocks + 66] = 0x77
    return bytes(data)
