"""Pre-game screens on real cartridges.

Collected only when POKESIM_CORE_ROMS (red.gb, blue.gb, yellow.gb) or POKESIM_CORE_GEN2_ROMS
(gold.gbc, silver.gbc, crystal.gbc) names a folder of ROMs. Each cartridge boots with an empty
save, shows the intro and title, opens the NEW GAME menu on START and reaches the overworld.
POKESIM_CORE_SHORTCUT_STATES adds in-game states, such as Bill's PC on Gold and Silver,
that must never read as the title or the main menu.
"""
import io
import os
from pathlib import Path

import pytest

from pokecore import gen1_save
from pokecore.shortcuts import current_screen
from rom_games import new_gen1_game, new_gen2_game

pytest.importorskip('pyboy_rs')

FILES = {'red': 'red.gb', 'blue': 'blue.gb', 'yellow': 'yellow.gb', 'gold': 'gold.gbc', 'silver': 'silver.gbc',
         'crystal': 'crystal.gbc'}
GEN1 = ('red', 'blue', 'yellow')


def _rom(version):
    variable = 'POKESIM_CORE_ROMS' if version in GEN1 else 'POKESIM_CORE_GEN2_ROMS'
    directory = os.environ.get(variable)
    if not directory:
        pytest.skip(f'set {variable} to a folder of cartridges to run')
    path = Path(directory) / FILES[version]
    if not path.exists():
        pytest.skip(f'{FILES[version]} is not in {variable}')
    return path.read_bytes()


def _boot(rom, version):
    if version in GEN1:
        from pokecore.yellow import open_emulator
        emulator = open_emulator(io.BytesIO(rom), ram_file=io.BytesIO(bytes(32768)), window='null',
                                 sound_emulated=False, log_level='ERROR')
        emulator.set_emulation_speed(0)
        return emulator
    from pokecore.gen2.clock import boot
    return boot(rom, sound=False)


@pytest.mark.parametrize('version', sorted(FILES))
def test_boot_shows_the_title_then_the_main_menu(version):
    rom = _rom(version)
    emulator = _boot(rom, version)
    try:
        seen = []
        for _ in range(80):
            emulator.tick(30, False, False)
            seen.append(current_screen(emulator.memory, version))
        assert 'title' in seen and set(seen) <= {'title', 'transition'}, seen
        for _ in range(4):
            gen1_save.press(emulator, 'start', 40)
            seen.append(current_screen(emulator.memory, version))
            if seen[-1] == 'main_menu':
                break
        assert seen[-1] == 'main_menu', seen[80:]
    finally:
        emulator.stop(save=False)


@pytest.mark.parametrize('version', sorted(FILES))
def test_a_new_game_reads_as_the_overworld(version):
    rom = _rom(version)
    emulator = new_gen1_game(rom) if version in GEN1 else new_gen2_game(rom, version)
    try:
        assert current_screen(emulator.memory, version) == 'overworld'
    finally:
        emulator.stop(save=False)


STATES = os.environ.get('POKESIM_CORE_SHORTCUT_STATES')
# Bill's PC Change Box, a wild battle and the overworld, where 0.9.2 read Gold and Silver as the title.
IN_GAME = ['gold-billspc-changebox.state', 'silver-billspc-changebox.state', 'gold-route34-wild-battle.state',
           'gold-goldenrod-overworld.state', 'silver-np-gate-overworld.state', 'crystal-league-overworld.state',
           'red-navigation-wild-battle.state', 'yellow-fuchsia-overworld.state']


@pytest.mark.parametrize('state', IN_GAME)
def test_in_game_screens_never_read_as_pre_game(state):
    if not STATES or not (Path(STATES) / state).exists():
        pytest.skip(f'set POKESIM_CORE_SHORTCUT_STATES to a folder holding {state}')
    version = state.split('-')[0]
    rom = _rom(version)
    # A presses page through dialogue and battle text. The rest open and close menus.
    for plan in (['a'] * 30, ['start', 'down', 'a', None, 'b', 'b', 'down', 'down', 'a', 'a', 'b', 'b', 'b']):
        emulator = _boot(rom, version)
        try:
            emulator.load((Path(STATES) / state).read_bytes())
            seen = []
            for button in plan:
                gen1_save.press(emulator, button, 6)
                for _ in range(4):
                    emulator.tick(4, False, False)
                    seen.append(current_screen(emulator.memory, version))
            assert not {'title', 'main_menu'} & set(seen), seen
        finally:
            emulator.stop(save=False)
