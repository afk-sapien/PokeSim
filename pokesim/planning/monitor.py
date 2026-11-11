"""One progress monitor with backoff for every goal.

A goal is known by its key. The monitor counts the frames each key spends, clears the count when the
goal makes progress, and says when a goal has spent its budget without any. A goal that stands down
waits before it is tried again, and the wait doubles with each stand-down in a row.

The monitor keeps no clock of its own. Each caller passes ``now`` in PlayClock frames, and the waits are
in frames too. A budget counts in the caller's unit, which is frames for Red, Blue and Yellow and
decisions for Gold, Silver and Crystal. The state lives in a dictionary the caller hands it, which in
both generations is the supervisor's tables (runtime/supervision.py), and a reload keeps them. The frame
counts behind ``shares`` are kept for the session only.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# Names inside the state dictionary. ``stood_down`` maps a key to the frame it last stood down, under
# the name older Gold, Silver and Crystal saves used.
STOOD_DOWN = 'stood_down'
STAND_DOWNS = 'stand_downs'
SPENT = 'progress_frames'
# The kind of failure that set a key aside (planning/decide.py), kept while it stands down.
FAILURES = 'failures'


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
    """The wait after a stand-down: ``base``, doubled once per stand-down in a row, ``doublings`` times at most.

    A ``linear`` backoff adds ``base`` for each stand-down in a row instead, and ``limit`` caps either wait.
    """
    base: float
    doublings: int = 0
    linear: bool = False
    limit: float | None = None

    def wait(self, count):
        count = max(count, 1)
        wait = self.base * count if self.linear else self.base * 2 ** min(count - 1, self.doublings)
        return wait if self.limit is None else min(self.limit, wait)


# A missed legendary encounter returns after 36000 frames for each miss in a row, at most 180000. Both
# generations count it on the PlayClock (runtime.supervision.LegendaryRetries).
LEGENDARY_RETRY = Backoff(36000, linear=True, limit=180000)


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

    def set_spent(self, key, frames):
        """Set the frames ``key`` has spent since its last progress. None or no frames forgets them."""
        spent = self._table(SPENT)
        if frames and frames > 0:
            spent[key] = frames
        else:
            spent.pop(key, None)

    def since(self, key):
        """When ``key`` last stood down, or None when it has not."""
        return self._table(STOOD_DOWN).get(key)

    def stood_down(self):
        """A copy of when each key last stood down, oldest first."""
        return dict(self._table(STOOD_DOWN))

    def stand_down(self, key, now, progressed=False, most=None, failure=None):
        """Set ``key`` aside from ``now`` and return when it may be tried again.

        A goal that made some progress before it stopped waits the base time and starts its count of
        stand-downs again. Otherwise each stand-down in a row doubles the wait. With ``most``, the count
        kept is capped there and the key moves to the newest end, so ``trim`` drops the keys left alone
        longest. The wait returned still counts this stand-down in full. ``failure`` is the kind of
        failure that set it aside, which ``failure`` answers while it waits.
        """
        self._forget_failure(key)
        if failure:
            self._table(FAILURES)[key] = failure
        counts = self._table(STAND_DOWNS)
        if most is not None and key in counts:
            counts[key] = counts.pop(key)
        count = 0 if progressed else counts.get(key, 0) + 1
        if count:
            counts[key] = count if most is None else min(count, most)
        else:
            counts.pop(key, None)
        self._table(STOOD_DOWN)[key] = now
        self._table(SPENT).pop(key, None)
        return now + self.backoff.wait(count)

    def expire(self, now):
        """Forget the stand-down times that ran out by ``now``. The counts stay, so the next stand-down
        in a row still waits longer."""
        stood = self._table(STOOD_DOWN)
        for key in [key for key in stood if not self.standing_down(key, now)]:
            del stood[key]
            self._forget_failure(key)

    def _forget_failure(self, key):
        # The failures table is made only by a failure, so a run that never parks keeps the tables it had.
        failures = self.state.get(FAILURES)
        if isinstance(failures, dict):
            failures.pop(key, None)

    def trim(self, limit):
        """Keep the newest ``limit`` keys in each table."""
        for name in (STOOD_DOWN, STAND_DOWNS, SPENT):
            table = self._table(name)
            for key in list(table)[:-limit]:
                del table[key]
        failures = self.state.get(FAILURES)
        if isinstance(failures, dict):
            for key in list(failures)[:-limit]:
                del failures[key]

    def until(self, key):
        """When ``key`` may be tried again, or None when it has not stood down."""
        since = self._table(STOOD_DOWN).get(key)
        if since is None:
            return None
        return since + self.backoff.wait(self._table(STAND_DOWNS).get(key, 0))

    def standing_down(self, key, now):
        until = self.until(key)
        return until is not None and now < until

    def failure(self, key, now):
        """The kind of failure ``key`` stands down for at ``now``, or None when it is not standing down
        or stood down for no named failure."""
        return self._table(FAILURES).get(key) if self.standing_down(key, now) else None

    def clear(self, key):
        """Forget ``key``'s stand-downs, failure and spent frames, as when its goal is done."""
        for name in (STOOD_DOWN, STAND_DOWNS, SPENT):
            self._table(name).pop(key, None)
        self._forget_failure(key)

    def rows(self, name):
        """The caller's own table ``name`` inside the same state, such as the no-route attempts."""
        return self._table(name)

    def rows(self, name):
        """The caller's own table ``name`` inside the same state, such as the no-route attempts."""
        return self._table(name)

    def shares(self):
        """Share of the frames counted this session, per goal key."""
        total = sum(self.frames.values())
        return {key: value / total for key, value in self.frames.most_common()} if total else {}
