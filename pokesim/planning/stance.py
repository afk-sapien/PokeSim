"""Fight, flee or catch, decided by the goal under way (planner design S5).

A wild battle is worth what it does for the current goal. A travel goal gains nothing from a plain
battle, so it runs from one. A training goal fights, since every battle is experience. A hunt catches
its target and runs from every other battle, which brings its next encounter sooner. Any other goal
fights as before, until the HP and PP it needs to reach its destination run out. It then runs too,
so the walk ends at its destination or at a Pokémon Center instead of in more battles.

Two rules hold for every goal. A Pokémon the run wants and can catch is caught, and a shiny it
cannot catch is run from rather than knocked out. A battle that forbids running is fought, and so is
one where running already failed ``FLEE_TRIES`` times, rather than burn more turns and HP.

The stance keeps no game knowledge. Each generation's adapter reads the encounter from its battle
memory and gives the goal's kind. Gold, Silver and Crystal use it, and so do Red, Blue and Yellow.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .ledger import Need


class Stance(Enum):
    FIGHT = 'fight'
    FLEE = 'flee'
    CATCH = 'catch'


FIGHT, FLEE, CATCH = Stance.FIGHT, Stance.FLEE, Stance.CATCH

# Goal kinds. A goal that names none is a story goal.
STORY = 'story'
TRAVEL = 'travel'
TRAIN = 'train'
HUNT = 'hunt'
# Kinds that run from every battle they cannot catch from.
FLEEING = frozenset({TRAVEL, HUNT})
# What a goal needs left to walk to its destination without turning back to heal: one point of HP
# above the heal line for every Pokémon, and one use of an attack for every Pokémon that has one.
WALK = Need(hp=1, pp=1)
# Failed run attempts in one battle before it is fought out (lead, 2026-10-29).
FLEE_TRIES = 2


@dataclass(frozen=True)
class Encounter:
    """One battle as the stance sees it.

    ``wanted`` is a Pokémon the run wants and can catch now. ``shiny`` is a wild shiny it cannot
    catch. ``escape`` is False when the battle forbids running, and ``tries`` counts the failed
    run attempts in this battle so far.
    """
    wild: bool
    wanted: bool = False
    shiny: bool = False
    escape: bool = True
    tries: int = 0


def budget_spent(ledger, goal, resources=None):
    """Whether ``goal`` has spent the HP or PP it needs for its walk. The one place that rule lives.

    ``resources`` may be a function that reads them, so a battle the stance settles first reads nothing.
    """
    if callable(resources):
        resources = resources()
    return not ledger.reserve(goal, WALK, resources).ok


def stance(kind, encounter, ledger, goal=None, resources=None):
    """How a goal of ``kind`` meets ``encounter``, with its HP and PP read from ``ledger``."""
    if not encounter.wild:
        return FIGHT
    if encounter.wanted:
        return CATCH
    if not encounter.escape or encounter.tries >= FLEE_TRIES:
        return FIGHT
    if encounter.shiny or kind in FLEEING:
        return FLEE
    if kind == TRAIN:
        return FIGHT
    return FLEE if budget_spent(ledger, goal or kind, resources) else FIGHT
