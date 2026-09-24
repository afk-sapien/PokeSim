"""A journal entry caught during a fade gets its picture once the screen shows something again."""
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image, ImageDraw

from pokesim.emulator import RETAKE_FRAMES, Emulator, blank_frame
from pokesim.events import Event
from pokesim.store import Store
from test_events import snap


def solid(color):
    return Image.new('RGB', (160, 144), color)


def scene():
    image = solid((255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 100, 159, 143), fill=(0, 0, 0))
    draw.rectangle((70, 50, 86, 66), fill=(96, 96, 96))
    return image


def test_blank_frames_are_single_colour_screens():
    assert blank_frame(solid((255, 255, 255)))
    assert blank_frame(solid((0, 0, 0)))
    speck = solid((0, 0, 0))
    speck.putpixel((5, 5), (255, 255, 255))
    assert blank_frame(speck)
    assert not blank_frame(scene())


class Ntfy:
    def __init__(self):
        self.sent = []

    def wants(self, ev):
        return True

    def send(self, title, body, **kwargs):
        self.sent.append((title, kwargs['image']))


def game(tmp_path, screen):
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.ntfy = Ntfy()
    emu.frame = 1000
    emu.mem = SimpleNamespace(championships=0)
    emu._image = lambda: screen[0]
    return emu


def test_a_blank_screenshot_is_retaken_and_pushed_when_the_fade_ends(tmp_path):
    screen = [solid((0, 0, 0))]
    emu = game(tmp_path, screen)
    emu._handle_events([Event('badge', 'Boulder Badge', 'Brock beaten', priority=5)], snap())
    [entry] = emu.store.events()
    faded = (emu.store.shots / entry['shot']).read_bytes()
    assert emu.ntfy.sent == []
    emu.frame += 30
    emu._retake_shots()
    assert emu.ntfy.sent == [] and (emu.store.shots / entry['shot']).read_bytes() == faded
    screen[0] = scene()
    emu.frame += 30
    emu._retake_shots()
    retaken = (emu.store.shots / entry['shot']).read_bytes()
    assert retaken != faded and not blank_frame(Image.open(emu.store.shots / entry['shot']).convert('RGB'))
    assert emu.ntfy.sent == [('Boulder Badge', retaken)]
    emu._retake_shots()
    assert len(emu.ntfy.sent) == 1


def test_a_screen_that_stays_blank_is_kept_and_pushed_at_the_deadline(tmp_path):
    screen = [solid((0, 0, 0))]
    emu = game(tmp_path, screen)
    emu._handle_events([Event('map', 'Rock Tunnel', 'A dark cave', priority=2)], snap())
    emu.frame += RETAKE_FRAMES - 1
    emu._retake_shots()
    assert emu.ntfy.sent == []
    emu.frame += 1
    emu._retake_shots()
    assert [title for title, _ in emu.ntfy.sent] == ['Rock Tunnel']


def test_a_clear_screen_is_kept_and_pushed_at_once(tmp_path):
    emu = game(tmp_path, [scene()])
    emu._handle_events([Event('catch', 'Caught PIKACHU', 'A new entry', priority=4)], snap())
    assert [title for title, _ in emu.ntfy.sent] == ['Caught PIKACHU']
    assert emu._retakes == ()


def test_observing_retakes_before_reading_the_game(monkeypatch):
    emu = Emulator.__new__(Emulator)
    emu._retake_shots = Mock(side_effect=RuntimeError('stop here'))
    try:
        emu._observe()
    except RuntimeError:
        pass
    emu._retake_shots.assert_called_once()
