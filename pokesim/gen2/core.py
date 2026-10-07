"""Gen II access to the Core emulator, including the cartridge clock.

Gold, Silver and Crystal cartridges set the CGB flag in their header, so the
Core backend enables Color hardware from the ROM itself. Their MBC3 chip has a
real-time clock. Core with RTC support (``rtc_file``, ``export_rtc``,
``lock_clock``) exposes it, and this module is the only place that talks to
those calls. When the installed Core or PyBoy RS lacks them, the operations
raise CoreCapabilityError instead of silently restarting the cartridge clock,
because Gen II treats a clock earlier than its saved time as a reset.
"""
from __future__ import annotations

import inspect
import io

from pokesim_core.emulator import Emulator as CoreEmulator

CLOCK_UNAVAILABLE = ('The installed Core or PyBoy RS does not support the cartridge clock '
                     '(rtc_file, export_rtc and lock_clock), so this operation cannot be verified.')

# A fixed instant for reproducible runs: 2023-11-14 22:13:20 UTC.
FIXED_CLOCK_EPOCH = 1_700_000_000.0


class CoreCapabilityError(NotImplementedError):
    """The installed Core and PyBoy RS lack a feature that Gen II requires."""


def _core_has_clock():
    return hasattr(CoreEmulator, 'export_rtc') and 'rtc_file' in inspect.signature(CoreEmulator.__init__).parameters


def _clock_call(function, *args, **kwargs):
    """Run a Core clock call, reporting a backend without clock control as a missing capability."""
    try:
        return function(*args, **kwargs)
    except CoreCapabilityError:
        raise
    except NotImplementedError as error:
        raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error
    except RuntimeError as error:
        if 'real-time clock' in str(error):
            raise CoreCapabilityError(CLOCK_UNAVAILABLE) from error
        raise


def boot(rom, *, ram=None, rtc=None, sound=True, log_level='ERROR'):
    """Open a Gen II cartridge on Core. Pass the ROM as a path or a byte stream.

    ``rtc`` is the ten-byte clock file saved with the cartridge, as bytes or a stream.
    Core copies it, so the caller's stream is never written later.
    """
    if ram is None:
        ram = io.BytesIO(bytes(32768))
    options = {}
    if rtc:
        if not _core_has_clock():
            raise CoreCapabilityError(CLOCK_UNAVAILABLE)
        options['rtc_file'] = rtc
    emulator = _clock_call(CoreEmulator, rom, window='null', sound_emulated=sound, ram_file=ram,
                           log_level=log_level, **options)
    emulator.set_emulation_speed(0)
    return emulator


def lock_clock(emulator, locked=True, *, at=None, follow_frames=False, rebase=False):
    """Freeze or release the cartridge clock.

    Lock before the first tick for reproducible runs. ``at`` is the instant to freeze at, by
    default the clock's current reading. ``rebase`` also moves the clock's zero point to ``at`` so
    a fresh cartridge reads exactly zero elapsed time there, the way a frozen clock behaved in
    the PyBoy exploration. Without it a clock restored from a file keeps its elapsed time.
    ``follow_frames`` advances the locked clock with emulated frames.
    """
    if not locked:
        if getattr(emulator, 'clock_locked', False):
            _clock_call(emulator.unlock_clock)
        return
    if not hasattr(emulator, 'lock_clock'):
        raise CoreCapabilityError(CLOCK_UNAVAILABLE)
    instant = _clock_call(emulator.clock_now) if at is None else at
    _clock_call(emulator.lock_clock, at=instant, follow_frames=follow_frames)
    if rebase:
        _clock_call(emulator.set_rtc_timezero, instant)


def stop_with_clock(emulator, save_stream, clock_stream):
    """Persist cartridge RAM and its ten-byte clock file together, then close the emulator."""
    if not hasattr(emulator, 'export_rtc'):
        raise CoreCapabilityError(CLOCK_UNAVAILABLE)
    _clock_call(emulator.stop, ram_file=save_stream, rtc_file=clock_stream)


def export_clock(emulator):
    """The ten-byte clock file of a running emulator, leaving it open."""
    if not hasattr(emulator, 'export_rtc'):
        raise CoreCapabilityError(CLOCK_UNAVAILABLE)
    return _clock_call(emulator.export_rtc)
