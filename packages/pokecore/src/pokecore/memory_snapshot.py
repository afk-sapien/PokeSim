"""A per-step memory snapshot for Core emulators.

Observation reads hundreds of small ranges from work RAM and cartridge RAM between two
emulator steps. Reading each through the binding costs at least one native call per range,
so a snapshot emulator keeps a lazy copy instead:

- each WRAM bank (``0xD000-0xDFFF`` of banks 0 to 7, and ``0xC000-0xCFFF``) and each
  cartridge RAM bank is copied with one ``read_bank_bytes`` call the first time a banked
  read needs it (``snapshot_window``). PyBoy RS 0.1.1 serves that with a single native
  call. Older bindings fall back to per-byte bank reads with identical values.
- the unbanked view of ``0xC000-0xDFFF`` (what the CPU currently sees, which is all Gen I
  needs) is copied with one ``read_bytes`` call, and plain ``memory[address]``,
  ``memory[start:stop]`` and ``memory.read_bytes`` inside it are served from that copy.

The copy is never stale. Every public emulator method except the short read-only list in
READ_ONLY bumps a mutation counter before and after it runs, and so does every memory write.
A copy taken under an older counter is discarded. Ticks, writes, state loads, checkpoint
restores, clock changes and inputs therefore all invalidate it. While a mutating call is
running, for example inside a hook callback during a tick, reads always go to the live machine.
Reads from a closed machine raise exactly as live reads do.

Ported from PokeSim's pokesim/gen2/snapshot.py.
"""
from __future__ import annotations

import functools
import operator

# Public Core methods that never change emulated memory. Everything else invalidates the
# snapshot, including methods a newer Core adds later.
READ_ONLY = frozenset({
    'audio_samples', 'checkpoint', 'clock_control_available', 'clock_lock_state', 'clock_locked',
    'clock_now', 'export_rtc', 'has_rtc', 'profiling_counters', 'rtc_registers', 'rtc_state', 'save',
    'save_state', 'screenshot', 'sequence_progress', 'set_emulation_speed', 'symbol_lookup',
})

WRAM, SRAM, VIEW = 0, 1, 2
VIEW_START, VIEW_STOP = 0xC000, 0xE000
_ERRORS = (ValueError, TypeError, OverflowError, IndexError, RuntimeError)


def _view_range(key):
    """(start, stop, single) when ``key`` is an unbanked read inside the WRAM view, else None."""
    if isinstance(key, slice):
        if key.step not in (None, 1) or key.start is None or key.stop is None:
            return None
        try:
            start, stop = operator.index(key.start), operator.index(key.stop)
        except TypeError:
            return None
        if VIEW_START <= start < stop <= VIEW_STOP:
            return start, stop, False
        return None
    if type(key) is int and VIEW_START <= key < VIEW_STOP:
        return key, key + 1, True
    return None


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

        def _block(self, key, read):
            """The cached block for ``key``, reading it with ``read`` once per generation, or None."""
            owner = self._owner
            if owner._busy:
                return None
            generation = owner._generation
            captured, banks = self._banks
            if captured != generation:
                banks = {}
                self._banks = (generation, banks)
            block = banks.get(key)
            if block is None:
                try:
                    block = read()
                except _ERRORS:
                    return None
                if owner._generation != generation or owner._busy:
                    return None
                banks[key] = block
            return block

        def _bank_bytes(self, bank, start, stop):
            read = getattr(super(), 'read_bank_bytes', None)
            if read is not None:
                return bytes(read(bank, start, stop))
            # bytearray() converts the list of ints about three times faster than bytes().
            return bytes(bytearray(super().__getitem__((bank, slice(start, stop)))))

        def snapshot_window(self, bank, address, size):
            """Bytes ``address .. address + size`` of ``bank`` from the snapshot, or None.

            Returns None whenever the result could differ from a live banked read: outside
            one WRAM or SRAM bank window, during a mutating call, on an invalid bank or a
            closed machine. The caller then reads live memory.
            """
            end = address + size
            if 0xC000 <= address and end <= 0xE000 and address >> 12 == (end - 1) >> 12:
                kind, start, offset = WRAM, address & 0xF000, address & 0xFFF
            elif 0xA000 <= address and end <= 0xC000:
                kind, start, offset = SRAM, 0xA000, address - 0xA000
            else:
                return None
            stop = start + (0x1000 if kind == WRAM else 0x2000)
            key = (kind, bank) if start != 0xC000 else (kind, bank, start)
            block = self._block(key, lambda: self._bank_bytes(bank, start, stop))
            return None if block is None else block[offset:offset + size]

        def snapshot_view(self, start, stop):
            """Unbanked bytes ``start .. stop`` inside 0xC000-0xDFFF from the snapshot, or None."""
            if not VIEW_START <= start <= stop <= VIEW_STOP:
                return None
            live = super().read_bytes
            block = self._block((VIEW, None), lambda: bytes(live(VIEW_START, VIEW_STOP)))
            return None if block is None else block[start - VIEW_START:stop - VIEW_START]

        def __getitem__(self, key):
            selected = _view_range(key)
            if selected is not None:
                start, stop, single = selected
                block = self.snapshot_view(start, stop)
                if block is not None:
                    return block[0] if single else list(block)
            return super().__getitem__(key)

        def read_bytes(self, start, stop):
            try:
                start, stop = operator.index(start), operator.index(stop)
            except TypeError:
                return super().read_bytes(start, stop)
            block = self.snapshot_view(start, stop)
            return block if block is not None else super().read_bytes(start, stop)

    SnapshotMemory.__qualname__ = SnapshotMemory.__name__ = f'Snapshot{base.__name__}'
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
    """``base`` (a Core Emulator class) whose ``memory`` serves reads from a per-step snapshot.

    The result is a subclass with the same constructor and public API. Pass it wherever an
    emulator class is expected, for example ``snapshot_emulator(Emulator)(rom)``.
    """
    from .emulator import Memory

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
