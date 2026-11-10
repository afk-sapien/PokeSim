import io
import sys
from types import SimpleNamespace

import pytest

from pokecore.emulator import GameBoy
from pokecore.rom import RomInfo


class FakeImage:
    def save(self, buffer, format):
        assert format == "PNG"
        buffer.write(b"fake-png")


class FakePyBoy:
    instances = []

    def __init__(self, rom, **options):
        self.rom = rom
        self.options = options
        self.memory = bytearray(65536)
        self.screen = SimpleNamespace(raw_buffer=bytes(160 * 144 * 4))
        self.frames = 0
        self.frame_count = 0
        self.sound = SimpleNamespace(raw_buffer=b"", raw_buffer_head=0)
        self.inputs = []
        self.stops = []
        self.instances.append(self)

    def set_emulation_speed(self, speed):
        self.speed = speed

    def button_press(self, button):
        self.inputs.append(("press", button))

    def button_release(self, button):
        self.inputs.append(("release", button))

    def tick(self, frames, render=True, sound=True):
        self.frames += frames
        self.frame_count += frames
        self.render = render

    def save_state(self, stream):
        stream.write(b"saved-state")

    def load_state(self, stream):
        self.loaded = stream.read()
        if self.loaded == b"invalid":
            raise ValueError("Invalid state")

    def stop(self, save=True, ram_file=None):
        self.stops.append(save)


@pytest.fixture
def fake(monkeypatch):
    FakePyBoy.instances = []
    monkeypatch.setitem(sys.modules, "pyboy_rs", SimpleNamespace(PyBoy=FakePyBoy))
    def require(path, *, allowed_games):
        if "red" not in allowed_games:
            raise ValueError("Excluded game")
        return RomInfo("sha1", "sha256", "red", "Red", True)
    monkeypatch.setattr("pokecore.emulator.require_rom", require)
    monkeypatch.setattr("pokecore.emulator.Path.read_bytes", lambda _: bytes(32768))
    return FakePyBoy


def test_no_background_frames_and_explicit_inputs(fake):
    with GameBoy("synthetic.gb") as game:
        underlying = fake.instances[-1]
        assert underlying.frames == 0
        assert len(game.rom_sha256) == 64
        assert len(game.screen.raw_buffer) == 160 * 144 * 4
        assert game.save() == b"saved-state"
        assert game.memory[0] == underlying.memory[0]
        assert underlying.frames == 0
        game.press("a")
        game.tick(8, render=False)
        game.release("a")
        game.tick(2)
        assert underlying.frames == 10
        assert underlying.inputs == [("press", "a"), ("release", "a")]
    assert underlying.stops == [False]
    game.close()
    assert underlying.stops == [False]


def test_each_instance_uses_independent_sram(fake):
    first, second = GameBoy("one.gb"), GameBoy("two.gb")
    one, two = fake.instances
    assert isinstance(one.options["ram_file"], io.BytesIO)
    assert "rtc_file" not in one.options
    one.options["ram_file"].write(b"changed")
    assert two.options["ram_file"].getvalue() == bytes(32768)
    assert one.speed == 0
    assert one.options["sound_emulated"] is False
    assert one.options["window"] == "null"
    first.close()
    second.close()


def test_state_load_and_failure_cleanup(fake):
    with GameBoy("one.gb", b"good"):
        assert fake.instances[-1].loaded == b"good"
    with pytest.raises(ValueError, match="Invalid state"):
        GameBoy("one.gb", b"invalid")
    assert fake.instances[-1].stops == [False]


@pytest.mark.parametrize("frames", [0, -1, True, 1.5])
def test_invalid_frame_counts_do_not_advance(fake, frames):
    with GameBoy("one.gb") as game:
        with pytest.raises(ValueError):
            game.tick(frames)
        assert fake.instances[-1].frames == 0


def test_closed_and_unknown_controls_fail(fake):
    game = GameBoy("one.gb")
    with pytest.raises(ValueError):
        game.press("rewind")
    with pytest.raises(ValueError):
        game.release("bad")
    game.close()
    with pytest.raises(RuntimeError, match="closed"):
        game.tick()


def test_excluded_rom_never_constructs_pyboy(fake):
    with pytest.raises(ValueError, match="Excluded"):
        GameBoy("one.gb", allowed_games=("blue",))
    assert not fake.instances
