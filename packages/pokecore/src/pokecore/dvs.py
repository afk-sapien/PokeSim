"""Exact DV tail counts under a uniform reference model, independent of game RNG timing."""
from functools import lru_cache
from itertools import product


def hp_dv(attack, defense, speed, special):
    """Derive HP from the low bits of the four stored DVs."""
    return ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)


@lru_cache(maxsize=1)
def _tails():
    counts = [0] * 76
    for values in product(range(16), repeat=4):
        counts[sum(values) + hp_dv(*values)] += 1
    return tuple(sum(counts[total:]) for total in range(77))


def dv_probabilities(dvs):
    """Return inclusive and strictly better DV-total tails, or None for invalid data.

    Input order is HP, Attack, Defense, Speed, Special. HP must match the
    stored DVs. Each of the 65,536 four-DV combinations has equal weight in
    this reference model. These are not measured cartridge encounter odds.
    """
    if (not isinstance(dvs, (tuple, list)) or len(dvs) != 5
            or any(type(value) is not int or not 0 <= value <= 15 for value in dvs)
            or dvs[0] != hp_dv(*dvs[1:])):
        return None
    total = sum(dvs)
    at_least, better = _tails()[total:total + 2]
    return {'total': total, 'outcomes': 65536, 'at_least': at_least, 'better': better,
            'at_least_probability': at_least / 65536,
            'better_probability': better / 65536}


def is_perfect(mon) -> bool:
    """All five DVs, including derived HP, are 15."""
    dvs = mon.get('dvs')
    return isinstance(dvs, (list, tuple)) and len(dvs) == 5 and all(
        type(value) is int and value == 15 for value in dvs)


def is_shiny(mon) -> bool:
    """Whether a mon dict's DVs would make it shiny once moved into Generation II.

    Order is HP, Attack, Defense, Speed, Special. Gen II shows a Pokémon as shiny
    when Defense, Speed and Special are 10 and Attack has bit 1 set.
    """
    dvs = mon.get('dvs', ())
    return (isinstance(dvs, (tuple, list)) and len(dvs) == 5
            and all(type(v) is int and 0 <= v <= 15 for v in dvs)
            and bool(dvs[1] & 2) and list(dvs[2:]) == [10, 10, 10])


def shiny_bytes(raw) -> bool:
    """The same shiny rule applied to the two stored DV bytes."""
    return len(raw) == 2 and raw[0] & 0x2f == 0x2a and raw[1] == 0xaa
