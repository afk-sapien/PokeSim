"""Shadow mode for the utility arbiter: what it would have picked, while the old order still decides.

Each generation's planner calls ``Shadow.compare`` at the points where it already picks a goal, with a
function that builds the arbiter's candidates and the key the old order chose. The comparison goes only
to the log and to counters that ``tools/replay_audit.py`` reads. Nothing here changes a decision, draws
a random number, steps the emulator or goes into a saved game.

A candidate's ``goal`` holds its kind, such as ``collection new entry`` or ``heal``, for the audit's
frame share by would-have-chosen kind. An inner point, such as the Gen I collection pick, runs before
the outer point that holds it, the Gen I overworld chain, so ``pick`` ends each decision on the outer
point's kind.

A failure in shadow code is logged once per point and never reaches the run.
"""
from __future__ import annotations

from collections import Counter
import logging

from . import arbiter

log = logging.getLogger(__name__)


class Shadow:
    def __init__(self, enabled=True):
        self.enabled = enabled
        # Comparisons and agreements per point.
        self.decisions = Counter()
        self.agreed = Counter()
        # 'point difference', such as 'collection score'.
        self.differences = Counter()
        # 'point: chosen kind -> pick kind' for each disagreement.
        self.disagreements = Counter()
        # The kind of the latest pick, which the audit counts frames against.
        self.pick = None
        # The candidates each point built last, by key, and its pick, for an outer point to reuse.
        self.built = {}
        self.picked = {}
        # The kind an inner point picked since an outer point last took it.
        self.pending = None
        self.last = {}
        self.failed = set()

    def changed(self, point, key):
        """Whether ``key`` differs from the last key chosen at ``point``, which makes it a new pick."""
        if self.last.get(point, object()) == key:
            return False
        self.last[point] = key
        return True

    def take(self):
        """The kind an inner point picked since the last take, or None, which an outer point counts."""
        kind, self.pending = self.pending, None
        return kind

    def compare(self, point, build, chosen, outer=False):
        """Compare the arbiter's pick from ``build()`` with ``chosen``, the key the old order chose.

        An ``outer`` point holds inner ones, so its pick is not left for another outer point to take.
        """
        if not self.enabled:
            return None
        try:
            candidates = list(build())
            result = arbiter.compare(candidates, None, chosen)
            self._count(point, candidates, result, outer)
            return result
        except Exception:
            if point not in self.failed:
                self.failed.add(point)
                log.exception('The shadow arbiter failed at %s. The old order still decides.', point)
            return None

    def _count(self, point, candidates, result, outer):
        self.built[point] = {candidate.key: candidate for candidate in candidates}
        kinds = {candidate.key: candidate.goal for candidate in candidates}
        pick = result.pick
        self.picked[point] = pick
        self.pick = None if pick is None else kinds.get(pick.key) or pick.key
        if not outer:
            self.pending = self.pick
        self.decisions[point] += 1
        if result.agrees:
            self.agreed[point] += 1
            return
        self.differences[f'{point} {result.difference}'] += 1
        chosen = kinds.get(result.chosen) or result.chosen
        self.disagreements[f'{point}: {chosen} -> {self.pick}'] += 1
        log.debug('Shadow arbiter at %s would pick %s over %s (%s)', point,
                  pick.key if pick else None, result.chosen, result.difference)

    def summary(self):
        """The counters as plain data, for the audit's run file."""
        return {'decisions': dict(self.decisions), 'agreed': dict(self.agreed),
                'differences': dict(self.differences), 'disagreements': dict(self.disagreements),
                'failed': sorted(self.failed)}
