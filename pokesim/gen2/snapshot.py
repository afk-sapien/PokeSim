"""A per-step memory snapshot for Gen II emulators.

Observation reads hundreds of small ranges from work RAM and cartridge RAM between two
emulator steps. Reading each through the binding costs at least one native call per range, so the
Gen II emulator keeps a lazy copy of each WRAM and SRAM bank instead. A bank is copied with
one banked slice through Core's public memory API the first time it is needed after the
machine last changed. PyBoy RS with the ``bank_bytes`` feature serves that slice with one
native call, so all 32 KB of WRAM and 32 KB of SRAM take at most twelve calls.

The copy is never stale. Every public emulator method except a short read-only list bumps a
mutation counter before and after it runs, and so does every memory write. A copy taken under
an older counter is discarded. While a mutating call is running, for example inside a hook
callback during a tick, reads always go to the live machine.
"""
from __future__ import annotations

import functools

# Public Core methods that never change emulated memory. Everything else invalidates the
# snapshot, including methods a newer Core adds later.
READ_ONLY = frozenset({
    'audio_samples', 'checkpoint', 'clock_control_available', 'clock_lock_state', 'clock_locked',
    'clock_now', 'export_rtc', 'has_rtc', 'profiling_counters', 'rtc_registers', 'rtc_state', 'save',
    'save_state', 'screenshot', 'sequence_progress', 'set_emulation_speed', 'symbol_lookup',
})

WRAM, SRAM = 0, 1


def snapshot_memory_class(base):
    """The Core Memory class extended with snapshot windows and write invalidation."""

    class SnapshotMemory(base):
        def __init__(self, owner):
            super().__init__(owner)
            self._banks = (None, {})

        def __setitem__(self, key, value):
            owner = self._owner
            owner._generation += 1
            try:
                super().__setitem__(key, value)
            finally:
                owner._generation += 1

        def snapshot_window(self, bank, address, size):
            """Bytes ``address .. address + size`` of ``bank`` from the snapshot, or None.

            Returns None whenever the result could differ from a live banked read: outside
            one WRAM or SRAM bank window, during a mutating call, on an invalid bank or a
            closed machine. The caller then reads live memory.
            """
            owner = self._owner
            if owner._busy:
                return None
            end = address + size
            if 0xC000 <= address and end <= 0xE000 and address >> 12 == (end - 1) >> 12:
                kind, start, offset = WRAM, 0xD000, address & 0xFFF
            elif 0xA000 <= address and end <= 0xC000:
                kind, start, offset = SRAM, 0xA000, address - 0xA000
            else:
                return None
            generation = owner._generation
            captured, banks = self._banks
            if captured != generation:
                banks = {}
                self._banks = (generation, banks)
            block = banks.get((kind, bank))
            if block is None:
                try:
                    stop = start + (0x1000 if kind == WRAM else 0x2000)
                    # bytearray() converts the list of ints about three times faster than bytes().
                    block = bytes(bytearray(super().__getitem__((bank, slice(start, stop)))))
                except (ValueError, TypeError, OverflowError, IndexError, RuntimeError):
                    return None
                if owner._generation != generation or owner._busy:
                    return None
                banks[(kind, bank)] = block
            return block[offset:offset + size]

    return SnapshotMemory


def _mutating(function):
    @functools.wraps(function)
    def call(self, *args, **kwargs):
        self._generation += 1
        self._busy += 1
        try:
            return function(self, *args, **kwargs)
        finally:
            self._busy -= 1
            self._generation += 1
    return call


@functools.cache
def snapshot_emulator(base):
    """``base`` (a Core Emulator class) whose ``memory`` serves reads from a per-step snapshot."""
    from pokesim_core.emulator import Memory

    memory_class = snapshot_memory_class(Memory)

    def __init__(self, *args, **kwargs):
        self._generation = 0
        self._busy = 1
        try:
            base.__init__(self, *args, **kwargs)
        finally:
            self._busy = 0
        self.memory = memory_class(self)

    namespace = {'__init__': __init__, '__doc__': base.__doc__, '__module__': __name__}
    for klass in reversed(base.__mro__[:-1]):
        for name, value in vars(klass).items():
            if name.startswith('_') or name in READ_ONLY or not callable(value) \
                    or isinstance(value, (type, staticmethod, classmethod)):
                continue
            namespace[name] = _mutating(value)
    return type(f'Snapshot{base.__name__}', (base,), namespace)
