"""Frames are encoded only for an audience, and no faster than the stream shows them."""
import time
from unittest.mock import Mock

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.play_clock import PlayClock


def emulator():
    emu = Emulator.__new__(Emulator)
    emu.play_clock = PlayClock()
    emu.play_clock.seed(0)
    emu.frame = 0
    emu.stopping = False
    emu.speed, emu.manual_mode = 0, False      # Max speed: no pacing between steps
    emu.pb = Mock()
    emu._publish_frame = Mock()
    emu._observe = Mock()
    emu._pace = Mock()
    return emu


def test_no_frames_are_encoded_when_nobody_is_watching():
    emu = emulator()
    emu._tick(600)
    assert emu._publish_frame.call_count == 0


def test_watching_starts_frames_again():
    emu = emulator()
    emu.watch()
    emu._tick(60)
    assert emu._publish_frame.call_count > 0


def test_a_fast_run_does_not_encode_faster_than_the_stream():
    """At Max speed a tick step is microseconds, but the stream still only shows STREAM_FPS."""
    emu = emulator()
    emu.watch()
    started = time.monotonic()
    emu._tick(6000)                            # 100 seconds of game time, run flat out
    elapsed = time.monotonic() - started
    # Bounded by the wall clock, not by how many frames went past: the old behaviour would have
    # encoded 6000 / CHUNK = 1500 of them.
    assert emu._publish_frame.call_count <= elapsed * config.STREAM_FPS / 0.8 + 2


def test_watching_lapses_after_the_grace_period():
    emu = emulator()
    emu.watch()
    emu._watch_until -= 60.0                   # as if the last request were a minute ago
    emu._tick(600)
    assert emu._publish_frame.call_count == 0


def test_current_frame_marks_interest_and_returns_the_latest():
    emu = emulator()
    emu.frame_jpeg = b'jpeg'
    assert emu.current_frame() == b'jpeg'
    emu._tick(60)
    assert emu._publish_frame.call_count > 0
