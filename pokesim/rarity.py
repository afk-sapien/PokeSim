"""How rare a copy's DVs are for its family, in both generations, from tables the caller supplies.

A copy is scored as the battle power of its family's fully evolved form at Lv 100 with full stat
experience, so a Gastly is scored as the Gengar it becomes. A family that branches takes the branch
its DVs suit best. The score sums the five stats. Attack counts fully when the final form's best
attacks are physical, not at all when they are special and half when they are mixed. Level, stat
experience and moves known are not in it, since training and moves can be added to any copy later.

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
BEST_ATTACKS = 2
# Explosion and Self-Destruct faint the user, so they never count among a form's best attacks
# (Gen I and Gen II effect names).
SELF_KO = frozenset({'EXPLODE_EFFECT', 'EFFECT_SELFDESTRUCT'})
# At Lv 100 with 65535 stat experience a stat is 2 * (base + DV) + 68, and HP adds 105 more.
STAT_BONUS, HP_BONUS = 68, 105


def physical(move_type):
    return move_type < PHYSICAL_BELOW


def attack_weight(types, moves):
    """1 when the best attacks are physical, 0 when special and 0.5 when mixed.

    ``moves`` holds (power, accuracy, type) for every damaging move the family learns by level on the
    way to this form, self-KO moves left out by the caller. The best two count, by power and accuracy with the same-type bonus. A form that learns
    fewer than two is filled out with its own types."""
    ranked = sorted(((power * accuracy / 100 * (STAB if kind in types else 1), physical(kind))
                     for power, accuracy, kind in moves if power > 1), reverse=True)
    sides = [side for _, side in ranked[:BEST_ATTACKS]]
    sides += [physical(kind) for kind in types][:BEST_ATTACKS - len(sides)]
    share = sum(sides) / len(sides) if sides else 1
    return 1 if share == 1 else 0 if share == 0 else 0.5


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
    Speed and Special, and ``moves`` maps a move id to (power, accuracy, type)."""

    def __init__(self, species, moves):
        self.species, self.moves = species, moves
        self.parent = {}
        for key, (_, _, _, after) in species.items():
            for child in after:
                self.parent.setdefault(child, key)
        self._forms = {}

    def path_moves(self, path):
        seen = {move for key in path for move in self.species[key][2]}
        return [self.moves[move] for move in sorted(seen) if move in self.moves]

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
