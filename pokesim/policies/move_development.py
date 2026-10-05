"""Prepare useful moves before stone evolution and use spare HM capacity."""
from dataclasses import asdict
from functools import lru_cache

from ..battle_power import battler, best_replacement, moveset_score
from ..strategy_data import ITEMS, MOVES, SPECIES
from .battle import HM_MOVES


def evolution_wait(mon, evolution):
    """Return the next valuable level move unavailable after a stone evolution."""
    if evolution['method'] != 'item':
        return None
    return _evolution_wait(mon['species'], mon['level'], tuple(mon['moves']), evolution['species'])


@lru_cache(maxsize=4096)
def _evolution_wait(species, current_level, moves, child_species):
    child = SPECIES[child_species]
    # Compare moves using the evolved species at a common mature level.
    future = battler({'species': child_species, 'level': 100, 'dvs': [15] * 5,
                      'stat_exp': [65535] * 5, 'moves': moves})
    for level, mid in SPECIES[species].get('learnset', ()):
        if level <= current_level or mid in moves:
            continue
        if any(move == mid and child_level > current_level for child_level, move in child.get('learnset', ())):
            continue
        slot = best_replacement(future, mid, HM_MOVES)
        if slot is not None:
            return level, mid
    return None


def hm_upgrade(snapshot):
    """Improve an empty slot with a reusable battle HM, without spending TMs."""
    candidates = []
    bag = dict(snapshot.items)
    for index, mon in enumerate(snapshot.party):
        if 0 not in mon.moves or mon.hp <= 0 or mon.status:
            continue
        stable = battler(asdict(mon))
        if stable is None:
            continue
        baseline = moveset_score(stable)
        for item, mid in (('HM03', 57), ('HM04', 70)):
            if (not bag.get(ITEMS[item]) or mid in mon.moves
                    or mid not in SPECIES.get(mon.species, {}).get('hms', ())):
                continue
            moves = list(mon.moves)
            moves[moves.index(0)] = mid
            gain = moveset_score(stable, moves) - baseline
            if gain > max(2, baseline * 0.15):
                candidates.append((gain, index, ITEMS[item], mid))
    return max(candidates, default=None)


def move_name(mid):
    return MOVES[mid]['name'].replace('_', ' ').title()
