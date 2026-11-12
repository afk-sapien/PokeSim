"""Whether the party is ready for a boss battle, one precondition for both generations (design S2).

Before a gym leader, an Elite Four member, the Champion, a rival or Red, every Pokémon should have at
least half its HP and at least half the PP of the attacks it fights with, each weighted by how hard
it hits. Those are the attacks within STRONG_SHARE of its strongest one. A party short of that heals
first when a Pokémon Center is in reach and the leg has a boss heal trip left. Otherwise it goes in
unready, and the journal says so once per leg. A leg runs from the last Pokémon Center visited to the
boss, so trips spent in Victory Road leave the Indigo Plateau Center its own.

Each generation reads its party into ``Fighter`` rows with ``fighter`` and its own move table, and
asks one ``Gate`` per policy. The HP and PP a Pokémon needs are the readiness oracle's
(planning/readiness.py short). The rule keeps no game knowledge of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from .readiness import READY_HP, READY_PP, short_slots

# An attack is one the Pokémon fights with when it hits at least this share as hard as its strongest.
# A Typhlosion with Flamethrower and Strength spent still had 30 PP of Cut, so it never went to heal
# and met Misty and Brock with Cut alone, and lost.
STRONG_SHARE = 0.5
# A move that knocks out its user is the last choice in battle, so it counts for this share.
SELF_KO_SHARE = 0.1
STAB = 1.5
# Boss heal trips one leg may take. Each trip heals at the Center nearest the party, so the next walk
# is shorter. After the last one the party goes in unready, so a long cave between the Center and the
# boss cannot loop. A trip back to the same Center stays in its leg, and only a different Center
# starts a new one. When the budget covered the whole approach, Red spent its three trips in Victory
# Road and met Lorelei unready, though the Indigo Plateau Center is on the way.
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


def restored(fighters):
    return all(row.hp >= row.max_hp and row.strong_pp >= row.strong_max for row in fighters)


class Gate:
    """The boss check of one policy: TRIPS boss heal trips per leg, and one journal note per unready
    leg.

    A leg runs from the last Pokémon Center visited to the boss while one boss goal stays the goal.
    Stepping into a different Center starts a new leg with a fresh budget, and a trip that ends there
    is its first. A trip back to the leg's own Center stays in the leg, so a cave the party cannot
    cross still stops after TRIPS. The budget also starts again when the goal changes, and when the
    party is restored outside a boss trip, by a blackout or an ordinary heal.
    """

    def __init__(self):
        self.key = None
        self.trips = 0
        self.healing = False
        self.noted = False
        self.was_restored = False
        self.memo = None
        self.leg = None
        self.done = False

    def decide(self, key, fighters, reachable: Callable[[], bool], where=None, center=False, supply=False,
               full=False):
        """READY, HEAL or UNREADY before the boss goal ``key``, or READY when ``key`` is None.

        ``reachable`` says whether a Pokémon Center is in reach, and is only asked when a trip would
        start, since it searches the map. ``center`` says the caller's map ``where`` is a Pokémon
        Center, which starts a leg there. ``supply`` says the bag can treat a short fighter where no
        Center can be reached, as between League rooms (``treatment``). That answers HEAL too, with no
        trip taken, since each item used leaves the bag smaller. ``full`` asks for a party restored in
        full, not only one with no Pokémon under half, as before a postgame League run
        (league.check). The answer is kept while ``key``, the party, ``where``, ``supply`` and
        ``full`` stay the same, so a step costs one comparison.
        """
        fighters = tuple(fighters)
        memo = (key, fighters, where, center, supply, full, self.healing, self.trips)
        if self.memo is not None and self.memo[0] == memo:
            return self.memo[1]
        if key != self.key:
            self.key, self.trips, self.healing, self.noted = key, 0, False, False
        if center and where != self.leg:
            # A new Center starts a new leg. A boss trip that ends here counts as its first.
            self.leg, self.trips, self.noted = where, int(self.healing), False
        now = restored(fighters)
        if now and not self.was_restored and not self.healing:
            self.trips = 0
            self.noted = False
        self.was_restored = now
        if key is None or not short_slots(fighters) and (now or not full):
            if self.healing and key is not None:
                self.done = True
            self.healing = False
            answer = READY
        elif self.healing:
            answer = HEAL
        elif supply:
            answer = HEAL
        elif self.trips < TRIPS and reachable():
            self.trips += 1
            self.healing = True
            answer = HEAL
        else:
            answer = UNREADY
        self.memo = ((key, fighters, where, center, supply, full, self.healing, self.trips), answer)
        return answer

    def note(self):
        """True once per unready leg, when the journal should say the party went in unready."""
        if self.noted:
            return False
        self.noted = True
        return True

    def healed(self):
        """True once after a boss heal trip ends with the party ready, when the journal says so."""
        done, self.done = self.done, False
        return done


# The League runs its rooms back to back with no Pokémon Center between them, so the bag stands in for
# the heal trip. The kit bought at the last mart before the first room holds one restore per room and
# KIT_REVIVES Revives, and spends at most KIT_SHARE of the money past the reservations, so a loss, which
# halves the purse, still leaves enough to buy one again. A Gold run met Lance with its ace at 95 of 199
# HP and three unused Revives, after five rooms with no potion in the bag.
ROOMS = 5
KIT_REVIVES = 2
KIT_SHARE = 0.5
# A member under this share of the top level is a filler the items are not spent on. Gold took a level 7
# Metapod and a level 5 Togepi to the League beside its level 63 ace.
FIGHTER_SHARE = 0.6

REVIVE, RESTORE, ETHER, ELIXIR = 'revive', 'restore', 'ether', 'elixir'


def kit(restores, revives, spare, restore_price, revive_price):
    """The restores and Revives to buy before the League, as a pair, with ``restores`` and ``revives``
    already in the bag and ``spare`` money past the reservations. Restores come first.

    The kit in the bag counts at its price toward the KIT_SHARE, so buying it a few at a time over
    several trips stops at the same share as buying it all at once."""
    held = min(restores, ROOMS) * restore_price + min(revives, KIT_REVIVES) * revive_price
    budget = (max(0, spare) + held) * KIT_SHARE - held
    buy = max(0, min(ROOMS - restores, int(budget // restore_price))) if restore_price else 0
    budget -= buy * restore_price
    extra = max(0, min(KIT_REVIVES - revives, int(budget // revive_price))) if revive_price else 0
    return buy, extra


@dataclass(frozen=True)
class Member:
    """One party Pokémon as the League items read it: its level, HP and each move's strength and PP."""
    level: int
    hp: int
    max_hp: int
    strengths: tuple
    pp: tuple
    max_pp: tuple

    def row(self):
        return fighter(self.hp, self.max_hp, list(self.strengths), list(self.pp), list(self.max_pp))


@dataclass(frozen=True)
class Medicine:
    """An item in the bag: its kind, and the HP or PP it restores, 0 for all of it."""
    item: int
    kind: str
    amount: int = 0


def fighting(members):
    """The slots the League items are spent on: members at FIGHTER_SHARE of the top level or more."""
    top = max((member.level for member in members), default=0)
    return [index for index, member in enumerate(members) if member.level >= top * FIGHTER_SHARE]


def spent_move(member):
    """The strong move slot an Ether restores: the one missing the most PP by its strength."""
    slots = [index for index in strong(member.strengths) if index < len(member.pp) and index < len(member.max_pp)]
    best = max(slots, key=lambda index: (member.strengths[index] * (member.max_pp[index] - member.pp[index]), -index),
               default=None)
    return best if best is not None and member.pp[best] < member.max_pp[best] else None


def treatment(members, bag):
    """The next item to use between League rooms, as (slot, Medicine, move slot or None), or None.

    The bar is the boss check's own: a fighter under READY_HP of its HP or READY_PP of its strong
    attacks' PP is short, the same bar a Pokémon Center trip heals for outside the League. A fainted
    fighter is revived first. A short one takes the smallest restore that lifts it past the bar, or the
    largest when none does, and an Elixir or an Ether for its spent strong moves.
    """
    def by_kind(*kinds):
        return [medicine for medicine in bag if medicine.kind in kinds]
    slots = fighting(members)
    revives = sorted(by_kind(REVIVE), key=lambda medicine: (medicine.amount == 0, medicine.amount))
    for slot in slots:
        if members[slot].hp == 0 and revives:
            return slot, revives[0], None
    for slot in slots:
        member = members[slot]
        row = member.row()
        if member.hp == 0:
            continue
        bar = member.max_hp * READY_HP
        if member.hp < bar:
            restores = sorted(by_kind(RESTORE), key=lambda medicine: (medicine.amount == 0, medicine.amount))
            lifting = [medicine for medicine in restores if member.hp + (medicine.amount or member.max_hp) >= bar]
            if lifting or restores:
                return slot, (lifting or restores)[-1 if not lifting else 0], None
        if row.strong_max and row.strong_pp < row.strong_max * READY_PP:
            move = spent_move(member)
            spent = sum(1 for index in strong(member.strengths)
                        if index < len(member.pp) and index < len(member.max_pp)
                        and member.pp[index] < member.max_pp[index] * READY_PP)
            elixirs, ethers = by_kind(ELIXIR), by_kind(ETHER) if move is not None else []
            choice = (elixirs if spent > 1 else ethers) or elixirs or ethers
            if choice:
                medicine = min(choice, key=lambda medicine: (medicine.amount == 0, medicine.amount))
                return slot, medicine, move if medicine.kind == ETHER else None
    return None


def boss_name(title):
    """The boss a goal title names, without its leading verb: Lorelei for "Challenge Lorelei"."""
    for verb in ('Challenge ', 'Battle '):
        if title.startswith(verb):
            return title[len(verb):]
    return title


def healed_event(title, full=False):
    """The journal row, low and kept off the feed, for a boss heal trip that left the party ready.
    ``full`` is a heal in full before a postgame League run (Gate.decide)."""
    return {'type': 'plan', 'title': f'Healed before {boss_name(title)}',
            'body': ('Nothing restores PP inside the League, so the party healed in full at a Pokémon Center first.'
                     if full else 'The party was under half HP or strong PP, so it healed at a Pokémon Center first.'),
            'priority': 1, 'notable': False, 'tags': 'hospital'}


def pp_heal_event(place):
    """The journal row, low and kept off the feed, for a heal its strong attacks' spent PP called for."""
    return {'type': 'plan', 'title': f'PP heal at {place}',
            'body': 'Strong attacks ran low on PP, so the party restored them at the nurse.',
            'priority': 1, 'notable': False, 'tags': 'hospital'}


def unready_event(title, fighters, names=None):
    """The journal row, a planner entry like a dropped pin, for a party that goes into ``title`` unready."""
    slots = short_slots(fighters)
    names = names or [f'Slot {index + 1}' for index in range(len(fighters))]
    detail = ', '.join(names[index] for index in slots)
    # A party held to a heal in full before a League run (Gate.decide) can be unready with none under half.
    lack = f'Under half HP or strong PP: {detail}.' if slots else 'Not restored in full before the League.'
    return {'type': 'plan', 'title': f'Went in unready: {title}',
            'body': (f'No Pokémon Center was in reach, or this leg already took its heal trips, '
                     f'and the bag held nothing to treat it. {lack}'),
            'priority': 2, 'tags': 'warning'}
