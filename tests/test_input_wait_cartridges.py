"""Core's ``input_wait`` finds each retail cartridge's menu loop, which a battle press waits on.

Runs on the configured Red, Yellow and Gen II cartridges, and skips each one that is not there.
"""
import os
from pathlib import Path

import pytest

from pokecore.shortcuts import input_wait

GEN2 = Path(os.environ.get('GEN2_CARTRIDGE_DIR', 'roms'))
SP = 0xDF00
# The returns inside each menu loop: HandleMenuInput_'s three calls in Gen I, and the far call
# return of StaticMenuJoypad and ScrollingMenuJoypad in Gen II. Then the byte where the joypad read
# leaves the held buttons: hJoyHeld in Gen I and hJoyDown in Gen II.
CARTRIDGES = {
    'red': (Path(os.environ.get('ROM_PATH', 'roms/pokered.gb')), (0x3AE8, 0x3AEC, 0x3AF8), 0xFFB4),
    'yellow': (Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc')), (0x3AD5, 0x3AD9, 0x3AE5), 0xFFB4),
    'gold': (GEN2 / 'gold.gbc', (0x1A6C, 0x1A76), 0xFFAA),
    'silver': (GEN2 / 'silver.gbc', (0x1A6C, 0x1A76), 0xFFAA),
    'crystal': (GEN2 / 'crystal.gbc', (0x1BCF, 0x1BD9), 0xFFA8),
}


@pytest.mark.parametrize('name', CARTRIDGES)
def test_each_cartridge_waits_inside_its_menu_loop_and_not_just_after_it(name):
    rom, returns, held = CARTRIDGES[name]
    if not rom.is_file():
        pytest.skip(f'no {name} cartridge')
    raw = bytearray(0x10000)
    raw[:0x8000] = rom.read_bytes()[:0x8000]
    for word in returns:
        raw[SP:SP + 2] = word.to_bytes(2, 'little')
        assert input_wait(raw, SP), hex(word)
        raw[held] = 0x01
        assert not input_wait(raw, SP), f'{word:#x} with A still held at the last read'
        raw[held] = 0
        raw[SP:SP + 2] = (word + 3).to_bytes(2, 'little')
        assert not input_wait(raw, SP), hex(word + 3)
