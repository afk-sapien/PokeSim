"""Which Pokémon a journal entry is about, so the journal can draw it.

A catch, gift, hatch, evolution or level-up is often logged mid-cutscene, while the screen is
black or showing a dialog box, so its screenshot says little. The title names the species, so the
journal can show that Pokémon's sprite instead, the way a cable trade already does.
"""
from __future__ import annotations

import re

SPECIES_TYPES = ('catch', 'obtain', 'hatch', 'evolve', 'level')
# The species name is the last capture group that matches. A level-up names the Pokémon by its
# nickname, which only resolves when the player kept the species name.
PATTERNS = (
    re.compile(r'^Caught (?:the legendary )?(.+?)!?$'),
    re.compile(r'^Got (.+?)!?$'),
    re.compile(r'^(.+?) joined the Pok[eé]dex$'),
    re.compile(r'^(.+?) hatched from its Egg$'),
    re.compile(r'^.+? evolved into (.+?)!?$'),
    re.compile(r'^(.+?) grew to level \d+$'),
)


def species_index(names: dict[int, str]) -> dict[str, int]:
    """Map lowercase species names to their Pokédex numbers."""
    return {str(name).strip().lower(): dex for dex, name in names.items() if name}


def annotate(row: dict, index: dict[str, int]) -> dict:
    """Add ``species_dex`` to an entry about one Pokémon when its title names the species."""
    if row.get('type') not in SPECIES_TYPES or not index:
        return row
    title = str(row.get('title') or '').strip()
    for pattern in PATTERNS:
        match = pattern.match(title)
        if match:
            dex = index.get(match.group(1).strip().lower())
            if dex:
                row['species_dex'] = dex
            break
    return row
