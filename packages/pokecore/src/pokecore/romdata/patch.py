"""Write an override map back into a copy of the caller's cartridge.

:func:`patch_rom` writes the placed Pokemon an override map changes: starters at every
site the scripts read, wild encounter tables (each Gen II grass table with its morning,
day and night slots) and trainer parties. It also writes the TM and HM move list. Every
table is rewritten in place, so a patch never moves data or pointers. A change that would
resize a table, such as a different party size, raises ``ValueError`` instead.

No game checks the global checksum, but emulators and tools report it, so it is fixed up
after any change. The header checksum, the only one the boot ROM checks, covers bytes a
patch never writes. With no overrides the input comes back byte for byte.
"""
from __future__ import annotations

from . import gen1, gen2

UNPATCHED = ('species', 'evolutions', 'learnsets')


def effective_data(rom, overrides=None, version=None):
    """The game data a planner should see once ``overrides`` are applied to ``rom``."""
    from . import load
    return load(rom, version).with_overrides(overrides)


def patch_rom(rom, overrides=None, version=None) -> bytes:
    """A copy of ``rom`` with ``overrides`` written into it. ``rom`` itself is unchanged."""
    from . import load
    original = bytes(rom)
    data = load(original, version)
    effective = data.with_overrides(overrides)
    for name in UNPATCHED:
        if getattr(effective, name) != getattr(data, name):
            raise ValueError(f'patch_rom cannot write {name} overrides yet')
    reader = gen1 if data.generation == 1 else gen2
    found = data.layout
    writer = _Writer(original)
    patched = writer.patched

    for sites, species in zip(found.starters, effective.starters):
        for site in sites:
            patched[site] = species

    wild = gen1.encounter_sites(original, found.wild[0][1]) if data.generation == 1 \
        else gen2.encounter_sites(original, found)
    for key, offset, table in wild:
        writer.table(offset, reader.encode_encounter(table), reader.encode_encounter(effective.encounters[key]), key)

    for key, offset, trainer in reader.trainer_sites(original, found):
        new = effective.trainers[key]
        for field in ('name', 'type'):
            if new.get(field) != trainer.get(field):
                raise ValueError(f'{key}: patch_rom cannot change a trainer {field}')
        first = original[offset]
        writer.table(offset, reader.encode_party(trainer, first), reader.encode_party(new, first), key)

    patched[found.tm_moves:found.tm_moves + found.tm_count] = bytes(effective.tm_moves)

    if patched == original:
        return original
    patched[0x14E:0x150] = ((sum(patched) - patched[0x14E] - patched[0x14F]) & 0xFFFF).to_bytes(2, 'big')
    return bytes(patched)


class _Writer:
    """Writes tables in place. Maps that share one table must agree on what it becomes."""

    def __init__(self, original):
        self.original = original
        self.patched = bytearray(original)
        self.written = {}

    def table(self, offset, current, new, key):
        if self.original[offset:offset + len(current)] != current:
            raise ValueError(f'{key}: the ROM bytes do not match the table read from them')
        if len(new) != len(current):
            raise ValueError(f'{key}: the new table is {len(new)} bytes, the ROM holds {len(current)}')
        if offset in self.written and self.written[offset][1] != new:
            raise ValueError(f'{key} shares its ROM table with {self.written[offset][0]}, so both must match')
        self.written.setdefault(offset, (key, new))
        self.patched[offset:offset + len(new)] = new
