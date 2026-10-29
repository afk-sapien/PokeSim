"""One utility arbiter that picks the next goal, for both generations.

Each generation's adapter turns its goal sources into candidates. A candidate says how much progress
it buys and how many frames it is expected to take. The arbiter takes the highest tier that has an
active candidate and, within it, the most value per frame. A candidate that cuts into a running goal
adds the frames lost by leaving it. Ties break on key, so the same list always gives the same pick.

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
    PROGRESS = 2
    FILLER = 3


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
    # The adapter's own goal, handed back with the pick. It takes no part in comparing candidates.
    goal: object = field(default=None, compare=False)

    @property
    def score(self):
        """Value per frame. A candidate expected to take no frames counts as taking one."""
        return self.value / max(self.expected_frames + self.interrupt_frames, 1.0)


def _order(candidate):
    return candidate.tier, -candidate.score, candidate.key


def rank(candidates):
    """The candidates that may be chosen, best first. Passive candidates are left out."""
    return sorted((candidate for candidate in candidates if not candidate.passive), key=_order)


def choose(candidates, state=None):
    """The candidate to run next, or None when the list is empty or holds only passive waits.

    ``state`` is the snapshot the candidates were built from. The arbiter reads nothing from it, since
    each adapter puts what the snapshot says into its candidates.
    """
    ranked = rank(candidates)
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
    if pick.tier < best.tier:
        return Comparison(chosen_key, pick, TIER)
    if pick.score > best.score:
        return Comparison(chosen_key, pick, SCORE)
    return Comparison(chosen_key, pick, KEY)
