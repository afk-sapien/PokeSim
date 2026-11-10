"""The Gold, Silver and Crystal cartridge clock on the Core emulator.

Their MBC3 chip has a real-time clock. The Core emulator exposes it (``rtc_file``,
``export_rtc``, ``lock_clock``), and these helpers wrap those calls for Gen II use.
Runs can put the clock on game time: it is locked to emulated frames, so a fast run
reaches the next hour, day and weekday as fast as it plays (see ``follow_game_time``).
A backend without clock control raises CoreCapabilityError on the first clock call
instead of silently restarting the cartridge clock, because Gen II treats a clock
earlier than its saved time as a reset.
"""
from __future__ import annotations

import io
import math
import time

from ..emulator import Emulator as CoreEmulator
from ..errors import CoreCapabilityError
from ..memory_snapshot import snapshot_emulator

CLOCK_UNAVAILABLE = ('The installed PyBoy RS does not support the cartridge clock '
                     '(rtc_file, export_rtc and lock_clock), so this operation cannot be verified.')

# A fixed instant for reproducible runs: 2023-11-14 22:13:20 UTC.
FIXED_CLOCK_EPOCH = 1_700_000_000.0

# Core counts 4389/262144 seconds per completed frame, the Game Boy's real frame length.
SECONDS_PER_FRAME = 4389 / 262144


def _method(emulator, name):
    """A clock method of the emulator. An emulator without it is a missing capability."""
    try:
        return getattr(emulator, name)
    except AttributeError as error:
        raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error


def _clock_call(function, *args, **kwargs):
    """Run a Core clock call, reporting a backend without clock control as a missing capability."""
    try:
        return function(*args, **kwargs)
    except CoreCapabilityError:
        raise
    except NotImplementedError as error:
        raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error
    except TypeError as error:
        if 'rtc_file' in str(error):
            raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error
        raise
    except RuntimeError as error:
        if 'real-time clock' in str(error):
            raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error
        raise


def boot(rom, *, ram=None, rtc=None, sound=True, log_level='ERROR'):
    """Open a Gen II cartridge on Core. Pass the ROM as a path, bytes or a byte stream.

    ``ram`` is the 32 KiB battery save and ``rtc`` the ten-byte clock file saved with the
    cartridge, each as bytes or a stream. Core copies them, so the caller's streams are
    never written later. The emulator serves memory reads between steps from a snapshot.
    """
    if isinstance(rom, (bytes, bytearray, memoryview)):
        rom = io.BytesIO(bytes(rom))
    if ram is None:
        ram = bytes(32768)
    if isinstance(ram, (bytes, bytearray, memoryview)):
        ram = io.BytesIO(bytes(ram))
    options = {}
    if rtc:
        options['rtc_file'] = rtc
    factory = snapshot_emulator(CoreEmulator) if isinstance(CoreEmulator, type) else CoreEmulator
    emulator = _clock_call(factory, rom, window='null', sound_emulated=sound, ram_file=ram,
                           log_level=log_level, **options)
    emulator.set_emulation_speed(0)
    return emulator


def lock_clock(emulator, locked=True, *, at=None, follow_frames=False, rebase=False):
    """Freeze or release the cartridge clock.

    Lock before the first tick for reproducible runs. ``at`` is the instant to freeze at, by
    default the clock's current reading. ``rebase`` also moves the clock's zero point to ``at`` so
    a fresh cartridge reads exactly zero elapsed time there. Without it a clock restored from a
    file keeps its elapsed time. ``follow_frames`` advances the locked clock with emulated frames.
    """
    if not locked:
        if getattr(emulator, 'clock_locked', False):
            _clock_call(_method(emulator, 'unlock_clock'))
        return
    instant = _clock_call(_method(emulator, 'clock_now')) if at is None else at
    _clock_call(_method(emulator, 'lock_clock'), at=instant, follow_frames=follow_frames)
    if rebase:
        _clock_call(_method(emulator, 'set_rtc_timezero'), instant)


def stop_with_clock(emulator, save_stream, clock_stream):
    """Persist cartridge RAM and its ten-byte clock file together, then close the emulator."""
    _clock_call(_method(emulator, 'stop'), ram_file=save_stream, rtc_file=clock_stream)


def export_clock(emulator):
    """The ten-byte clock file of a running emulator, leaving it open."""
    return _clock_call(_method(emulator, 'export_rtc'))


def clock_elapsed(emulator):
    """Seconds the cartridge clock has counted: its current reading minus its zero point.

    This is what the game sees (the RTC days, hours, minutes and seconds). Gen II adds its own
    saved offsets to it, so this number going down is a clock going backward.
    """
    state = _clock_call(_method(emulator, 'rtc_state'))
    return float(state['clock']) - float(state['timezero'])


def clock_lock_state(emulator):
    """The clock lock as Core stores it in a checkpoint (``rtc_clock``), or None while unlocked."""
    return _clock_call(_method(emulator, 'clock_lock_state'))


def host_elapsed(emulator):
    """Seconds the clock would show on the host clock now, as an unlocked cartridge reads it."""
    state = _clock_call(_method(emulator, 'rtc_state'))
    return time.time() - float(state['timezero'])


def follow_game_time(emulator, elapsed=None):
    """Lock the cartridge clock to emulated frames at ``elapsed`` seconds, by default its reading now.

    From then on the clock moves only as frames run, so a run at 8x speed passes in-game hours
    eight times as fast and a paused run stops the clock. Returns the elapsed seconds it locked at.
    """
    state = _clock_call(_method(emulator, 'rtc_state'))
    zero = float(state['timezero'])
    target = float(state['clock']) - zero if elapsed is None else float(elapsed)
    _clock_call(_method(emulator, 'lock_clock'), at=_instant(zero, target), follow_frames=True)
    return target


def _instant(zero, elapsed):
    """The instant that reads at least ``elapsed`` against ``zero``, never a rounding step less."""
    instant = zero + elapsed
    while instant - zero < elapsed:
        instant = math.nextafter(instant, math.inf)
    return instant


def rebase_to_host(emulator):
    """Keep the reading but move the zero point so the host clock now shows the same time.

    A raw save state carries only the zero point. Anything that later opens it with an unlocked
    clock (a cable session, a save export, a check of a trade result) reads host time against that
    zero point. After this call that reading is the game time at the save plus the real time since,
    never less, so no copy of the cartridge ever sees its clock run backward.
    """
    elapsed = clock_elapsed(emulator)
    zero = time.time() - elapsed
    _clock_call(_method(emulator, 'set_rtc_timezero'), zero)
    _clock_call(_method(emulator, 'lock_clock'), at=_instant(zero, elapsed), follow_frames=True)
    return elapsed
