"""Gen II hook signatures and setup writes on real cartridges. Collected only when POKESIM_CORE_GEN2_ROMS is set.

Set POKESIM_CORE_GEN2_DATA to a directory of <version>/data.json game tables to also check the
hooks against the consumer's full symbol table.
"""
import io
import json
import os
from pathlib import Path

import pytest

from pokecore import gen2
from pokecore.gen2 import hooks, resets

pytest.importorskip('pyboy_rs')

FOUGHT, SHOWN, GS = 'EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA', 'EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER'
# Indexes from the pinned pret event constants, the same in all three games.
EVENTS = {FOUGHT: 792, SHOWN: 1853, GS: 832}
CHIKORITA = {'name': 'Chikorita', 'growth': 'MEDIUM_SLOW', 'stats': [45, 49, 65, 45, 49, 65],
             'learnset': [[1, 33], [1, 45], [8, 75], [12, 115]]}


def boot(version):
    """A live machine with a blank battery, past the boot code."""
    from pokecore.emulator import Emulator
    rom = Path(os.environ['POKESIM_CORE_GEN2_ROMS']) / f'{version}.gbc'
    if not rom.exists():
        pytest.skip(f'{rom.name} is not in POKESIM_CORE_GEN2_ROMS')
    machine = Emulator(io.BytesIO(rom.read_bytes()), ram_file=io.BytesIO(bytes(32768)), sound_emulated=False)
    machine.tick(200, render=False, sound=False)
    return machine


def tables(version):
    return gen2.GameTables({'game': version, 'species': {152: CHIKORITA},
                            'moves': {33: {'pp': 35}, 45: {'pp': 40}}, 'events': EVENTS})


def every_hook(memory, data):
    found = [*hooks.capture_hooks(memory, data), hooks.encounter_hook(memory, data), hooks.contest_hook(memory, data),
             hooks.hatch_hook(memory, data), hooks.step_hook(memory, data)]
    marts = hooks.mart_hooks(memory, data)
    assert set(marts) == {'opened', 'priced', 'subtotal', 'bought'}
    return found + list(marts.values())


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_every_hook_signature_verifies_on_the_cartridge(version):
    machine = boot(version)
    try:
        found = every_hook(machine.memory, tables(version))
        assert len(set(found)) == len(found) == 10
        directory = os.environ.get('POKESIM_CORE_GEN2_DATA')
        if directory:
            full = gen2.GameTables(json.loads((Path(directory) / version / 'data.json').read_text()))
            assert every_hook(machine.memory, full) == found
            assert all(tuple(full.symbols[name]) == address for name, address in hooks.LABELS[version].items())
    finally:
        machine.stop(save=False)


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_box_gift_round_trips_through_read_snapshot(version):
    machine = boot(version)
    data = tables(version)
    try:
        before = gen2.read_snapshot(machine.memory, data, cache=False)
        box = before.active_box
        position = before.box_counts[box]
        resets.box_gift(machine.memory, data, 152, 'seed', box, position, nicknames=('LEAF',))
        after = gen2.read_snapshot(machine.memory, data, cache=False)
        mon = next(mon for mon in after.stored if (mon.box, mon.position) == (box, position))
        assert (mon.species, mon.level, mon.nick, mon.moves, mon.pp, mon.friendship) == (
            152, 5, 'LEAF', (33, 45, 0, 0), (35, 40, 0, 0), 70)
        assert after.box_counts[box] == position + 1 and len(after.stored) == len(before.stored) + 1
        assert after.owned == before.owned | {152} and 152 in after.seen
        assert after.party == before.party and after.event_flags == before.event_flags
        other = (box + 1) % 14
        resets.box_gift(machine.memory, data, 152, 'other', other, after.box_counts[other])
        last = gen2.read_snapshot(machine.memory, data, cache=False)
        assert [mon.nick for mon in last.stored if mon.box == other] == ['CHIKORITA']
    finally:
        machine.stop(save=False)


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_flag_writes_are_visible_through_snapshot_event(version):
    machine = boot(version)
    data = tables(version)
    try:
        before = gen2.read_snapshot(machine.memory, data, cache=False)
        assert not before.event(FOUGHT) and not before.event(SHOWN)
        assert resets.write_flag(machine.memory, data, FOUGHT, True)
        snapshot = gen2.read_snapshot(machine.memory, data, cache=False)
        assert snapshot.event(FOUGHT) and not snapshot.event(SHOWN)
        changed = [i for i, (a, b) in enumerate(zip(before.event_flags, snapshot.event_flags)) if a != b]
        assert changed == [792 // 8]
        assert resets.reset_event(machine.memory, data, [(FOUGHT, False), (SHOWN, True)]) == (FOUGHT, SHOWN)
        snapshot = gen2.read_snapshot(machine.memory, data, cache=False)
        assert not snapshot.event(FOUGHT) and snapshot.event(SHOWN)
        if version == 'crystal':
            resets.set_gs_ball(machine.memory, data)
            assert gen2.ram.Memory(machine.memory, data).byte('sGSBallFlag') == 0x0B
        else:
            with pytest.raises(ValueError):
                resets.set_gs_ball(machine.memory, data)
    finally:
        machine.stop(save=False)
