import io
from pathlib import Path

import pytest

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.palettes import PALETTES, validate_palette
from pokesim.app.manager import Manager


@pytest.mark.parametrize('value', [None, [], 'unknown', 5])
def test_invalid_palette_rejected(value):
    with pytest.raises(ValueError, match='palette'):
        validate_palette(value)
    with pytest.raises(ValueError, match='palette'):
        Manager.validate_adventure_settings({'palette': value})


def test_palette_reload_changes_pixels_without_changing_game_state(monkeypatch):
    rom = Path('roms/pokered.gb')
    if not rom.exists():
        pytest.skip('Private ROM unavailable')
    emu = Emulator.__new__(Emulator)
    emu.rom, emu.isolated_ram = rom, True
    monkeypatch.setattr(config, 'PALETTE', 'original')
    original = emu._boot()
    try:
        original.tick(300, render=True, sound=False)
        state = io.BytesIO()
        original.save_state(state)
        original.tick(1, render=True, sound=False)
        original_pixels = original.screen.image.tobytes()
        for name in PALETTES:
            monkeypatch.setattr(config, 'PALETTE', name)
            other = emu._boot()
            try:
                other.load_state(io.BytesIO(state.getvalue()))
                other.tick(1, render=True, sound=False)
                assert bytes(other.memory[0xa000:0xe000]) == bytes(original.memory[0xa000:0xe000])
                if name != 'original':
                    assert other.screen.image.tobytes() != original_pixels
            finally:
                other.stop(save=False)
    finally:
        original.stop(save=False)
