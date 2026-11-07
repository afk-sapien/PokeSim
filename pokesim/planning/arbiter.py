"""One utility arbiter that picks the next goal, for both generations.

Each generation's adapter turns its goal sources into candidates. A candidate says how much progress
it buys and how many frames it is expected to take. The arbiter takes the highest tier that has an
active candidate and, within it, the most value per frame. A candidate that cuts into a running goal
adds the frames lost by leaving it. Ties break on key, so the same list always gives the same pick.
The adventure's play style can move filler and collection hunts to another rank, never STORY or UPKEEP.

A passive candidate, such as Day Care steps or a clock wait, accrues while something else runs and is
never chosen. The arbiter keeps no game knowledge and no value weights. Values come in on each
candidate from the adapter that built it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Tier(IntEnum):
    """A higher tier always goes first, whatever the scores. A lower number is a higher tier."""
    STORY = 0
    UPKEEP = 1
    # New Pokédex entries and what opens them.
    PROGRESS = 2
    # A marathon that is due. It goes after new entries and urgent supplies and before every upgrade,
    # and its own cooldown keeps it rare (docs/marathon.md).
    RACE = 3
    # Better copies, training and other gains to what is already registered.
    UPGRADE = 4
    FILLER = 5


# Play styles, chosen per adventure and read from config.PLAY_STYLE on each ranking. Balanced ranks by
# tier alone. Story ranks filler below the plan placeholder. Collector ranks collection hunts with
# PROGRESS, before the Champion only those for species catchable now. STORY and UPKEEP never move.
BALANCED, STORY, COLLECTOR = 'balanced', 'story', 'collector'
PLAY_STYLES = (BALANCED, STORY, COLLECTOR)

# What kind of collection hunt a candidate is. Only the Collector style reads it.
NOT_HUNT = ''
HUNT_NOW = 'now'              # Before the Champion, a hunt for a species catchable now.
HUNT_LATER = 'later'          # Before the Champion, a hunt for a species not catchable now.
HUNT_POSTGAME = 'postgame'    # After the Champion, any collection hunt.


def hunt(champion, catchable):
    """The hunt kind of a collection hunt, from whether the Champion is beaten and the species is catchable now."""
    return HUNT_POSTGAME if champion else HUNT_NOW if catchable else HUNT_LATER


@dataclass(frozen=True)
class Candidate:
    key: str
    tier: Tier
    # Progress the goal buys, such as dex entries, level credit or a better copy.
    value: float
    # Travel plus the expected encounters times the frames per encounter.
    expected_frames: float
    # A wait that accrues on any walk. It is never chosen.
    passive: bool = False
    # Frames lost by cutting into the running goal: the walk back to it and any puzzle that resets.
    interrupt_frames: float = 0.0
    # One of the hunt kinds above, for a collection hunt the Collector style can promote.
    hunt: str = NOT_HUNT
    # The plan placeholder, or an errand that serves it. The Story style ranks filler below it.
    plan: bool = False
    # The adapter's own goal, handed back with the pick. It takes no part in comparing candidates.
    goal: object = field(default=None, compare=False)

    @property
    def score(self):
        """Value per frame. A candidate expected to take no frames counts as taking one."""
        return self.value / max(self.expected_frames + self.interrupt_frames, 1.0)


def play_style(style=None):
    """``style``, or else the adventure's play style. An unknown style ranks as Balanced."""
    if style is None:
        from .. import config
        style = getattr(config, 'PLAY_STYLE', BALANCED)
    return style if style in PLAY_STYLES else BALANCED


def standing(candidate, style=BALANCED):
    """Where ``candidate`` ranks under ``style``, as (rank, loses ties). A lower rank goes first.

    A hunt Collector promotes before the Champion loses ties to the goals already in its rank.
    """
    tier = candidate.tier
    if style == COLLECTOR and tier > Tier.PROGRESS and candidate.hunt in (HUNT_NOW, HUNT_POSTGAME):
        return int(Tier.PROGRESS), candidate.hunt == HUNT_NOW
    if style == STORY and tier == Tier.FILLER and not candidate.plan:
        return int(Tier.FILLER) + 1, False
    return int(tier), False


def ceiling(tier, style=BALANCED):
    """The best standing any candidate in ``tier`` can reach under ``style``."""
    if style == COLLECTOR and tier > Tier.PROGRESS:
        return int(Tier.PROGRESS), False
    return int(tier), False


def ahead(candidate, tier, style=None):
    """Whether ``candidate`` ranks above every candidate ``tier`` could offer, so that tier cannot win."""
    style = play_style(style)
    return standing(candidate, style) < ceiling(tier, style)


def _lane(candidate, pinned):
    """Where a pin puts a candidate. Upkeep still goes first, then the pinned key, then the rest."""
    if pinned is None:
        return 0
    if candidate.tier == Tier.UPKEEP:
        return 0
    return 1 if candidate.key == pinned else 2


def _order(candidate, pinned=None, style=BALANCED):
    return _lane(candidate, pinned), *standing(candidate, style), -candidate.score, candidate.key


def rank(candidates, pinned=None, style=None):
    """The candidates that may be chosen, best first, under ``style`` or the adventure's play style.
    Passive candidates are left out.

    ``pinned`` is the key a manager set as the next activity. It goes after upkeep and before every
    other candidate. Without a pin, or when no active candidate has its key, the order is the usual one.
    """
    style = play_style(style)
    active = [candidate for candidate in candidates if not candidate.passive]
    if all(candidate.key != pinned for candidate in active):
        pinned = None
    return sorted(active, key=lambda candidate: _order(candidate, pinned, style))


def choose(candidates, state=None, pinned=None, style=None):
    """The candidate to run next, or None when the list is empty or holds only passive waits.

    ``state`` is the snapshot the candidates were built from. The arbiter reads nothing from it, since
    each adapter puts what the snapshot says into its candidates. ``pinned`` and ``style`` are as for
    ``rank``.
    """
    ranked = rank(candidates, pinned, style)
    return ranked[0] if ranked else None


# How the arbiter's pick differs from the goal the old order chose.
TIER = 'tier'            # The pick is in a higher tier.
SCORE = 'score'          # Same tier, more value per frame.
KEY = 'key'              # Same tier and score, the tie broke on key.
PASSIVE = 'passive'      # The chosen goal is a passive wait, which the arbiter never picks.
UNLISTED = 'unlisted'    # The chosen goal is not among the candidates.
IDLE = 'idle'            # Nothing was chosen, but the arbiter has a pick.


@dataclass(frozen=True)
class Comparison:
    """What the arbiter would pick against the key that was chosen, for the shadow log."""
    chosen: str | None
    pick: Candidate | None
    # None when the two agree, otherwise one of the names above.
    difference: str | None = None

    @property
    def agrees(self):
        return self.difference is None


def compare(candidates, state, chosen_key):
    """Compare the arbiter's pick with ``chosen_key``, the goal the old order chose, or None for none."""
    pick = choose(candidates, state)
    if chosen_key is None:
        return Comparison(None, pick, None if pick is None else IDLE)
    if pick is not None and pick.key == chosen_key:
        return Comparison(chosen_key, pick)
    chosen = [candidate for candidate in candidates if candidate.key == chosen_key]
    if not chosen:
        return Comparison(chosen_key, pick, UNLISTED)
    active = rank(chosen)
    if not active:
        return Comparison(chosen_key, pick, PASSIVE)
    best = active[0]
    style = play_style()
    if standing(pick, style) < standing(best, style):
        return Comparison(chosen_key, pick, TIER)
    if pick.score > best.score:
        return Comparison(chosen_key, pick, SCORE)
    return Comparison(chosen_key, pick, KEY)
