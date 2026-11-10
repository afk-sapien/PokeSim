"""Generation II Battle Power on the same scale as the Generation I estimate.

The score rates known moves at full health and PP against one same-level
reference opponent of each type: 3L + 10 HP and 2L + 5 in every defense.
Moves, typing, matchups and stats come from the adventure's own cartridge data,
so the split Special stats, Steel and Dark, and Gen II move effects all count.
"""
from functools import lru_cache
from math import sqrt

from .ram import calculated_stats

UTILITY = {'EFFECT_HEAL': 0.12, 'EFFECT_MORNING_SUN': 0.12, 'EFFECT_SYNTHESIS': 0.12,
           'EFFECT_MOONLIGHT': 0.12, 'EFFECT_SLEEP': 0.08, 'EFFECT_PARALYZE': 0.06,
           'EFFECT_LEECH_SEED': 0.06}
NO_DIRECT_DAMAGE = {'EFFECT_COUNTER', 'EFFECT_MIRROR_COAT', 'EFFECT_BIDE',
                    'EFFECT_DREAM_EATER', 'EFFECT_SNORE'}
CHARGING = {'EFFECT_RAZOR_WIND', 'EFFECT_SOLARBEAM', 'EFFECT_SKY_ATTACK',
            'EFFECT_SKULL_BASH', 'EFFECT_FLY', 'EFFECT_FUTURE_SIGHT'}
HITS = {'EFFECT_MULTI_HIT': 3, 'EFFECT_DOUBLE_HIT': 2, 'EFFECT_POISON_MULTI_HIT': 2,
        'EFFECT_TRIPLE_KICK': 6}
# Average power of moves whose listed power is a placeholder.
AVERAGE_POWER = {'EFFECT_MAGNITUDE': 71, 'EFFECT_PRESENT': 52, 'EFFECT_REVERSAL': 20}
HIGH_CRITICAL = {'KARATE_CHOP', 'RAZOR_LEAF', 'CRABHAMMER', 'SLASH', 'AEROBLAST', 'CROSS_CHOP'}
HIDDEN_POWER_TYPES = ('FIGHTING', 'FLYING', 'POISON', 'GROUND', 'ROCK', 'BUG', 'GHOST', 'STEEL',
                      'FIRE', 'WATER', 'GRASS', 'ELECTRIC', 'PSYCHIC_TYPE', 'ICE', 'DRAGON', 'DARK')


def hidden_power(data, dvs):
    """Type and power from the DVs, as the cartridge's HiddenPowerDamage computes them."""
    _, attack, defense, speed, special = dvs
    kind = data.types[HIDDEN_POWER_TYPES[(attack & 3) * 4 + (defense & 3)]]
    high = (special >> 3) + 2 * (speed >> 3) + 4 * (defense >> 3) + 8 * (attack >> 3)
    return kind, (5 * high + (special & 3)) // 2 + 31


def _valid(mon, data):
    moves, dvs, training = mon.get('moves'), mon.get('dvs'), mon.get('stat_exp')
    level = mon.get('level')
    return (not mon.get('egg') and mon.get('species') in data.species
            and type(level) is int and 1 <= level <= 100
            and isinstance(moves, (list, tuple)) and 1 <= len(moves) <= 4
            and all(type(mid) is int and (mid == 0 or mid in data.moves) for mid in moves)
            and isinstance(dvs, (list, tuple)) and len(dvs) == 5
            and all(type(v) is int and 0 <= v <= 15 for v in dvs)
            and isinstance(training, (list, tuple)) and len(training) == 5
            and all(type(v) is int and 0 <= v <= 65535 for v in training))


def _damage(data, move, species, friendship, stats, dvs, level, target_type, hp, defense):
    effect = move['effect']
    if not move['power'] or effect in NO_DIRECT_DAMAGE:
        return 0.0
    kind, power = move['type'], AVERAGE_POWER.get(effect, move['power'])
    if effect == 'EFFECT_HIDDEN_POWER':
        kind, power = hidden_power(data, dvs)
    elif effect == 'EFFECT_RETURN':
        power = max(1, friendship * 10 // 25)
    elif effect == 'EFFECT_FRUSTRATION':
        power = max(1, (255 - friendship) * 10 // 25)
    factor = data.matchups.get((kind, target_type), 1)
    if not factor:
        return 0.0
    if effect == 'EFFECT_STATIC_DAMAGE':
        return float(power)
    if effect == 'EFFECT_LEVEL_DAMAGE':
        return float(level)
    if effect == 'EFFECT_PSYWAVE':
        return level * 0.75
    if effect == 'EFFECT_SUPER_FANG':
        return float(max(1, hp // 2))
    if effect == 'EFFECT_OHKO':
        return float(hp)  # The reference opponent is never above the user's level.
    physical = kind < 20
    attack = stats[1] if physical else stats[4]
    target = max(1, defense // 2 if effect == 'EFFECT_SELFDESTRUCT' else defense)
    raw = ((2 * level // 5 + 2) * power * max(1, attack) // target) // 50 + 2
    raw *= 1.5 if kind in data.species[species]['types'] else 1
    raw *= factor * 0.925
    critical = (64 if move['constant'] in HIGH_CRITICAL else 17) / 256
    return raw * (1 + critical) * HITS.get(effect, 1)


def battle_power(mon, data):
    """Gen II Battle Power, or None when the snapshot lacks what the rating needs."""
    if not _valid(mon, data):
        return None
    friendship = mon.get('friendship')
    return _power(data, mon['species'], mon['level'], tuple(mon['dvs']), tuple(mon['stat_exp']),
                  tuple(dict.fromkeys(mon['moves'])), friendship if type(friendship) is int else 0)


@lru_cache(maxsize=8192)
def _power(data, species, level, dvs, training, moves, friendship):
    stats = calculated_stats(data.species[species]['stats'], level, dvs, training)
    max_hp, _, physical_defense, speed, _, special_defense = stats
    hp, defense = 3 * level + 10, 2 * level + 5
    reference_types = sorted({kind for row in data.species.values() for kind in row['types']})
    outcomes = []
    for target_type in reference_types:
        scores = []
        for mid in moves:
            move = data.moves.get(mid)
            if not move:
                continue
            connected = _damage(data, move, species, friendship, stats, dvs, level, target_type, hp, defense)
            if not connected:
                continue
            effect = move['effect']
            value = min(hp, connected) * min(255, move['accuracy'] * 255 // 100) / 256
            if effect in CHARGING:
                value *= 0.5
            if effect == 'EFFECT_HYPER_BEAM' and connected < hp:
                value *= 0.5
            if effect == 'EFFECT_RECOIL_HIT':
                value *= 0.75
            if effect == 'EFFECT_SELFDESTRUCT':
                value *= 0.1
            scores.append(value)
        outcomes.append(max(scores, default=0) / hp * 100)
    effects = {data.moves[mid]['effect'] for mid in moves if mid in data.moves}
    utility = min(0.2, sum(UTILITY.get(effect, 0) for effect in effects))
    score = sum(outcomes) / len(outcomes) * (1 + utility)
    durability = 2 * physical_defense * special_defense / (physical_defense + special_defense)
    return int(score * sqrt(max_hp * durability) * (1 + speed / 500) / 10)
