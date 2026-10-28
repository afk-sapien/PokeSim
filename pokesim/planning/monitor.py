"""One progress monitor with backoff for every goal.

A goal is known by its key. The monitor counts the frames each key spends, clears the count when the
goal makes progress, and says when a goal has spent its budget without any. A goal that stands down
waits before it is tried again, and the wait doubles with each stand-down in a row.

The monitor keeps no clock of its own. Each caller passes ``now`` in its own unit, which is decisions
for Gold, Silver and Crystal and elapsed frames for Red, Blue and Yellow, and the waits are in the same
unit. The state that has to survive a restart lives in a plain dictionary the caller saves with its
policy. The frame counts behind ``shares`` are kept for the session only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# Names inside the saved state dictionary. ``stood_down`` maps a key to the time it last stood down,
# which is the format Gold, Silver and Crystal saves already use.
STOOD_DOWN = 'stood_down'
STAND_DOWNS = 'stand_downs'
SPENT = 'progress_frames'


@dataclass(frozen=True)
class ProgressEvent:
    """Something a goal was for: a dex entry, a catch, an item, a level, a badge or a map reached."""
    kind: str
    detail: object = None


@dataclass(frozen=True)
class Verdict:
    stand_down: bool = False
    # When a goal that stood down may be tried again, in the caller's unit of ``now``.
    until: float | None = None


CONTINUE = Verdict()


@dataclass(frozen=True)
class Backoff:
    """The wait after a stand-down: ``base``, doubled once per stand-down in a row, ``doublings`` times at most."""
    base: float
    doublings: int = 0

    def wait(self, count):
        return self.base * 2 ** min(max(count - 1, 0), self.doublings)


class Monitor:
    def __init__(self, state=None, backoff=Backoff(50000), multiple=3.0):
        self.state = {} if state is None else state
        self.backoff = backoff
        self.multiple = multiple
        self.budgets = {}
        self.frames = Counter()

    def _table(self, name):
        table = self.state.get(name)
        if not isinstance(table, dict):
            table = self.state[name] = {}
        return table

    def start(self, key, expected_frames=None, budget=None):
        """Begin or resume a goal. Its budget is ``budget``, or ``multiple`` times ``expected_frames``.

        Frames spent without progress are kept across a restart, so starting a goal again does not
        reset its count. Without either figure the goal is only counted, never stood down.
        """
        if budget is None and expected_frames is not None:
            budget = self.multiple * expected_frames
        self.budgets[key] = budget

    def observe(self, key, frames, events=(), now=None):
        """Count ``frames`` against ``key``. Any progress event clears its count of frames.

        The stand-downs in a row are kept. A Red hunt reaches new maps on every trip, and clearing them
        there would stop a hunt that never finds its Pokémon from waiting longer each time. They clear
        when the goal is done, or when it stands down after it made some progress.
        """
        self.frames[key] += frames
        spent = self._table(SPENT)
        if events:
            spent.pop(key, None)
            return CONTINUE
        spent[key] = spent.get(key, 0) + frames
        budget = self.budgets.get(key)
        if budget is None or spent[key] < budget:
            return CONTINUE
        if now is None:
            return Verdict(True)
        return Verdict(True, self.stand_down(key, now))

    def spent(self, key):
        """Frames ``key`` has spent since its last progress."""
        return self._table(SPENT).get(key, 0)

    def stand_down(self, key, now, progressed=False):
        """Set ``key`` aside from ``now`` and return when it may be tried again.

        A goal that made some progress before it stopped waits the base time and starts its count of
        stand-downs again. Otherwise each stand-down in a row doubles the wait.
        """
        counts = self._table(STAND_DOWNS)
        count = 0 if progressed else counts.get(key, 0) + 1
        if count:
            counts[key] = count
        else:
            counts.pop(key, None)
        self._table(STOOD_DOWN)[key] = now
        self._table(SPENT).pop(key, None)
        return now + self.backoff.wait(count)

    def until(self, key):
        """When ``key`` may be tried again, or None when it has not stood down."""
        since = self._table(STOOD_DOWN).get(key)
        if since is None:
            return None
        return since + self.backoff.wait(self._table(STAND_DOWNS).get(key, 0))

    def standing_down(self, key, now):
        until = self.until(key)
        return until is not None and now < until

    def clear(self, key):
        """Forget ``key``'s stand-downs and spent frames, as when its goal is done."""
        for name in (STOOD_DOWN, STAND_DOWNS, SPENT):
            self._table(name).pop(key, None)

    def shares(self):
        """Share of the frames counted this session, per goal key."""
        total = sum(self.frames.values())
        return {key: value / total for key, value in self.frames.most_common()} if total else {}
