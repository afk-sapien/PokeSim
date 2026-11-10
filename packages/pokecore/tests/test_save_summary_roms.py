"""Save summaries of every PokeSim ladder rung on real cartridges.

Collected only when POKESIM_CORE_ROMS or POKESIM_CORE_GEN2_ROMS names a folder of ROMs. The ladder's
states are read in place from POKESIM_LADDER, default ~/Repos/pokesim/data/ladder, and no save is
committed. The ladder holds emulator states, and the game's Save menu is out of reach in many of them,
so each rung's SRAM image is built from its WRAM by the same mapping. Real Save-menu exports on a
few rungs then check that a built image reads the same as the file the game writes.
"""
import gzip
import io
import json
import os
from pathlib import Path

import pytest

from pokecore import gen1_save, save_summary as ss
from pokecore.gen1 import W_DEX_OWNED, W_PARTY_COUNT, W_PLAYER_NAME
from pokecore.gen2 import GameTables, clock, read_snapshot, save as gen2_save
from pokecore.gen2.memory_map import symbols

pytest.importorskip('pyboy_rs')

LADDER = Path(os.environ.get('POKESIM_LADDER', Path.home() / 'Repos/pokesim/data/ladder'))
ROMS = {'red': 'red.gb', 'blue': 'blue.gb', 'yellow': 'yellow.gb', 'gold': 'gold.gbc', 'silver': 'silver.gbc',
        'crystal': 'crystal.gbc'}
# The stage each rung means. Gen II's red rung stands before the fight, so Red is not beaten yet.
GEN1_STAGES = {'new_game': 'new game', 'league_first': 'league entered', 'champion_first': 'champion',
               'post_game': 'post-game'}
GEN2_STAGES = {'new_game': 'new game', 'league_first': 'league entered', 'champion_first': 'champion',
               'kanto_entry': 'kanto entered', 'red': 'kanto entered', 'post_game': 'red beaten'}
GEN1_MAIN_END = 0xDA80
# Gen II walking needs a map in the tables and a species with stats, nothing more from a real table.
TABLES = {'species': {str(dex): {'stats': [1] * 6} for dex in range(1, 252)},
          'maps': {str(group * 256 + number): {} for group in range(1, 30) for number in range(1, 130)}}


def _ladders():
    return sorted(path.parent.name for path in LADDER.glob('*/ladder.json'))


def _meta(ladder):
    return json.loads((LADDER / ladder / 'ladder.json').read_text())


def _rungs():
    return [(ladder, path.parent.name) for ladder in _ladders()
            for path in sorted((LADDER / ladder).glob('*/start.state'))]


def _state(ladder, rung):
    raw = (LADDER / ladder / rung / 'start.state').read_bytes()
    return gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw


def _rom(game):
    generation = 2 if game in ('gold', 'silver', 'crystal') else 1
    variable = 'POKESIM_CORE_GEN2_ROMS' if generation == 2 else 'POKESIM_CORE_ROMS'
    directory = os.environ.get(variable)
    path = Path(directory or '') / ROMS[game]
    if not directory or not path.exists():
        pytest.skip(f'{ROMS[game]} is not in {variable}')
    return path.read_bytes()


def _gen1_image(memory, raw_memory):
    """What the Save menu would write for this WRAM, with the boxes as SRAM holds them now."""
    image = bytearray(ss.SAVE_SIZE)
    for bank in (2, 3):
        image[bank * 0x2000:(bank + 1) * 0x2000] = bytes(raw_memory[bank, 0xA000:0xC000])
    image[ss.GEN1_PLAYER_NAME:ss.GEN1_PLAYER_NAME + 11] = bytes(memory[W_PLAYER_NAME:W_PLAYER_NAME + 11])
    image[W_DEX_OWNED - ss.GEN1_MAIN:GEN1_MAIN_END - ss.GEN1_MAIN] = bytes(memory[W_DEX_OWNED:GEN1_MAIN_END])
    image[ss.GEN1_PARTY:ss.GEN1_ACTIVE_BOX] = bytes(memory[W_PARTY_COUNT:W_PARTY_COUNT + 0x194])
    image[ss.GEN1_ACTIVE_BOX:ss.GEN1_ACTIVE_BOX + ss.GEN1_BOX_SIZE] = bytes(memory[GEN1_MAIN_END:GEN1_MAIN_END + ss.GEN1_BOX_SIZE])
    image[ss.GEN1_CHECKSUM] = ~sum(image[ss.GEN1_PLAYER_NAME:ss.GEN1_CHECKSUM]) & 0xFF
    return bytes(image)


def _gen2_image(version, memory):
    table = symbols(version)
    _, delta, end = ss.GEN2_LAYOUTS['crystal' if version == 'crystal' else None]
    image = bytearray(ss.SAVE_SIZE)
    for bank in (1, 2, 3):
        image[bank * 0x2000:(bank + 1) * 0x2000] = bytes(memory[bank, 0xA000:0xC000])
    image[ss.GEN2_CHECK_1] = ss.GEN2_CHECK_1_VALUE
    image[ss.GEN2_DATA:end] = bytes(memory[1, ss.GEN2_DATA + delta:end + delta])
    at = table['sChecksum'][1] - 0xA000 + 0x2000
    image[at:at + 2] = (sum(image[ss.GEN2_DATA:end]) & 0xFFFF).to_bytes(2, 'little')
    image[at + 2] = ss.GEN2_CHECK_2_VALUE
    return bytes(image)


def _image(game, ladder, rung):
    """The emulator is stopped before this returns, so a rung holds no process open."""
    rom = _rom(game)
    state = _state(ladder, rung)
    if _meta(ladder)['generation'] == 1:
        emulator = gen1_save._open(rom, bytes(ss.SAVE_SIZE))
        try:
            emulator.load_state(io.BytesIO(state))
            return _gen1_image(emulator.memory, getattr(emulator, '_emulator', emulator).memory)
        finally:
            emulator.stop(save=False)
    emulator = clock.boot(rom, sound=False)
    try:
        emulator.load_state(io.BytesIO(state))
        return _gen2_image(game, emulator.memory)
    finally:
        emulator.stop(save=False)


def _expected(generation, rung):
    if rung.startswith('badges_'):
        return f'{rung.removeprefix("badges_")} badges'
    return (GEN2_STAGES if generation == 2 else GEN1_STAGES)[rung]


@pytest.mark.parametrize('ladder, rung', _rungs())
def test_every_ladder_rung_has_the_right_stage(ladder, rung):
    meta = _meta(ladder)
    summary = ss.summarize_save(_image(meta['game'], ladder, rung))
    assert summary.generation == meta['generation']
    assert summary.stage == _expected(meta['generation'], rung)


def _export_gen1(rom, state):
    # A map-entry script may still hold the trainer, so let it finish before opening the menu.
    emulator = gen1_save._open(rom, bytes(ss.SAVE_SIZE))
    try:
        emulator.load_state(io.BytesIO(state))
        emulator.tick(900, render=False)
        state = emulator.save()
    finally:
        emulator.stop(save=False)
    return gen1_save.export(rom, state)


@pytest.mark.parametrize('ladder, rung', [('red', 'badges_8'), ('blue', 'post_game'), ('yellow', 'post_game')])
def test_gen1_save_menu_export_matches_the_summary(ladder, rung):
    game = _meta(ladder)['game']
    summary = ss.summarize_save(_export_gen1(_rom(game), _state(ladder, rung)))
    built = ss.summarize_save(_image(game, ladder, rung))
    assert (built.player_name, built.badges, built.party, built.box_counts, built.dex_owned, built.hall_of_fame) == (
        summary.player_name, summary.badges, summary.party, summary.box_counts, summary.dex_owned, summary.hall_of_fame)
    assert summary.stage == _expected(1, rung)
    assert summary.party and 1 <= summary.party[0].level <= 100
    assert (summary.version == 'yellow') == (game == 'yellow')
    assert 0 < summary.dex_owned <= summary.dex_seen <= 151


@pytest.mark.parametrize('ladder, rung', [('gold', 'champion_first'), ('crystal', 'champion_first'),
                                          ('crystal', 'post_game'), ('silver', 'post_game')])
def test_gen2_save_menu_export_matches_the_summary(ladder, rung):
    game = _meta(ladder)['game']
    rom = _rom(game)
    tables = GameTables({'game': game, **TABLES})
    emulator = clock.boot(rom, sound=True)
    try:
        emulator.load_state(io.BytesIO(_state(ladder, rung)))
        for _ in range(12):
            gen2_save.press(emulator, 'b', 60)
            if gen2_save._walking(read_snapshot(emulator.memory, tables)):
                break
        state = emulator.save()
    finally:
        emulator.stop(save=False)
    raw = gen2_save.export(rom, state, tables)
    summary = ss.summarize_save(raw, rom=rom)
    built = ss.summarize_save(_image(game, ladder, rung), rom=rom)
    assert summary.stage == _expected(2, rung)
    assert summary.version == game
    assert summary.party and summary.party[0].name
    # Dismissing text changes nothing the summary reads, so the built image agrees with the real file.
    assert (built.player_name, built.badges, built.party, built.box_counts, built.dex_owned, built.hall_of_fame) == (
        summary.player_name, summary.badges, summary.party, summary.box_counts, summary.dex_owned, summary.hall_of_fame)
