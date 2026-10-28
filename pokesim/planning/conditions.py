"""One precondition check for goals and navigation edges, for both generations.

A goal says what must hold before it starts with ``requires``: items, badges, event flags, a ledger
``Need`` and the maps it must reach. ``feasible`` checks them all at once and answers with what is
missing and the goals that would make each missing condition hold. A navigation edge carries the
same conditions, so a gate whose guard turns the player back is closed until its condition holds,
and its enabler is offered as a goal instead.

The check keeps no game knowledge. Each generation's adapter supplies a ``World`` that answers the
questions below from its own snapshot, and builds the enabler goals in its own goal type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .ledger import Need


class World(Protocol):
    """What a condition may ask about the game. Each generation's adapter reads it from a snapshot."""

    def has_item(self, item) -> bool: ...
    def has_badge(self, badge) -> bool: ...
    def event(self, flag) -> bool: ...
    def reachable(self, place) -> bool: ...
    def item_count(self, item) -> int: ...
    def can(self, action) -> bool: ...


class Condition(Protocol):
    def holds(self, world: World) -> bool: ...
    def enabler(self, world: World) -> object | None: ...


# Builds the goal that would make a condition hold, or gives None when no goal can.
Enabler = Callable[[World], object]


def _no_enabler(world):
    return None


@dataclass(frozen=True)
class _Base:
    # Compared by value, so two edges that need the same item share one condition in a set.
    enable: Enabler = field(default=_no_enabler, compare=False, kw_only=True)

    def enabler(self, world):
        return self.enable(world)


@dataclass(frozen=True)
class Item(_Base):
    """An item somewhere in the bag, such as the Bicycle the Cycling Road guards ask for."""
    item: object

    def holds(self, world):
        return world.has_item(self.item)


@dataclass(frozen=True)
class Count(_Base):
    """At least ``at_least`` of ``items`` together in the bag, such as five balls for a hunt."""
    items: tuple
    at_least: int = 1

    def holds(self, world):
        return sum(world.item_count(item) for item in self.items) >= self.at_least


@dataclass(frozen=True)
class Can(_Base):
    """Something the adapter decides from the whole snapshot, such as room to catch or a party that surfs."""
    action: str

    def holds(self, world):
        return world.can(self.action)


@dataclass(frozen=True)
class Badge(_Base):
    """A badge, as the adapter numbers them (a bit for Red, Blue and Yellow)."""
    badge: object

    def holds(self, world):
        return world.has_badge(self.badge)


@dataclass(frozen=True)
class Event(_Base):
    """An event flag that is set, such as a Cinnabar Gym door unlocked."""
    flag: object

    def holds(self, world):
        return world.event(self.flag)


@dataclass(frozen=True)
class Reach(_Base):
    """A map or place the route planner can reach from here."""
    place: object

    def holds(self, world):
        return world.reachable(self.place)


@dataclass(frozen=True)
class AnyOf(_Base):
    """Holds when one of ``options`` holds. Its enabler is the first option enabler that gives a goal."""
    options: tuple

    def holds(self, world):
        return any(option.holds(world) for option in self.options)

    def enabler(self, world):
        goal = self.enable(world)
        if goal is not None:
            return goal
        return next((goal for option in self.options if (goal := option.enabler(world)) is not None), None)


@dataclass(frozen=True)
class Requirements:
    """What a goal needs: conditions that must hold and room the ledger must hold for it."""
    conditions: tuple = ()
    need: Need = field(default_factory=Need)


@dataclass(frozen=True)
class Feasibility:
    """The answer of ``feasible``: ok, or the missing conditions, the ledger shortfall and their enablers."""
    missing: tuple = ()
    shortfall: object = None
    enablers: tuple = ()

    @property
    def ok(self):
        return not self.missing and self.shortfall is None

    def __bool__(self):
        return self.ok


FEASIBLE = Feasibility()


def requirements(goal, world):
    """A goal's ``Requirements``. A goal may give them directly or through a ``requires(world)`` method."""
    if goal is None:
        return Requirements()
    if isinstance(goal, Requirements):
        return goal
    requires = getattr(goal, 'requires', None)
    if requires is None:
        return Requirements()
    found = requires(world) if callable(requires) else requires
    return found if isinstance(found, Requirements) else Requirements(tuple(found))


def missing(conditions, world):
    """The conditions among ``conditions`` that do not hold, in order."""
    return tuple(condition for condition in conditions if not condition.holds(world))


def feasible(goal, world, ledger=None, key=None):
    """Whether ``goal`` can start in ``world``.

    The conditions are checked in the order the goal lists them. With a ledger and a ``Need``, the
    goal's room is reserved under ``key`` (the goal's own key by default), and a shortfall is given
    back in place of the reservation. Enablers are the goals that would make a missing condition hold,
    one per condition that has one, without repeats.
    """
    found = requirements(goal, world)
    gaps = missing(found.conditions, world)
    shortfall = None
    if ledger is not None and found.need.amounts():
        name = key if key is not None else getattr(goal, 'key', str(goal))
        answer = ledger.reserve(name, found.need)
        if not answer.ok:
            shortfall = answer
    if not gaps and shortfall is None:
        return FEASIBLE
    enablers = []
    for condition in gaps:
        goal_for = condition.enabler(world)
        if goal_for is not None and goal_for not in enablers:
            enablers.append(goal_for)
    return Feasibility(gaps, shortfall, tuple(enablers))
