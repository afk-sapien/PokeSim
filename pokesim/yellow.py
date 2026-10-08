"""Pokémon Yellow on the Red and Blue engine.

Yellow keeps the Red and Blue memory layout except for one byte. pret/pokeyellow
drops wOnCGB at 0xCF1A and adds Pikachu state later in WRAM, so every Red WRAM
address from 0xCF1B through the end of the box data sits one byte lower. HRAM
moves a few joypad and layout bytes. Cartridge RAM is identical.

PokeSim keeps one set of Red addresses. A Yellow emulator exposes memory through
a view that translates those addresses, so snapshots, menus, resets and saves
read the same fields on every Gen 1 cartridge. Raw access stays available for
the CPU stack, which both games keep at the same place.
"""
from __future__ import annotations

import hashlib
import operator
from pathlib import Path

from pokesim_core.emulator import Emulator as CoreEmulator

YELLOW_SHA1 = 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'
YELLOW_NAME = 'Pokemon Yellow (USA, Europe) (GBC,SGB Enhanced)'

# Red WRAM [start, stop) ranges and the Yellow offset, from pret symbol files.
# 0xDEE2 onward is CPU stack space in both games and stays raw.
_SHIFT_START, _SHIFT_STOP = 0xCF1B, 0xDEE2
# Raw Yellow address of wPikachuHappiness, from pokeyellow.sym.
PIKACHU_HAPPINESS = 0xD46F
_HRAM = {0xFFF4: 0xFFF9, 0xFFF6: 0xFFFA, 0xFFF7: 0xFFFB, 0xFFF8: 0xFFF5, 0xFFF9: 0xFFF8}


def is_yellow(rom) -> bool:
    raw = rom if isinstance(rom, (bytes, bytearray)) else Path(rom).read_bytes()
    return hashlib.sha1(raw).hexdigest() == YELLOW_SHA1


def address(red: int) -> int:
    """Return the Yellow address that holds the Red field at ``red``."""
    if _SHIFT_START <= red < _SHIFT_STOP:
        return red - 1
    return _HRAM.get(red, red)


class YellowMemory:
    """Red-layout view of a Yellow machine. Banked keys outside WRAM pass through."""

    def __init__(self, owner):
        self._owner = owner

    @property
    def raw(self):
        return self._owner.raw_memory

    def _read(self, start, stop):
        return self._owner.raw_memory.read_bytes(start, stop)

    def _byte(self, key):
        return self._owner.raw_memory[address(operator.index(key))]

    def __getitem__(self, key):
        if isinstance(key, tuple):
            bank, inner = key
            if isinstance(inner, slice):
                if 0xC000 <= (inner.start or 0) < 0xE000 or 0xFF80 <= (inner.start or 0):
                    return list(self[inner])
                return self.raw[key]
            if 0xC000 <= inner < 0xE000 or inner >= 0xFF80:
                return self[inner]
            return self.raw[key]
        if isinstance(key, slice):
            if key.step not in (None, 1):
                return [self[i] for i in range(*key.indices(65536))]
            start = 0 if key.start is None else operator.index(key.start)
            stop = 65536 if key.stop is None else operator.index(key.stop)
            return list(self.read_bytes(start, stop))
        return self._byte(key)

    def read_bytes(self, start, stop):
        start, stop = operator.index(start), operator.index(stop)
        if not 0 <= start <= stop <= 65536:
            raise ValueError('Invalid memory range')
        return _red_bytes(self._read, start, stop)

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            bank, inner = key
            if isinstance(inner, slice) or not (0xC000 <= inner < 0xE000 or inner >= 0xFF80):
                self.raw[key] = value
                return
            key = inner
        if isinstance(key, slice):
            start = 0 if key.start is None else operator.index(key.start)
            values = list(value) if not isinstance(value, int) else [value] * len(range(*key.indices(65536)))
            for offset, byte in enumerate(values):
                self.raw[address(start + offset)] = byte
            return
        self.raw[address(operator.index(key))] = value

    def __iter__(self):
        raise TypeError('Read an explicit memory range')


def _red_bytes(read, start, stop):
    """Assemble Red-layout bytes for [start, stop) from a raw Yellow reader."""
    out = bytearray()
    cursor = start
    while cursor < stop:
        if cursor < _SHIFT_START:
            end = min(stop, _SHIFT_START)
            out += read(cursor, end)
        elif cursor < _SHIFT_STOP:
            end = min(stop, _SHIFT_STOP)
            out += read(cursor - 1, end - 1)
        elif cursor < 0xFFF4 or cursor >= 0xFFFA:
            end = min(stop, 0xFFF4) if cursor < 0xFFF4 else stop
            out += read(cursor, end)
        else:
            end = cursor + 1
            out += read(address(cursor), address(cursor) + 1)
        cursor = end
    return bytes(out)


class YellowEmulator(CoreEmulator):
    """A Core emulator whose ``memory`` uses Red addresses on a Yellow cartridge."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw_memory = self.memory
        self.memory = YellowMemory(self)

    def _advance(self, frames, render, sound, read_range=None):
        if read_range is None:
            return super()._advance(frames, render, sound)
        super()._advance(frames, render, sound)
        return self.memory.read_bytes(*read_range)


def open_emulator(rom, default=None, **kwargs):
    """Construct the Core emulator that matches the cartridge.

    ``rom`` is a path or a binary stream, as for the Core emulator. Red and Blue use ``default``,
    which is the Core emulator unless the caller names its own class.
    """
    if hasattr(rom, 'read'):
        raw = rom.read()
        import io
        rom = io.BytesIO(raw)
    else:
        raw = Path(rom).read_bytes()
    if hashlib.sha1(raw).hexdigest() == YELLOW_SHA1:
        return YellowEmulator(rom, **kwargs)
    if default is None:
        import pokesim_core.emulator
        default = pokesim_core.emulator.Emulator
    return default(rom, **kwargs)
