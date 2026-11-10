"""Checks against real cartridges. Set POKESIM_CORE_ROMS to a folder of ROMs to run them.

CI has no ROMs, so the emulator job, which forbids skips, ignores this file.
"""
import os
from pathlib import Path

import pytest

from pokecore import cartridges, gen1_link_metadata, gen2_link_metadata, randomizer, romdata, timecapsule as tc
from pokecore.cartridges import identify, read_header, unpack
from pokecore.rom import inspect_rom, require_rom

ROMS = os.environ.get('POKESIM_CORE_ROMS')
VERSIONS = ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal')


def _cartridges():
    """Yield (path, bytes, cartridge) for each recognised ROM file in POKESIM_CORE_ROMS."""
    for path in sorted(Path(ROMS).iterdir()):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        cartridge = identify(raw)
        if cartridge is not None:
            yield path, raw, cartridge


@pytest.mark.skipif(not ROMS, reason='set POKESIM_CORE_ROMS to a folder of cartridges to run')
def test_real_cartridges_identify_and_match_their_headers():
    seen = set()
    for path, raw, cartridge in _cartridges():
        seen.add(cartridge.version)
        assert cartridges.header_matches(raw, cartridge), path.name
        assert cartridges.refusal_reason(raw) is None and unpack(raw) == raw
        assert cartridges.identify_file(path) == cartridge
        info = require_rom(path, allowed_games=cartridges.SLOTS)
        assert info.game == cartridge.version and info.verified
        assert inspect_rom(path).verified == (cartridge.version in ('red', 'blue'))
    assert seen


@pytest.mark.skipif(not ROMS, reason='set POKESIM_CORE_ROMS to a folder of cartridges to run')
def test_real_cartridges_carry_link_code():
    for path, raw, cartridge in _cartridges():
        builds = gen1_link_metadata if cartridge.generation == 1 else gen2_link_metadata
        assert builds.verify_signatures(raw, cartridge.sha1) == [], path.name
        if cartridge.generation == 2:
            assert tc.communication_ok(raw, cartridge.version)


@pytest.mark.skipif(not ROMS, reason='set POKESIM_CORE_ROMS to a folder of cartridges to run')
@pytest.mark.parametrize('version', VERSIONS)
def test_randomized_patch_round_trips_on_real_cartridges(version):
    rom = _rom_for(version).read_bytes()
    data = romdata.load(rom)
    assert romdata.patch_rom(rom) == rom
    overrides = randomizer.randomize(data, 8, randomizer.Options(trainers=True))
    patched = romdata.patch_rom(rom, overrides)
    header = read_header(patched)
    assert header.header_checksum_ok and header.global_checksum_ok
    assert romdata.load(patched, version=version).canonical() == data.with_overrides(overrides).canonical()


# Shortcuts on real cartridges -------------------------------------------------------
# POKESIM_CORE_SHORTCUT_STATES names a folder with your own save states and a
# shortcuts.json manifest, a list of entries like
#   {"rom": "red", "state": "wild-battle.state", "machine": "RunAway", "args": [], "kwargs": {},
#    "expect": "completed"}
# ``machine`` is a class from ``pokecore.shortcuts`` and ``rom`` is any version, Gen 1 or Gen 2.
# ``expect`` is "completed" (effect seen and the screen settled) or "refused" (the
# game or the shortcut refused, and the screen still settled). No states ship here.
STATES = os.environ.get('POKESIM_CORE_SHORTCUT_STATES')


def _shortcut_cases():
    if not (ROMS and STATES):
        return []
    import json
    manifest = Path(STATES) / 'shortcuts.json'
    return json.loads(manifest.read_text()) if manifest.is_file() else []


def _rom_for(version):
    for path, _, cartridge in _cartridges():
        if cartridge.version == version:
            return path
    pytest.skip(f'no {version} cartridge in POKESIM_CORE_ROMS')


@pytest.mark.skipif(not (ROMS and STATES), reason='set POKESIM_CORE_ROMS and POKESIM_CORE_SHORTCUT_STATES to run')
@pytest.mark.parametrize('case', _shortcut_cases(), ids=lambda case: f"{case['machine']}:{case['state']}")
def test_shortcuts_finish_at_a_resting_screen_on_real_cartridges(case):
    from pokecore import shortcuts
    from pokecore.emulator import Emulator
    emulator = Emulator(str(_rom_for(case['rom'])), sound_emulated=False)
    emulator.load((Path(STATES) / case['state']).read_bytes())
    from pokecore.emulator import BUTTONS
    for button in BUTTONS:
        emulator.release(button)
    machine = getattr(shortcuts, case['machine'])(*case.get('args', []), version=case['rom'], **case.get('kwargs', {}))
    done = shortcuts.drive(machine, emulator)
    assert done.settled, done.outcome
    assert done.completed == (case.get('expect', 'completed') == 'completed'), done.outcome
    screen = shortcuts.current_screen(emulator.memory, case['rom'])
    assert screen in ('overworld', 'battle_menu', 'move_menu', 'party', 'mart', 'pc', 'transition',
                      'switch_prompt'), screen
