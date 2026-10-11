"""Individual Pokémon keys for trading, the same in Red, Blue, Yellow, Gold, Silver and Crystal.

Neither generation stores a unique ID per Pokémon, so a key is built from what the cartridge
does keep: the original trainer ID, the DVs and the evolution family. The family is what lets
a key survive evolution while still telling apart two different species that happen to share a
trainer and DVs, which emulator reloads and Gold, Silver and Crystal breeding both produce.

A family is every species linked by evolution in either generation, and its root is the lowest
Pokédex number in it. The lowest number is a Kanto species for every family that has one, so a
Pokémon keeps its key through the Time Capsule: Pichu, Pikachu and Raichu are all family 25, and
Tyrogue joins Hitmonlee, Hitmonchan and Hitmontop as family 106, since it can become any of them.

This module has no game data and no heavy imports, so the cable workers can use it on raw bytes.
"""
from pokesim_core.identity import pokemon_identity

# Red, Blue and Yellow species index order (1 to 190) as Pokédex numbers; 0 marks an unused index.
_GEN1_ORDER = (
    112, 115, 32, 35, 21, 100, 34, 80, 2, 103, 108, 102, 88, 94, 29, 31, 104, 111, 131, 59,
    151, 130, 90, 72, 92, 123, 120, 9, 127, 114, 0, 0, 58, 95, 22, 16, 79, 64, 75, 113,
    67, 122, 106, 107, 24, 47, 54, 96, 76, 0, 126, 0, 125, 82, 109, 0, 56, 86, 50, 128,
    0, 0, 0, 83, 48, 149, 0, 0, 0, 84, 60, 124, 146, 144, 145, 132, 52, 98, 0, 0,
    0, 37, 38, 25, 26, 0, 0, 147, 148, 140, 141, 116, 117, 0, 0, 27, 28, 138, 139, 39,
    40, 133, 136, 135, 134, 66, 41, 23, 46, 61, 62, 13, 14, 15, 0, 85, 57, 51, 49, 87,
    0, 0, 10, 11, 12, 68, 0, 55, 97, 42, 150, 143, 129, 0, 0, 89, 0, 99, 91, 0,
    101, 36, 110, 53, 105, 0, 93, 63, 65, 17, 18, 121, 1, 3, 73, 0, 118, 119, 0, 0,
    0, 0, 77, 78, 19, 20, 33, 30, 74, 137, 142, 0, 81, 0, 0, 4, 7, 5, 8, 6,
    0, 0, 0, 0, 43, 44, 45, 69, 70, 71,
)
GEN1_DEX = {index: dex for index, dex in enumerate(_GEN1_ORDER, 1) if dex}

# Every evolution family of two or more species across both generations, by Pokédex number.
_FAMILIES = (
    (1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12), (13, 14, 15), (16, 17, 18), (19, 20),
    (21, 22), (23, 24), (25, 26, 172), (27, 28), (29, 30, 31), (32, 33, 34), (35, 36, 173),
    (37, 38), (39, 40, 174), (41, 42, 169), (43, 44, 45, 182), (46, 47), (48, 49), (50, 51),
    (52, 53), (54, 55), (56, 57), (58, 59), (60, 61, 62, 186), (63, 64, 65), (66, 67, 68),
    (69, 70, 71), (72, 73), (74, 75, 76), (77, 78), (79, 80, 199), (81, 82), (84, 85),
    (86, 87), (88, 89), (90, 91), (92, 93, 94), (95, 208), (96, 97), (98, 99), (100, 101),
    (102, 103), (104, 105), (106, 107, 236, 237), (109, 110), (111, 112), (113, 242),
    (116, 117, 230), (118, 119), (120, 121), (123, 212), (124, 238), (125, 239), (126, 240),
    (129, 130), (133, 134, 135, 136, 196, 197), (137, 233), (138, 139), (140, 141),
    (147, 148, 149), (152, 153, 154), (155, 156, 157), (158, 159, 160), (161, 162), (163, 164),
    (165, 166), (167, 168), (170, 171), (175, 176), (177, 178), (179, 180, 181), (183, 184),
    (187, 188, 189), (191, 192), (194, 195), (204, 205), (209, 210), (216, 217), (218, 219),
    (220, 221), (223, 224), (228, 229), (231, 232), (246, 247, 248),
)
ROOT = {dex: min(family) for family in _FAMILIES for dex in family}


def family(dex):
    """The lowest Pokédex number in a species' evolution family, the same in both generations."""
    return ROOT.get(dex, dex)


def dex_of(mon):
    """A Pokémon record's Pokédex number. Gold, Silver and Crystal records carry ``dex``; a Red,
    Blue or Yellow record without it has the cartridge's species index in ``species``."""
    dex = mon.get('dex')
    if dex:
        return dex
    species = mon.get('species')
    return GEN1_DEX.get(species) if isinstance(species, int) else None


def key(trainer, dvs, dex):
    """The trade key: the older trainer and DV signature, then the family root after a hyphen."""
    signature = pokemon_identity(trainer, dvs)
    if signature is None or not dex:
        return None
    return f'{signature}-{family(dex)}'


def legacy(value):
    """The trainer and DV signature a key starts with. Older releases used it as the whole key."""
    return value.split('-', 1)[0] if isinstance(value, str) else None


def is_legacy(value):
    return isinstance(value, str) and '-' not in value


def same(current, wanted):
    """Whether a Pokémon's current key answers to a stored key.

    A key stored by an older release has no family part and answers to every Pokémon with the
    same trainer and DVs. Callers still insist on exactly one match, so an old key that now fits
    two different species is refused rather than guessed.
    """
    if not current or not wanted:
        return False
    if current == wanted:
        return True
    return (is_legacy(wanted) and legacy(current) == wanted) or (is_legacy(current) and legacy(wanted) == current)


def find(rows, wanted, field='trade_key'):
    """The one row whose ``field`` answers to ``wanted``, or None when none or several do."""
    exact = [row for row in rows if row.get(field) and row.get(field) == wanted]
    if exact:
        return exact[0] if len(exact) == 1 else None
    matches = [row for row in rows if same(row.get(field), wanted)]
    return matches[0] if len(matches) == 1 else None
