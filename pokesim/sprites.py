"""The 151 front portraits of a Red, Blue or Yellow cartridge, as PNG files.

The artwork is in the ROM the owner supplied, so there is nothing to ship and nothing to
download. Core decodes the pictures (``pokecore.sprites``). This module only picks the
species from PokeSim's game data and writes each portrait as a PNG.
"""
from __future__ import annotations

from pokecore.sprites import MEW_DEX, MEW_INTERNAL, front_sprite, png, sprite_bank

__all__ = ['MEW_DEX', 'MEW_INTERNAL', 'extract', 'front_sprite', 'png', 'sprite_bank']


def extract(rom: bytes, species: dict) -> dict[int, bytes]:
    """Decode every front portrait the cartridge holds, as dex number -> PNG bytes."""
    from .yellow import is_yellow
    yellow = is_yellow(rom)
    by_dex = {entry['dex']: internal for internal, entry in species.items() if entry.get('dex')}
    out = {}
    for dex in range(1, 152):
        internal = by_dex.get(dex)
        if internal is None:
            continue
        pixels, _, _ = front_sprite(rom, dex, internal, yellow)
        out[dex] = png(pixels)
    return out
