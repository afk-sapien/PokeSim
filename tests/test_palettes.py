import io
from pathlib import Path
import threading

from PIL import Image
from pokesim_core.emulator import Emulator as PyBoy
import pytest

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.palettes import PALETTES, recolor, validate_palette
from pokesim.app.manager import Manager


@pytest.mark.parametrize('value', [None, [], 'unknown', 5])
def test_invalid_palette_rejected(value):
    with pytest.raises(ValueError, match='palette'):
        validate_palette(value)
    with pytest.raises(ValueError, match='palette'):
        Manager.validate_adventure_settings({'palette': value})


@pytest.mark.parametrize('name', PALETTES)
def test_every_shade_maps_exactly_without_mutating_source(name):
    original = Image.new('RGB', (4, 1))
    original.putdata([(value & 255,) * 3 for value in PALETTES['original']])
    before = original.tobytes()
    colored = recolor(original, name)
    assert [colored.getpixel((x, 0)) for x in range(4)] == [tuple((value >> shift) & 255 for shift in (16, 8, 0))
                                       for value in PALETTES[name]]
    assert original.tobytes() == before


def test_live_palette_matches_native_renderer_without_advancing_paused_game(monkeypatch):
    rom = Path('roms/pokered.gb')
    if not rom.exists():
        pytest.skip('Private ROM unavailable')
    emu = Emulator.__new__(Emulator)
    emu.rom, emu.isolated_ram = rom, True
    emu.frame_cond = threading.Condition()
    emu.frame_seq = 0
    emu.paused = True
    monkeypatch.setattr(config, 'PALETTE', 'blue')
    emu.pb = emu._boot()
    try:
        emu.pb.tick(300, render=True, sound=False)
        checkpoint = emu._state_bytes()
        emu.pb.load_state(io.BytesIO(checkpoint))
        emu.pb.tick(1, render=True, sound=False)
        emu.pb.tick(1, render=True, sound=False)
        before = emu._state_bytes()
        native = emu.pb.screen.image.tobytes()
        for name, colors in PALETTES.items():
            other = PyBoy(str(rom), window='null', sound_emulated=True,
                          color_palette=colors, ram_file=io.BytesIO(bytes(32768)))
            try:
                other.set_emulation_speed(0)
                other.load_state(io.BytesIO(checkpoint))
                other.tick(1, render=True, sound=False)
                other.tick(1, render=True, sound=False)
                previous_seq = emu.frame_seq
                assert emu.set_palette(name) == {'palette': name}
                assert emu.frame_seq == previous_seq + 1
                assert emu.paused
                expected = other.screen.image.convert('RGB')
                assert emu._image().tobytes() == expected.tobytes()
                assert Image.open(io.BytesIO(emu.current_frame())).tobytes() == expected.tobytes()
                shot = Image.open(io.BytesIO(emu._shot_png()))
                assert shot.resize(expected.size, Image.Resampling.NEAREST).tobytes() == expected.tobytes()
                assert emu._state_bytes() == before
                assert emu.pb.screen.image.tobytes() == native
            finally:
                other.stop(save=False)
        with pytest.raises(ValueError):
            emu.set_palette('invalid')
        assert emu.palette == name
        assert emu._state_bytes() == before
    finally:
        emu.pb.stop(save=False)
