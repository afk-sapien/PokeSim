"""Whether the party is ready for a boss battle, one precondition for both generations (design S2).

Before a gym leader, an Elite Four member, the Champion, a rival or Red, every Pokémon should have at
least half its HP and at least half the PP of the attacks it fights with, each weighted by how hard
it hits. Those are the attacks within STRONG_SHARE of its strongest one. A party short of that heals
first when a Pokémon Center is in reach and the approach has a boss heal trip left. Otherwise it goes
in unready, and the journal says so once.

Each generation reads its party into ``Fighter`` rows with ``fighter`` and its own move table, and
asks one ``Gate`` per policy. The rule keeps no game knowledge of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

# A Pokémon under this share of its HP, or of its strong attacks' PP, is not ready for a boss.
READY_HP = 0.5
READY_PP = 0.5
# An attack is one the Pokémon fights with when it hits at least this share as hard as its strongest.
# A Typhlosion with Flamethrower and Strength spent still had 30 PP of Cut, so it never went to heal
# and met Misty and Brock with Cut alone, and lost.
STRONG_SHARE = 0.5
# A move that knocks out its user is the last choice in battle, so it counts for this share.
SELF_KO_SHARE = 0.1
STAB = 1.5
# Boss heal trips one approach may take. Each trip heals at the Center nearest the party, so the next
# walk is shorter. After the last one the party goes in unready, so a long cave between the Center
# and the boss cannot loop.
TRIPS = 3

READY, HEAL, UNREADY = 'ready', 'heal', 'unready'


@dataclass(frozen=True)
class Effects:
    """How one generation's move table names the attacks that do not hit for power times STAB.

    ``hits`` gives the hits one use lands, ``self_ko`` the effects that knock out the user, ``level``
    the effects or move names that deal the user's level, and ``fixed`` the effects or names that deal
    a set amount (0 means the move's power).
    """
    hits: Mapping[str, int] = field(default_factory=dict)
    self_ko: frozenset = frozenset()
    level: frozenset = frozenset()
    fixed: Mapping[str, int] = field(default_factory=dict)


def attack_strength(entry, types, level, effects):
    """How hard the move ``entry`` hits for a Pokémon of ``types`` and ``level``, or 0 with no power."""
    power = entry.get('power', 0)
    if not power:
        return 0
    effect, name = entry.get('effect'), entry.get('name')
    if effect in effects.level or name in effects.level:
        return level
    for key in (effect, name):
        if key in effects.fixed:
            return effects.fixed[key] or power
    stab = STAB if entry.get('type') in types else 1
    return power * stab * effects.hits.get(effect, 1) * (SELF_KO_SHARE if effect in effects.self_ko else 1)


def strong(strengths):
    """The move slots a Pokémon fights with: those within STRONG_SHARE of its strongest attack."""
    line = max(strengths, default=0) * STRONG_SHARE
    return [index for index, strength in enumerate(strengths) if strength and strength >= line]


def strong_uses(strengths, pp):
    return sum(pp[index] for index in strong(strengths) if index < len(pp))


@dataclass(frozen=True)
class Fighter:
    """One party Pokémon as the boss check sees it. Strong PP is weighted by each attack's strength."""
    hp: int
    max_hp: int
    strong_pp: float
    strong_max: float


def fighter(hp, max_hp, strengths, pp, max_pp):
    """One ``Fighter``. Each strong attack's PP counts by its strength, so a spent Flamethrower is not
    hidden by a full Strength. A Typhlosion with Flamethrower at 2 of 15 and Strength at 14 of 15 met
    Red with 16 of 30 strong PP and lost."""
    slots = [index for index in strong(strengths) if index < len(pp)]
    return Fighter(hp, max_hp, sum(strengths[index] * pp[index] for index in slots),
                   sum(strengths[index] * (max_pp[index] if index < len(max_pp) else pp[index]) for index in slots))


def short(row):
    """Whether one Pokémon is under READY_HP of its HP or READY_PP of its strong attacks' PP."""
    return row.hp < row.max_hp * READY_HP or bool(row.strong_max) and row.strong_pp < row.strong_max * READY_PP


def unready(fighters):
    """The party slots that are not ready for a boss."""
    return [index for index, row in enumerate(fighters) if short(row)]


def restored(fighters):
    return all(row.hp >= row.max_hp and row.strong_pp >= row.strong_max for row in fighters)


class Gate:
    """The boss check of one policy: TRIPS boss heal trips per approach, and one journal note per
    unready one.

    An approach is the time one boss goal stays the goal. It starts again when the goal changes, and
    when the party is restored outside a boss trip, by a blackout or an ordinary heal.
    """

    def __init__(self):
        self.key = None
        self.trips = 0
        self.healing = False
        self.noted = False
        self.was_restored = False
        self.memo = None

    def decide(self, key, fighters, reachable: Callable[[], bool], where=None):
        """READY, HEAL or UNREADY before the boss goal ``key``, or READY when ``key`` is None.

        ``reachable`` says whether a Pokémon Center is in reach, and is only asked when a trip would
        start, since it searches the map. The answer is kept while ``key``, the party and ``where``
        (the caller's map) stay the same, so a step costs one comparison.
        """
        fighters = tuple(fighters)
        memo = (key, fighters, where, self.healing, self.trips)
        if self.memo is not None and self.memo[0] == memo:
            return self.memo[1]
        if key != self.key:
            self.key, self.trips, self.healing, self.noted = key, 0, False, False
        now = restored(fighters)
        if now and not self.was_restored and not self.healing:
            self.trips = 0
            self.noted = False
        self.was_restored = now
        if key is None or not unready(fighters):
            self.healing = False
            answer = READY
        elif self.healing:
            answer = HEAL
        elif self.trips < TRIPS and reachable():
            self.trips += 1
            self.healing = True
            answer = HEAL
        else:
            answer = UNREADY
        self.memo = ((key, fighters, where, self.healing, self.trips), answer)
        return answer

    def note(self):
        """True once per unready approach, when the journal should say the party went in unready."""
        if self.noted:
            return False
        self.noted = True
        return True


def unready_event(title, fighters, names=None):
    """The journal row, a planner entry like a dropped pin, for a party that goes into ``title`` unready."""
    slots = unready(fighters)
    names = names or [f'Slot {index + 1}' for index in range(len(fighters))]
    detail = ', '.join(names[index] for index in slots)
    return {'type': 'plan', 'title': f'Went in unready: {title}',
            'body': (f'No Pokémon Center was in reach, or this approach already took its heal trips. '
                     f'Under half HP or strong PP: {detail}.'),
            'priority': 2, 'tags': 'warning'}
