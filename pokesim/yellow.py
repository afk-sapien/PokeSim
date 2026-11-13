"""Pokémon Yellow on the Red and Blue engine.

Yellow keeps the Red and Blue memory layout except for one byte, so PokeSim keeps
one set of Red addresses. ``pokecore.yellow`` holds the view that translates them
and the emulator that exposes it, so snapshots, menus, resets and saves read the
same fields on every Gen 1 cartridge. ``raw_memory`` on a Yellow emulator keeps
the untranslated addresses, for the CPU stack and the Yellow-only Pikachu fields.

This module keeps the names PokeSim imports.
"""
from pokecore.yellow import (
    HRAM,
    PIKACHU_HAPPINESS,
    YELLOW_NAME,
    YELLOW_SHA1,
    YellowEmulator,
    YellowMemory,
    address,
    is_yellow,
)
from pokecore.yellow import open_emulator as _core_open_emulator

__all__ = [
    'HRAM', 'PIKACHU_HAPPINESS', 'YELLOW_NAME', 'YELLOW_SHA1', 'YellowEmulator', 'YellowMemory',
    'address', 'is_yellow', 'open_emulator',
]


def open_emulator(rom, default=None, yellow=None, **kwargs):
    """pokecore's ``open_emulator``, with ``yellow`` naming the variant of a patched ROM.

    A patched ROM's checksum no longer identifies it. pokecore before 0.12.0 had no ``yellow``
    argument, so the choice is made here. 0.12.0 takes it too, and this wrapper keeps the callers unchanged.
    """
    if yellow is None:
        return _core_open_emulator(rom, default, **kwargs)
    if yellow:
        return YellowEmulator(rom, **kwargs)
    if default is None:
        from pokecore.emulator import Emulator as default
    return default(rom, **kwargs)
