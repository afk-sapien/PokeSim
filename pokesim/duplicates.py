"""Conservative duplicate retention shared by the player and trade broker."""
from collections import defaultdict
from math import isqrt

from .strategy_data import MOVES, SPECIES


def quality(mon):
    """Prefer practical investment before natural potential, within one species.

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
    return (mon['level'], sum(isqrt(value) for value in mon.get('stat_exp', ())),
            sum(coverage.values()) + utility, mon.get('experience', 0),
            sum(mon.get('dvs', ())))


def spare_entries(party, stored, protected=()):
    """Keep the best individual per species, with party members winning exact ties.

    Party members are never offered. A better boxed copy survives alongside them.
    Older payloads without individual data retain the original level-only rule.
    """
    groups = defaultdict(list)
    for mon in [*party, *stored]:
        groups[mon['species']].append(mon)
    keepers = {}
    for species, copies in groups.items():
        detailed = all(len(mon.get('dvs', ())) == 5 and
                       len(mon.get('stat_exp', ())) == 5 and 'moves' in mon
                       for mon in copies)
        if detailed:
            keepers[species] = max(copies, key=quality)
        else:
            keepers[species] = next((mon for mon in party if mon['species'] == species),
                                    max(copies, key=lambda mon: mon['level']))
    return [mon for mon in stored if mon['species'] not in protected
            and mon is not keepers[mon['species']]]
