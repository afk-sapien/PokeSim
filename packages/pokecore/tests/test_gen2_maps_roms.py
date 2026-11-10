"""Live Gen II collision on real cartridges. Collected only when POKESIM_CORE_GEN2_ROMS is set.

Each case plays a new game from the title screen to the bedroom, then decodes the loaded map
blocks. Set POKESIM_CORE_GEN2_DATA to a directory of <version>/data.json game tables to also
compare against the consumer's recorded collision.
"""
import io
import json
import os
from pathlib import Path

import pytest

from pokecore import gen2
from pokecore.gen2 import maps
from pokecore.gen2.ram import Memory

pytest.importorskip('pyboy_rs')

BEDROOM = 24 * 256 + 7
# PLAYERS_HOUSE_2F as a new game loads it. The stairs are 0x7A, the TV 0x97, the radio 0x91 and the
# PC 0x95. A new game puts the bed (block 27) and the PC (block 31) in, so the live grid differs from
# the map file pret builds (STATIC) where they stand.
RECORDED = [
    0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x95, 0x7A,
    0x00, 0x00, 0x07, 0x07, 0x97, 0x91, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x07, 0x00, 0x00, 0x00, 0x07, 0x07, 0x00, 0x00,
    0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
]
STATIC = list(RECORDED)
STATIC[6], STATIC[32], STATIC[40] = 0x07, 0x00, 0x00
# The bedroom's blocks from its tileset. Blocks it never loads read as walls.
BLOCK_COLLISION = [[7, 7, 7, 7]] * 32
BLOCK_COLLISION[2:8] = [[7, 122, 0, 0], [7, 7, 151, 145], [7, 7, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [7, 7, 0, 0]]
BLOCK_COLLISION[27], BLOCK_COLLISION[31] = [7, 0, 7, 0], [149, 122, 0, 0]


def bedroom_tables(version):
    entry = {'name': 'Bedroom', 'constant': 'PLAYERS_HOUSE_2F', 'width': 8, 'height': 6,
             'block_collision': BLOCK_COLLISION, 'collision': STATIC, 'objects': []}
    return gen2.GameTables({'game': version, 'maps': {str(BEDROOM): entry}})


def press(emulator, button, wait=40):
    if button:
        emulator.press(button)
    emulator.tick(8, render=False, sound=False)
    if button:
        emulator.release(button)
    emulator.tick(wait, render=False, sound=False)


def to_bedroom(version):
    """A new game standing in the bedroom, with the default clock and the first preset names."""
    from pokecore.emulator import Emulator
    rom = Path(os.environ['POKESIM_CORE_GEN2_ROMS']) / f'{version}.gbc'
    if not rom.exists():
        pytest.skip(f'{rom.name} is not in POKESIM_CORE_GEN2_ROMS')
    emulator = Emulator(io.BytesIO(rom.read_bytes()), ram_file=io.BytesIO(bytes(32768)), sound_emulated=False)
    data = bedroom_tables(version)
    mem = Memory(emulator.memory, data)
    for step in range(600):
        rows = mem.tiles()
        if any('▶NEW NAME' in row for row in rows):
            press(emulator, 'down')
            continue
        snapshot = gen2.read_snapshot(emulator.memory, data, cache=False)
        if step > 30 and snapshot.map == BEDROOM and '┌' not in rows[12] and not any('▶' in row for row in rows):
            press(emulator, None, 60)
            if '┌' not in mem.tiles()[12]:
                return emulator, data
        press(emulator, 'start' if step < 3 else 'a')
    emulator.stop(save=False)
    raise AssertionError(f'{version} never reached the bedroom')


@pytest.mark.parametrize('version', gen2.VERSIONS)
def test_live_collision_of_the_bedroom_matches_the_recorded_grid(version):
    emulator, data = to_bedroom(version)
    try:
        snapshot = gen2.read_snapshot(emulator.memory, data, cache=False)
        assert maps.collision(emulator.memory, data, snapshot) == RECORDED
        directory = os.environ.get('POKESIM_CORE_GEN2_DATA')
        if directory:
            full = gen2.GameTables(json.loads((Path(directory) / version / 'data.json').read_text()))
            assert maps.collision(emulator.memory, full, snapshot) == RECORDED
            assert full.maps[BEDROOM]['collision'] == STATIC
    finally:
        emulator.stop(save=False)
