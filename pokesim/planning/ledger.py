"""One resource ledger for bag pockets, box and party slots and money, for both generations.

A goal says what it needs with a ``Need``. The ledger reads what is free from a snapshot through a
generation adapter, holds one reservation per goal, and answers a shortfall with the units worth least
that would cover it. A unit is something that can be given up to free room: a bag entry put in the PC,
sold or tossed, a boxed Pokémon released, or a held item taken off first. Each unit has a value from
the goals that want it, so a ball is worth more while a legendary goal runs. A unit a reservation keeps
is never offered.

The ledger keeps no game knowledge. Each generation's adapter turns a snapshot into ``Resources`` and
turns the units ``make_room`` picks into menu tasks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType

log = logging.getLogger('pokesim.ledger')

MONEY = 'money'
BOX = 'box'
PARTY = 'party'
# A unit worth this much is never given up, whatever the shortfall.
PRICELESS = float('inf')
# Move slots the ledger keeps in Gold, Silver and Crystal: Cut, Fly, Surf, Strength, Flash, Whirlpool and
# Waterfall. No machine, level-up move or Move Deleter visit replaces one of these.
FIELD_MOVES = frozenset({15, 19, 57, 70, 148, 250, 127})
# A level-up move also leaves Headbutt and Rock Smash, which shake trees and break rocks.
LEARN_KEPT = FIELD_MOVES | {29, 249}


def _frozen(mapping):
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True)
class Need:
    """What a goal needs before it starts. ``keep`` names units the goal relies on."""
    pocket_slots: dict = field(default_factory=dict)  # "balls": 1
    box_slots: int = 0
    party_slots: int = 0
    money: int = 0
    move_slot: str | None = None   # a move such as "SURF" that no plan may overwrite
    keep: frozenset = frozenset()

    def amounts(self):
        """The need as one table of kinds: pocket names, ``box``, ``party`` and ``money``."""
        table = {pocket: count for pocket, count in self.pocket_slots.items() if count > 0}
        for kind, count in ((BOX, self.box_slots), (PARTY, self.party_slots), (MONEY, self.money)):
            if count > 0:
                table[kind] = count
        return table


@dataclass(frozen=True)
class Unit:
    """Something that can be given up for room.

    ``frees`` is the kind it frees and ``amount`` how much: one slot, or the money a sale brings.
    ``action`` says how (deposit, sell, toss, release, unequip), ``needs`` what the action itself
    takes first, such as a bag entry for the item a release takes off, and ``detail`` is the
    adapter's own handle on it.
    """
    key: object
    frees: str
    value: float
    action: str
    amount: int = 1
    needs: Need = field(default_factory=Need)
    detail: object = field(default=None, compare=False)
    # Breaks ties between units of equal value, lowest first.
    order: tuple = ()


@dataclass(frozen=True)
class Resources:
    """Free room per kind and the units that could be given up for more."""
    free: dict
    money: int = 0
    units: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, 'free', _frozen(self.free))

    def available(self, kind):
        return self.money if kind == MONEY else self.free.get(kind, 0)


@dataclass(frozen=True)
class Reservation:
    goal: str
    need: Need
    ok = True


@dataclass(frozen=True)
class Shortfall:
    goal: str
    missing: dict
    ok = False

    def __post_init__(self):
        object.__setattr__(self, 'missing', _frozen(self.missing))


class Ledger:
    """Reservations against one generation's resources.

    ``read`` turns a snapshot into ``Resources``. Reservations last until ``release`` and are kept for
    the session only, since every goal reserves again when it starts.
    """

    def __init__(self, read):
        self.read = read
        self.reservations = {}
        self.resources = None

    def snapshot(self, snapshot, kinds=None):
        """Read the resources from ``snapshot`` and keep them for ``reserve`` and ``make_room``.

        ``kinds`` limits the units read to the kinds a caller is about to ask for, since ranking every
        boxed Pokémon costs more than reading the bag.
        """
        self.resources = self.read(snapshot, kinds)
        return self.resources

    def kept(self, goal=None):
        """Units some reservation other than ``goal``'s relies on."""
        return frozenset().union(*(need.keep for name, need in self.reservations.items() if name != goal))

    def held(self, kind, goal=None):
        """How much of ``kind`` the other goals hold."""
        return sum(need.amounts().get(kind, 0) for name, need in self.reservations.items() if name != goal)

    def available(self, kind, goal=None, resources=None):
        resources = resources or self.resources
        return resources.available(kind) - self.held(kind, goal)

    def reserve(self, goal, need, resources=None):
        """Hold ``need`` for ``goal``, or say what is missing. A goal reserving again replaces its old need."""
        resources = resources or self.resources
        missing = {}
        for kind, count in need.amounts().items():
            have = self.available(kind, goal, resources)
            if count > have:
                missing[kind] = count - max(have, 0)
        if missing:
            return Shortfall(goal, missing)
        self.reservations[goal] = need
        return Reservation(goal, need)

    def release(self, goal):
        self.reservations.pop(goal, None)

    def make_room(self, shortfall, resources=None, keep=frozenset()):
        """Units to give up, worth least first, that cover ``shortfall``, or [] when nothing covers it.

        A unit whose action needs room of its own, such as a held item taken off before a release, is
        chosen only when that room is free or can itself be made from other units. The plan lists those
        units first. ``keep`` adds units the caller relies on beyond the reservations.
        """
        resources = resources or self.resources
        kept = self.kept(shortfall.goal) | frozenset(keep)
        plan = self._cover(dict(shortfall.missing), resources, kept, shortfall.goal, [], depth=0)
        return plan or []

    def _cover(self, missing, resources, kept, goal, planned, depth):
        plan = []
        used = {unit.key for unit in planned}
        for kind, count in missing.items():
            got = 0
            candidates = sorted((unit for unit in resources.units if unit.frees == kind and unit.value != PRICELESS
                                 and unit.key not in kept),
                                key=lambda unit: (unit.value / max(unit.amount, 1), unit.order))
            for unit in candidates:
                if got >= count:
                    break
                if unit.key in used:
                    continue
                before = self._prepare(unit, resources, kept, goal, planned + plan, depth)
                if before is None:
                    continue
                plan.extend(before)
                plan.append(unit)
                used.update(row.key for row in before)
                used.add(unit.key)
                got += unit.amount
            if got < count:
                return None
        return plan

    def compare(self, goal, kind, existing, count=1, resources=None):
        """Log when the ledger would free ``kind`` with other units than the existing check picked.

        ``existing`` is the detail of the unit the older check chose, or None when it found nothing.
        Returns the ledger's own choice as a list of details, so callers and tests can read it.
        """
        resources = resources or self.resources
        plan = self.make_room(Shortfall(goal, {kind: count}), resources)
        chosen = [unit.detail for unit in plan if unit.frees == kind]
        if chosen[:1] != ([] if existing is None else [existing]):
            log.debug('ledger %s for %s picks %s where the existing check picks %s', kind, goal, chosen, existing)
        return chosen

    def _prepare(self, unit, resources, kept, goal, planned, depth):
        """Units that make the room ``unit`` itself needs, [] when it is free, or None when it cannot be made."""
        missing = {}
        for kind, count in unit.needs.amounts().items():
            # Room already freed by units planned before this one counts, and room they consume does not.
            have = self.available(kind, goal, resources) + sum(
                row.amount for row in planned if row.frees == kind) - sum(
                row.needs.amounts().get(kind, 0) for row in planned)
            if count > have:
                missing[kind] = count - max(have, 0)
        if not missing:
            return []
        if depth:
            return None
        return self._cover(missing, resources, kept, goal, planned, depth + 1)
