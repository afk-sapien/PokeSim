"""Stable moveset estimates for collection browsing and move development."""
from functools import lru_cache
from math import sqrt

from .pokemon import stored_strength
from .ram import PartyMon
from .strategy_data import MOVES, SPECIES

REFERENCE_TYPES = tuple(sorted({typ for data in SPECIES.values() for typ in data['types']}))
UTILITY = {'HEAL_EFFECT': 0.12, 'SLEEP_EFFECT': 0.08,
           'PARALYZE_EFFECT': 0.06, 'LEECH_SEED_EFFECT': 0.06}


def moveset_score(mon, moves=None):
    """Expected damage per turn across equal single-type reference opponents.

    References have 3L + 10 HP and 2L + 5 defenses. Score is percent HP per
    turn, with at most 20 percent extra credit for distinct utility effects.
    Full health and restored PP make this independent of temporary condition.
    """
    moves = tuple(dict.fromkeys(mon.moves if moves is None else moves))
    return _moveset_score(mon.species, mon.level, tuple(mon.types), mon.attack,
                          mon.defense, mon.speed, mon.special, mon.max_hp, moves)


@lru_cache(maxsize=16384)
def _moveset_score(species, level, types, attack, physical_defense, speed, special, max_hp, moves):
    from .policies.battle import damage
    mon = PartyMon(species, max_hp, max_hp, level, '', types=types, moves=moves,
                   attack=attack, defense=physical_defense, speed=speed, special=special)
    hp, defense = 3 * mon.level + 10, 2 * mon.level + 5
    outcomes = []
    for typ in REFERENCE_TYPES:
        enemy = PartyMon(0, hp, hp, mon.level, '', types=(typ, typ),
                         defense=defense, special=defense, speed=defense)
        scores = []
        for mid in moves:
            move = MOVES.get(mid, {})
            effect = move.get('effect')
            if not move.get('power') or effect in ('OHKO_EFFECT', 'COUNTER_EFFECT', 'BIDE_EFFECT'):
                continue
            connected = damage(mid, mon, enemy)
            value = min(hp, connected) * min(255, move['accuracy'] * 255 // 100) / 256
            if effect in ('CHARGE_EFFECT', 'FLY_EFFECT', 'CHARGE_ATTACK_EFFECT') or move['name'] == 'DIG':
                value *= 0.5
            if effect == 'RECHARGE_EFFECT' and connected < hp:
                value *= 0.5
            if effect == 'RECOIL_EFFECT':
                value *= 0.75
            if effect == 'EXPLODE_EFFECT':
                value *= 0.1
            scores.append(value)
        outcomes.append(max(scores, default=0) / hp * 100)
    effects = {MOVES.get(mid, {}).get('effect') for mid in moves}
    utility = min(0.2, sum(UTILITY.get(effect, 0) for effect in effects))
    return sum(outcomes) / len(outcomes) * (1 + utility)


def battler(mon):
    stats = stored_strength(mon)['calculated_stats']
    if stats is None:
        return None
    return PartyMon(mon['species'], stats['HP'], stats['HP'], mon['level'], '',
                    types=tuple(SPECIES[mon['species']]['types']), moves=tuple(mon.get('moves', ())),
                    attack=stats['Attack'], defense=stats['Defense'],
                    speed=stats['Speed'], special=stats['Special'])


def battle_power(mon):
    moves = mon.get('moves')
    if (not isinstance(moves, (list, tuple)) or not 1 <= len(moves) <= 4
            or any(type(mid) is not int or mid != 0 and mid not in MOVES for mid in moves)
            or stored_strength(mon)['power'] is None):
        return None
    return _power(mon['species'], mon['level'], tuple(mon['dvs']), tuple(mon['stat_exp']), tuple(moves))


@lru_cache(maxsize=8192)
def _power(species, level, dvs, training, moves):
    mon = battler({'species': species, 'level': level, 'dvs': dvs, 'stat_exp': training, 'moves': moves})
    durability = 2 * mon.defense * mon.special / (mon.defense + mon.special)
    return int(moveset_score(mon) * sqrt(mon.max_hp * durability) * (1 + mon.speed / 500) / 10)


def best_replacement(mon, new_move, protected=()):
    """Find a meaningful improvement while retaining protected field moves."""
    if new_move not in MOVES or new_move in mon.moves:
        return None
    slots = [i for i, mid in enumerate(mon.moves) if mid not in protected]
    if not slots:
        return None
    score = moveset_score(mon)
    def improved(slot):
        return moveset_score(mon, tuple(new_move if i == slot else mid for i, mid in enumerate(mon.moves)))
    # Prefer an empty slot or a weaker old move on equal outcomes.
    slot = max(slots, key=lambda i: (improved(i), mon.moves[i] == 0, -moveset_score(mon, (mon.moves[i],))))
    return slot if improved(slot) > score * 1.03 + 0.1 else None
