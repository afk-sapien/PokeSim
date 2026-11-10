"""Generation I stat formulas and PokeSim's battle power estimate, without bundled tables.

The caller supplies the game tables, which Core does not ship:

* ``species``: internal species ID to a dict with ``stats`` (base HP, Attack,
  Defense, Speed, Special) and ``types``.
* ``moves``: move ID to a dict with ``name``, ``power``, ``type``, ``accuracy``
  (percent) and ``effect`` (the pokered effect constant).
* ``matchups``: ``(move type, defender type)`` to a damage factor. Missing pairs
  are neutral.

Given the same tables, every function returns exactly what PokeSim's
``pokemon.stored_strength``, ``policies.battle.damage`` and ``battle_power``
module return. Scores are estimates for sorting a collection, not a simulator.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isqrt, sqrt

STAT_NAMES = ('HP', 'Attack', 'Defense', 'Speed', 'Special')
UTILITY = {'HEAL_EFFECT': 0.12, 'SLEEP_EFFECT': 0.08,
           'PARALYZE_EFFECT': 0.06, 'LEECH_SEED_EFFECT': 0.06}
HIGH_CRITICAL = ('RAZOR_LEAF', 'SLASH', 'CRABHAMMER', 'KARATE_CHOP')
# Types 20 and up are special in Generation I.
SPECIAL_TYPES_START = 20


@dataclass(frozen=True)
class Battler:
    """The battle facts the estimates read. PokeSim's ``PartyMon`` has the same fields."""

    species: int
    hp: int
    max_hp: int
    level: int
    nick: str = ''
    status: int = 0
    types: tuple[int, ...] = ()
    moves: tuple[int, ...] = ()
    pp: tuple[int, ...] = ()
    attack: int = 1
    defense: int = 1
    speed: int = 1
    special: int = 1


def stat_exp_bonus(stat_exp: int) -> int:
    """CalcStat rounds the square root of stat experience up, caps it at 255 and divides by four."""
    root = isqrt(stat_exp)
    return min(255, root + (root * root < stat_exp)) // 4


def calculated_stat(base: int, level: int, dv: int, stat_exp: int, *, hp: bool = False) -> int:
    """One stat as the cartridge computes it on withdrawal, capped at 999."""
    value = ((base + dv) * 2 + stat_exp_bonus(stat_exp)) * level // 100
    return min(999, value + (level + 10 if hp else 5))


def _valid(mon, species):
    level, dvs, training = mon.get('level'), mon.get('dvs'), mon.get('stat_exp')
    return (bool(species) and type(level) is int and 1 <= level <= 100
            and isinstance(dvs, (list, tuple)) and len(dvs) == 5
            and isinstance(training, (list, tuple)) and len(training) == 5
            and not any(type(v) is not int or not 0 <= v <= 15 for v in dvs)
            and not any(type(v) is not int or not 0 <= v <= 65535 for v in training))


def calculated_stats(mon, species: dict) -> dict | None:
    """Stats by name for a mon dict with ``species``, ``level``, ``dvs`` and ``stat_exp``, or None."""
    data = species.get(mon.get('species'))
    if not _valid(mon, data):
        return None
    return {label: calculated_stat(base, mon['level'], dv, exp, hp=index == 0)
            for index, (label, base, dv, exp) in enumerate(zip(STAT_NAMES, data['stats'], mon['dvs'],
                                                                mon['stat_exp']))}


def stored_strength(mon, species: dict) -> dict:
    """PokeSim's ``stored_strength``: calculated stats, their total and a power figure.

    Power weights the better offense, balanced durability and speed. Records
    without individual data give None for every field.
    """
    stats = calculated_stats(mon, species)
    if stats is None:
        return {'calculated_stats': None, 'stat_total': None, 'power': None}
    hp, attack, defense, speed, special = (stats[name] for name in STAT_NAMES)
    offense = (3 * max(attack, special) + min(attack, special)) / 4
    durability = 2 * defense * special / (defense + special)
    power = int(offense * sqrt(hp * durability) * (1 + speed / 500) / 50)
    return {'calculated_stats': stats, 'stat_total': sum(stats.values()), 'power': power}


def dv_rating(mon) -> dict:
    """Rate fixed potential using all five DVs, including derived HP, out of 75."""
    dvs = mon.get('dvs')
    if (not isinstance(dvs, (list, tuple)) or len(dvs) != 5
            or any(type(value) is not int or not 0 <= value <= 15 for value in dvs)):
        return {'dv_stars': None, 'dv_total': None, 'dv_percent': None}
    total = sum(dvs)
    stars = 4 if total == 75 else 3 if total >= 60 else 2 if total >= 38 else 1
    return {'dv_stars': stars, 'dv_total': total, 'dv_percent': round(total * 100 / 75, 1)}


class BattlePower:
    """Estimates bound to one set of game tables. Results are cached per instance."""

    def __init__(self, species: dict, moves: dict, matchups: dict):
        self.species, self.moves, self.matchups = species, moves, matchups
        self.reference_types = tuple(sorted({typ for data in species.values() for typ in data['types']}))
        self._moveset_score = lru_cache(maxsize=16384)(self._moveset_score_uncached)
        self._power = lru_cache(maxsize=8192)(self._power_uncached)

    def effectiveness(self, move_type, defender_types) -> float:
        factor = 1.0
        for typ in set(defender_types):
            factor *= self.matchups.get((move_type, typ), 1.0)
        return factor

    def damage(self, move_id, attacker, defender) -> float:
        """Expected connected-hit damage before accuracy, including common special moves."""
        move = self.moves.get(move_id)
        if not move or not move['power']:
            return 0.0
        name, effect = move['name'], move['effect']
        if name in ('SEISMIC_TOSS', 'NIGHT_SHADE'):
            return float(attacker.level)
        factor = self.effectiveness(move['type'], defender.types)
        if not factor:
            return 0.0
        if name in ('SONICBOOM', 'DRAGON_RAGE'):
            return 20.0 if name == 'SONICBOOM' else 40.0
        if name == 'SUPER_FANG':
            return float(max(1, defender.hp // 2))
        if name == 'PSYWAVE':
            return max(1.0, attacker.level * 0.75)
        if effect == 'OHKO_EFFECT':
            return float(defender.hp) if attacker.speed >= defender.speed else 0.0
        if effect in ('COUNTER_EFFECT', 'BIDE_EFFECT'):
            return 0.0
        physical = move['type'] < SPECIAL_TYPES_START
        attack = attacker.attack if physical else attacker.special
        defense = defender.defense if physical else defender.special
        if effect == 'EXPLODE_EFFECT':
            defense = max(1, defense // 2)
        raw = ((2 * attacker.level // 5 + 2) * move['power'] * max(1, attack) // max(1, defense)) // 50 + 2
        raw *= 1.5 if move['type'] in attacker.types else 1
        raw *= factor * 0.925
        # Generation I uses species base Speed and gives these moves a much higher critical rate.
        base_speed = self.species.get(attacker.species, {}).get('stats', [0, 0, 0, attacker.speed])[3]
        threshold = base_speed // 2
        if name in HIGH_CRITICAL:
            threshold *= 8
        critical_chance = min(255, threshold) / 256
        critical_multiplier = (4 * attacker.level // 5 + 2) / max(1, 2 * attacker.level // 5 + 2)
        raw *= 1 + critical_chance * (critical_multiplier - 1)
        if effect in ('ATTACK_TWICE_EFFECT', 'TWINEEDLE_EFFECT'):
            raw *= 2
        elif effect == 'TWO_TO_FIVE_ATTACKS_EFFECT':
            raw *= 3
        return raw

    def moveset_score(self, mon, moves=None) -> float:
        """Expected damage per turn across equal single-type reference opponents.

        References have 3L + 10 HP and 2L + 5 defenses. Score is percent HP per
        turn, with at most 20 percent extra credit for distinct utility effects.
        """
        moves = tuple(dict.fromkeys(mon.moves if moves is None else moves))
        return self._moveset_score(mon.species, mon.level, tuple(mon.types), mon.attack,
                                   mon.defense, mon.speed, mon.special, mon.max_hp, moves)

    def _moveset_score_uncached(self, species, level, types, attack, physical_defense, speed, special,
                                max_hp, moves):
        mon = Battler(species, max_hp, max_hp, level, types=types, moves=moves,
                      attack=attack, defense=physical_defense, speed=speed, special=special)
        hp, defense = 3 * level + 10, 2 * level + 5
        outcomes = []
        for typ in self.reference_types:
            enemy = Battler(0, hp, hp, level, types=(typ, typ), defense=defense, special=defense, speed=defense)
            scores = []
            for mid in moves:
                move = self.moves.get(mid, {})
                effect = move.get('effect')
                if not move.get('power') or effect in ('OHKO_EFFECT', 'COUNTER_EFFECT', 'BIDE_EFFECT'):
                    continue
                connected = self.damage(mid, mon, enemy)
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
        effects = {self.moves.get(mid, {}).get('effect') for mid in moves}
        utility = min(0.2, sum(UTILITY.get(effect, 0) for effect in effects))
        return sum(outcomes) / len(outcomes) * (1 + utility)

    def stored_strength(self, mon) -> dict:
        return stored_strength(mon, self.species)

    def battler(self, mon) -> Battler | None:
        """A full-health battler built from a mon dict's calculated stats."""
        stats = calculated_stats(mon, self.species)
        if stats is None:
            return None
        return Battler(mon['species'], stats['HP'], stats['HP'], mon['level'],
                       types=tuple(self.species[mon['species']]['types']), moves=tuple(mon.get('moves', ())),
                       attack=stats['Attack'], defense=stats['Defense'],
                       speed=stats['Speed'], special=stats['Special'])

    def battle_power(self, mon) -> int | None:
        """One number for a stored mon dict, or None when its moves or individual data are unusable."""
        moves = mon.get('moves')
        if (not isinstance(moves, (list, tuple)) or not 1 <= len(moves) <= 4
                or any(type(mid) is not int or mid != 0 and mid not in self.moves for mid in moves)
                or calculated_stats(mon, self.species) is None):
            return None
        return self._power(mon['species'], mon['level'], tuple(mon['dvs']), tuple(mon['stat_exp']), tuple(moves))

    def _power_uncached(self, species, level, dvs, training, moves):
        mon = self.battler({'species': species, 'level': level, 'dvs': dvs, 'stat_exp': training, 'moves': moves})
        durability = 2 * mon.defense * mon.special / (mon.defense + mon.special)
        return int(self.moveset_score(mon) * sqrt(mon.max_hp * durability) * (1 + mon.speed / 500) / 10)

    def best_replacement(self, mon, new_move, protected=()) -> int | None:
        """The move slot ``new_move`` should replace for a meaningful gain, keeping protected moves."""
        if new_move not in self.moves or new_move in mon.moves:
            return None
        slots = [i for i, mid in enumerate(mon.moves) if mid not in protected]
        if not slots:
            return None
        score = self.moveset_score(mon)

        def improved(slot):
            return self.moveset_score(mon, tuple(new_move if i == slot else mid for i, mid in enumerate(mon.moves)))
        # Prefer an empty slot or a weaker old move on equal outcomes.
        slot = max(slots, key=lambda i: (improved(i), mon.moves[i] == 0, -self.moveset_score(mon, (mon.moves[i],))))
        return slot if improved(slot) > score * 1.03 + 0.1 else None
