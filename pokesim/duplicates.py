"""Quality ranks within one species, which training, trading and checkpoint trims compare by."""
from math import isqrt

from .strategy_data import MOVES, SPECIES
from .investment import potential_power


def dv_quality(mon):
    """Rank known natural stats before any trainable investment."""
    dvs = mon.get('dvs', ())
    if len(dvs) != 5 or any(type(value) is not int or not 0 <= value <= 15 for value in dvs):
        return (-1, -1)
    return (sum(dvs), min(dvs))


def quality(mon):
    """Prefer natural potential, then practical investment, within one species.

    Current HP and PP are deliberately absent because healing restores them.
    Move coverage and useful status moves matter more than raw move count.
    """
    types = SPECIES.get(mon['species'], {}).get('types', ())
    coverage = {}
    utility = 0
    for mid in set(mon.get('moves', ())) - {0}:
        move = MOVES.get(mid, {})
        power = move.get('power', 0)
        if power:
            value = power * move.get('accuracy', 100) / 100
            value *= 1.5 if move.get('type') in types else 1
            coverage[move.get('type')] = max(coverage.get(move.get('type'), 0), value)
        else:
            utility += 40 if move.get('effect') in (
                'SLEEP_EFFECT', 'HEAL_EFFECT', 'LEECH_SEED_EFFECT', 'PARALYZE_EFFECT') else 8
    return (potential_power(mon) or -1, *dv_quality(mon), mon['level'], sum(isqrt(value) for value in mon.get('stat_exp', ())),
            sum(coverage.values()) + utility, mon.get('experience', 0),
            sum(mon.get('dvs', ())))
