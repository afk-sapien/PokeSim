"""Bulk reads remain detached, bounded, and consistent after execution and load."""
import pytest

from pokecore.emulator import Emulator, demo_rom


def test_bulk_bytes_follow_writes_execution_and_restore():
    pytest.importorskip('pyboy_rs')
    emu = Emulator(demo_rom())
    try:
        emu.memory[0xc000:0xc010] = list(range(16))
        first = emu.memory.read_bytes(0xc000, 0xc010)
        state = emu.save()
        emu.memory[0xc000] = 99
        assert first == bytes(range(16))
        assert emu.memory.read_bytes(0xc000, 0xc010)[0] == 99
        emu.tick(2)
        assert emu.memory.read_bytes(0xc000, 0xe000) == bytes(emu.memory[0xc000:0xe000])
        emu.load(state)
        assert emu.memory.read_bytes(0xc000, 0xc010) == first
        assert emu.memory.read_bytes(65536, 65536) == b''
        for start, stop in ((-1, 10), (10, 9), (0, 65537)):
            with pytest.raises(ValueError):
                emu.memory.read_bytes(start, stop)
    finally:
        emu.close()
    with pytest.raises(RuntimeError):
        emu.memory.read_bytes(0, 1)
