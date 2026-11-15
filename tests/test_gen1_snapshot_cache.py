"""A Gen I snapshot is decoded once per step and never outlives a change to the machine.

Runs on retail Red and Yellow cartridges, and skips each one that is not configured.
"""
import io
import os
from pathlib import Path

import pytest

from pokecore.emulator import Memory
from pokecore.gen1 import W_MONEY
from pokesim import ram, yellow
from test_trade_save import ABRA, MACHOKE, populate

RED_ROM = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
YELLOW_ROM = Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc'))
CARTRIDGES = [
    pytest.param((RED_ROM, False), id='red',
                 marks=pytest.mark.skipif(not RED_ROM.exists(), reason='no ROM')),
    pytest.param((YELLOW_ROM, True), id='yellow',
                 marks=pytest.mark.skipif(not YELLOW_ROM.exists() or not yellow.is_yellow(YELLOW_ROM),
                                          reason='no retail Yellow ROM')),
]


@pytest.fixture(params=CARTRIDGES)
def machine(request):
    rom, is_yellow = request.param
    pb = yellow.open_emulator(str(rom), yellow=is_yellow, snapshot=True, window='null', sound_emulated=False,
                              ram_file=io.BytesIO(bytes(32768)))
    pb.set_emulation_speed(0)
    pb.tick(120, False, False)
    populate(pb.memory, contents=((1, ABRA, 30), (3, MACHOKE, 41)))
    yield pb
    pb.stop(save=False)


@pytest.fixture
def decodes(monkeypatch):
    """How many times the snapshot was really decoded."""
    calls = []
    decode = ram._decode_snapshot

    def counted(mem, frame):
        calls.append(frame)
        return decode(mem, frame)
    monkeypatch.setattr(ram, '_decode_snapshot', counted)
    return calls


DECODE = ram._decode_snapshot


def fresh(pb, frame):
    """A decode of live memory, which never goes through the snapshot or its kept value."""
    live = Memory(pb)
    return DECODE(yellow.YellowMemory(live) if hasattr(pb, 'raw_memory') else live, frame)


def test_a_step_decodes_its_snapshot_once(machine, decodes):
    first = ram.read_snapshot(machine.memory, 7)
    assert ram.read_snapshot(machine.memory, 7) is first
    assert decodes == [7]
    assert first == fresh(machine, 7)
    assert first.stored_pokemon
    assert ram.read_snapshot(machine.memory, 8).frame == 8
    assert decodes == [7, 8]


def test_a_tick_a_write_or_a_load_drops_the_kept_snapshot(machine, decodes):
    memory = machine.memory
    state = machine.save()
    before = ram.read_snapshot(memory, 1)
    memory[W_MONEY] = 0x42
    written = ram.read_snapshot(memory, 1)
    assert written is not before and written.money != before.money
    assert written == fresh(machine, 1)
    machine.tick(1, False, False)
    ticked = ram.read_snapshot(memory, 1)
    assert ticked is not written and ticked == fresh(machine, 1)
    machine.load(state)
    loaded = ram.read_snapshot(memory, 1)
    assert loaded is not ticked and loaded == before == fresh(machine, 1)
    assert len(decodes) == 4


def test_memory_without_a_snapshot_decodes_every_time(machine, decodes):
    live = Memory(machine)
    memory = yellow.YellowMemory(live) if hasattr(machine, 'raw_memory') else live
    assert ram.read_snapshot(memory, 3) == ram.read_snapshot(memory, 3)
    assert len(decodes) == 2
