"""Gen II access to the Core emulator, with explicit errors for missing RTC support.

Gold, Silver and Crystal cartridges set the CGB flag in their header, so the
Core backend enables Color hardware from the ROM itself. Cartridge clock files
and the clock lock that the PyBoy-based exploration used are not part of Core's
public contract. Operations that need them raise instead of silently restarting
the cartridge clock, because Gen II treats a clock earlier than its saved time
as a reset.
"""
from __future__ import annotations

import io

from pokesim_core.emulator import Emulator as CoreEmulator

CLOCK_UNAVAILABLE = ('Core does not provide cartridge clock import or export. PyBoy RS rejects '
                     'rtc_file and exposes no clock lock, so this operation cannot be verified.')


class CoreCapabilityError(NotImplementedError):
    """The installed Core and PyBoy RS lack a feature that Gen II requires."""


def boot(rom, *, ram=None, rtc=None, sound=True, log_level='ERROR'):
    """Open a Gen II cartridge on Core. Pass the ROM as a path or a byte stream."""
    if rtc:
        raise CoreCapabilityError(CLOCK_UNAVAILABLE)
    if ram is None:
        ram = io.BytesIO(bytes(32768))
    emulator = CoreEmulator(rom, window='null', sound_emulated=sound, ram_file=ram, log_level=log_level)
    emulator.set_emulation_speed(0)
    return emulator


def lock_clock(emulator, locked=True):
    """Freeze or release the cartridge clock. Core's clock always follows the host."""
    if locked:
        raise CoreCapabilityError(CLOCK_UNAVAILABLE)


def stop_with_clock(emulator, save_stream, clock_stream):
    """Persist cartridge RAM and its clock together, as the PyBoy exploration did."""
    raise CoreCapabilityError(CLOCK_UNAVAILABLE)
