"""Explicit trusted setup mutations, separate from read-only decoders.

These helpers are not controller actions. Do not expose them as benchmark agent
commands. Consumers own ROM verification, event definitions and reset eligibility.
Call only while the emulator is paused or under its exclusive simulation lock.
"""
from dataclasses import dataclass

from .gen1 import W_CUR_MAP, W_IS_IN_BATTLE
from .gen1_ui import read_screen


@dataclass(frozen=True)
class Flag:
    base: int
    bit: int

    def __post_init__(self):
        if (type(self.base) is not int or type(self.bit) is not int or self.bit < 0
                or not 0xC000 <= self.base <= self.address < 0xE000):
            raise ValueError('Flag must reference a bit in WRAM')

    @property
    def address(self):
        return self.base + self.bit // 8

    @property
    def mask(self):
        return 1 << (self.bit % 8)


@dataclass(frozen=True)
class Change:
    address: int
    before: int
    after: int


def update_flags(memory, changes):
    """Apply explicit flag values, preserving other bits. Return changed bytes.

    Preflight every read and reject conflicting assignments before any write.
    On a write failure, attempt to restore every affected byte and re-raise.
    """
    requested = {}
    for flag, value in changes:
        if not isinstance(flag, Flag) or type(value) is not bool:
            raise ValueError('Changes must be pairs of Flag and bool')
        key = (flag.address, flag.mask)
        if key in requested and requested[key] != value:
            raise ValueError('Conflicting values for one flag')
        requested[key] = value
    before = {address: memory[address] for address, _ in requested}
    after = dict(before)
    for (address, mask), value in requested.items():
        after[address] = after[address] | mask if value else after[address] & ~mask
    receipt = tuple(Change(address, value, after[address]) for address, value in before.items() if value != after[address])
    attempted = []
    try:
        for change in receipt:
            attempted.append(change)
            memory[change.address] = change.after
            if memory[change.address] != change.after:
                raise RuntimeError('Flag write did not persist')
    except Exception as error:
        for change in reversed(attempted):
            try:
                memory[change.address] = change.before
                if memory[change.address] != change.before:
                    raise RuntimeError('Rollback verification failed')
            except Exception as rollback_error:
                error.add_note(f'Could not restore address {change.address:#x}: {rollback_error}')
        raise
    return receipt


def reset_events(memory, flags, *, rooms):
    """Clear a caller-defined event group while its maps are unloaded.

    Supply all rooms affected by the event. Refuse battle, visible menus,
    dialogue and display transitions. The caller must verify script-idle state
    and cartridge identity before using this trusted setup API.
    """
    rooms = tuple(rooms)
    flags = tuple(flags)
    if not rooms or any(type(room) is not int or not 0 <= room <= 255 for room in rooms):
        raise ValueError('Supply the affected map IDs')
    if not flags:
        raise ValueError('Supply at least one event flag')
    screen = read_screen(memory)
    if (memory[W_CUR_MAP] in rooms or memory[W_IS_IN_BATTLE] or screen['cursor']
            or screen['textbox'] or screen['pause'] or not memory[0xFF40] & 128
            or memory[0xFF47] in (0, 85, 170, 255)):
        raise ValueError('Reset requires an idle overworld outside the affected maps')
    return update_flags(memory, ((flag, False) for flag in flags))


def reset_encounter(memory, *, event, visibility, room):
    """Reopen a stationary encounter by clearing its event and hide flags."""
    return reset_events(memory, (event, visibility), rooms=(room,))
