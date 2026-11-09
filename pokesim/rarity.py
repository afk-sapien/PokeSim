"""How rare a copy's DVs are for its family, in both generations, from tables the caller supplies.

A copy is scored as the battle power of its family's fully evolved form at Lv 100 with full stat
experience, so a Gastly is scored as the Gengar it becomes. A family that branches takes the branch
its DVs suit best. The score sums the five stats. Attack counts fully when the final form's best
physical attack beats its best special one by a quarter, not at all when the special one does, and
half otherwise. The attacks are the family's level-up moves plus the TMs and HMs the bot teaches that
the form can learn. Level, stat experience and moves known are not in it, since training and moves
can be added to any copy later.

Rarity is the chance a uniformly random set of the four stored DVs, with HP derived from them,
scores at least as well. It is counted exactly over all 65536 sets and cached per family shape.
"""
from bisect import bisect_left
from functools import lru_cache

import numpy

COMBOS = 65536
# Type ids below this are physical in both generations: Normal, Fighting, Flying, Poison, Ground,
# Rock, Bird, Bug, Ghost and Gen II Steel. Fire and above are special.
PHYSICAL_BELOW = 20
# Same-type attack bonus when ranking a form's best attacks.
STAB = 1.5
# The best attack of one side must beat the other side's by this factor to decide the Attack weight.
DOMINANCE = 1.25
# Explosion and Self-Destruct faint the user, so they never count among a form's best attacks
# (Gen I and Gen II effect names).
SELF_KO = frozenset({'EXPLODE_EFFECT', 'EFFECT_SELFDESTRUCT'})
# At Lv 100 with 65535 stat experience a stat is 2 * (base + DV) + 68, and HP adds 105 more.
STAT_BONUS, HP_BONUS = 68, 105


def physical(move_type):
    return move_type < PHYSICAL_BELOW


def best_attacks(types, moves):
    """The best physical and special attack values, each power times accuracy with the same-type
    bonus, as ((P, move), (S, move)). A side the form has no attack for is (0, None)."""
    best = {True: (0, None), False: (0, None)}
    for move in moves:
        power, accuracy, kind = move[:3]
        if power > 1:
            value = power * accuracy / 100 * (STAB if kind in types else 1)
            side = physical(kind)
            if value > best[side][0]:
                best[side] = (value, move)
    return best[True], best[False]


def attack_weight(types, moves):
    """1 when the best physical attack is at least DOMINANCE times the best special one, 0 when the
    special one is at least DOMINANCE times the physical one, and 0.5 otherwise, ties included.

    ``moves`` holds (power, accuracy, type) for every damaging move in the form's pool, self-KO
    moves left out by the caller. A form with no damaging move is judged by its own types."""
    (strong, _), (special, _) = best_attacks(types, moves)
    if not strong and not special:
        strong = sum(map(physical, types))
        special = len(types) - strong
    if strong >= DOMINANCE * special:
        return 1
    return 0 if special >= DOMINANCE * strong else 0.5


def form(stats, types, moves):
    """One final form as (constant, attack weight). ``stats`` are the HP, Attack, Defense, Speed and
    Special base stats. Its score for a copy is the constant plus twice the weighted DVs."""
    weight = attack_weight(types, moves)
    weights = (1, weight, 1, 1, 1)
    constant = sum(2 * w * base + STAT_BONUS * w for w, base in zip(weights, stats)) + HP_BONUS
    return (int(round(constant)), weight)


def score(forms, dvs):
    """The family score of one copy. ``dvs`` are HP, Attack, Defense, Speed and Special, and HP is
    derived again from the other four."""
    attack, defense, speed, special = dvs[1:5]
    hp = (attack & 1) << 3 | (defense & 1) << 2 | (speed & 1) << 1 | special & 1
    rest = hp + defense + speed + special
    return max(int(constant + 2 * (rest + weight * attack)) for constant, weight in forms)


def shape(forms):
    """The forms with constants shifted to start at 0, so families of one shape share one table."""
    low = min(constant for constant, _ in forms)
    return tuple(sorted((constant - low, weight) for constant, weight in forms))


@lru_cache(maxsize=1)
def _combos():
    values = numpy.arange(COMBOS)
    attack, defense, speed, special = values >> 12 & 15, values >> 8 & 15, values >> 4 & 15, values & 15
    hp = (attack & 1) << 3 | (defense & 1) << 2 | (speed & 1) << 1 | special & 1
    return hp + defense + speed + special, attack


@lru_cache(maxsize=512)
def _sorted_scores(key):
    rest, attack = _combos()
    best = numpy.max([constant + 2 * (rest + weight * attack) for constant, weight in key], axis=0)
    return numpy.sort(best.astype(numpy.int64)).tolist()


def tail(forms, dvs):
    """The chance a random copy of the family scores at least as well as one with ``dvs``."""
    key = shape(forms)
    low = min(constant for constant, _ in forms)
    scores = _sorted_scores(key)
    return (COMBOS - bisect_left(scores, score(forms, dvs) - low)) / COMBOS


# The family shape for a copy without species data: every stat counts and every base is equal.
GENERIC = ((0, 1),)


def valid(dvs):
    return (isinstance(dvs, (list, tuple)) and len(dvs) == 5
            and all(type(value) is int and 0 <= value <= 15 for value in dvs))


def generic(dex, dvs):
    """Rarity by the plain DV total, for callers without species data."""
    return tail(GENERIC, dvs) if valid(dvs) else None


class Families:
    """Final forms per species from one game's tables.

    ``species`` maps a key to (stats, types, move ids, next keys), stats being HP, Attack, Defense,
    Speed and Special, and ``moves`` maps a move id to (power, accuracy, type). ``machines`` maps a
    key to the move ids of the TMs and HMs the bot teaches that the species can learn, which join a
    final form's pool."""

    def __init__(self, species, moves, machines=None):
        self.species, self.moves, self.machines = species, moves, machines or {}
        self.parent = {}
        for key, (_, _, _, after) in species.items():
            for child in after:
                self.parent.setdefault(child, key)
        self._forms = {}

    def path_ids(self, path):
        """The move ids in a final form's pool, level-up moves on the way and its taught TMs and HMs."""
        return sorted({move for key in path for move in self.species[key][2]} | set(self.machines.get(path[-1], ())))

    def path_moves(self, path):
        return [self.moves[move] for move in self.path_ids(path) if move in self.moves]

    def finals(self, key, path):
        after = [child for child in self.species[key][3] if child in self.species and child not in path]
        if not after:
            return [path]
        return [final for child in after for final in self.finals(child, path + [child])]

    def forms(self, key):
        """The family's final forms reachable from ``key``, each scored with the moves learned on
        the way from the family's first stage, or None for an unknown species."""
        if key not in self.species:
            return None
        if key not in self._forms:
            root, chain = key, [key]
            while root in self.parent and self.parent[root] not in chain:
                root = self.parent[root]
                chain.insert(0, root)
            rows = []
            for path in self.finals(key, chain):
                stats, types = self.species[path[-1]][:2]
                rows.append(form(stats, tuple(types), self.path_moves(path)))
            self._forms[key] = tuple(rows)
        return self._forms[key]

    def score(self, key, dvs):
        forms = self.forms(key)
        return score(forms, dvs) if forms and valid(dvs) else None

    def tail(self, key, dvs):
        forms = self.forms(key)
        return tail(forms, dvs) if forms and valid(dvs) else None

    def rarity(self, key, dvs):
        """``tail``, or the plain DV total's for a species these tables do not hold."""
        value = self.tail(key, dvs)
        return generic(key, dvs) if value is None else value
