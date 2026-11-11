"""Shadow mode for the utility arbiter: what it would have picked, while the old order still decides.

Each generation's planner calls ``Shadow.compare`` at the points where it already picks a goal, with a
function that builds the arbiter's candidates and the key the old order chose. The comparison goes only
to the log and to counters that ``python -m pokesim.replay audit`` reads. Nothing here changes a decision, draws
a random number, steps the emulator or goes into a saved game.

A candidate's ``goal`` holds its kind, such as ``collection new entry`` or ``heal``, for the audit's
frame share by would-have-chosen kind. An inner point, such as the Gen I collection pick, runs before
the outer point that holds it, the Gen I decide pipeline, so ``pick`` ends each decision on the outer
point's kind.

``Shadow.weigh`` runs the decide pipeline (planning/decide.py) beside the old chain in the same way. It
also counts decisions by the source of the chain's goal, and the frames each point's two picks agree.

A failure in shadow code is logged once per point and never reaches the run.
"""
from __future__ import annotations

from collections import Counter
import logging

from . import arbiter
from . import decide

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
        # 'point source' decisions and agreements, by the source of the goal the old chain chose.
        self.sources = Counter()
        self.sources_agreed = Counter()
        # Frames per point between decisions, and those under a decision where both picks agreed.
        self.frames = Counter()
        self.frames_agreed = Counter()
        # The frame and agreement of each point's latest decision, which the next one counts frames from.
        self.agreeing = {}
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
            self._failed(point)
            return None

    def weigh(self, point, build, chosen, token=None, frame=None):
        """Run the decide pipeline from ``build()``, a ``decide.Decision``, beside ``chosen``, the goal key
        the old chain chose, and return the Decision.

        The agreement is kept on every call, so ``frame`` counts the frames since the last call under it.
        A decision is counted when either key or ``token`` changes, as a long wait under one goal would
        otherwise drown the moments that matter. It is an outer point.
        """
        if not self.enabled:
            return None
        try:
            decision = build()
            difference = decide.difference(decision, chosen)
            self._clock(point, frame, difference is None)
            pick = decision.pick
            self.pick = None if pick is None else pick.kind
            if self.changed(point, (chosen, decision.key, token)):
                mine = next((offer for offer in decision.offers if offer.key == chosen), None)
                source = mine.source if mine is not None else 'none' if chosen is None else arbiter.UNLISTED
                self._tally(point, source, 'none' if pick is None else pick.source, difference, source)
                if difference is not None:
                    log.debug('The decide pipeline at %s would pick %s over %s (%s)', point,
                              decision.key, chosen, difference)
            return decision
        except Exception:
            self._failed(point)
            return None

    def _failed(self, point):
        if point not in self.failed:
            self.failed.add(point)
            log.exception('The shadow arbiter failed at %s. The old order still decides.', point)

    def _clock(self, point, frame, agrees):
        if frame is None:
            return
        last = self.agreeing.get(point)
        if last is not None and frame >= last[0]:
            self.frames[point] += frame - last[0]
            if last[1]:
                self.frames_agreed[point] += frame - last[0]
        self.agreeing[point] = (frame, agrees)

    def _tally(self, point, chosen, pick, difference, source=None):
        """Count one decision at ``point``, where the old order chose ``chosen`` and shadow picked ``pick``."""
        self.decisions[point] += 1
        if source is not None:
            self.sources[f'{point} {source}'] += 1
        if difference is None:
            self.agreed[point] += 1
            if source is not None:
                self.sources_agreed[f'{point} {source}'] += 1
            return
        self.differences[f'{point} {difference}'] += 1
        self.disagreements[f'{point}: {chosen} -> {pick}'] += 1

    def _count(self, point, candidates, result, outer):
        self.built[point] = {candidate.key: candidate for candidate in candidates}
        kinds = {candidate.key: candidate.goal for candidate in candidates}
        pick = result.pick
        self.picked[point] = pick
        self.pick = None if pick is None else kinds.get(pick.key) or pick.key
        if not outer:
            self.pending = self.pick
        chosen = kinds.get(result.chosen) or result.chosen
        self._tally(point, chosen, self.pick, result.difference)
        if not result.agrees:
            log.debug('Shadow arbiter at %s would pick %s over %s (%s)', point,
                      pick.key if pick else None, result.chosen, result.difference)

    def point(self, point, top=3):
        """One point's decisions, agreements, frames, differences and top disagreements, or None when the
        point made no decision. The gate and the scenario replays report it per rung."""
        if not self.decisions[point]:
            return None
        prefix = f'{point}: '
        return {'decisions': self.decisions[point], 'agreed': self.agreed[point],
                'frames': self.frames[point], 'frames_agreed': self.frames_agreed[point],
                'differences': {key[len(point) + 1:]: count for key, count in self.differences.items()
                                if key.startswith(f'{point} ')},
                'sources': {key[len(point) + 1:]: [count, self.sources_agreed[key]]
                            for key, count in self.sources.items() if key.startswith(f'{point} ')},
                'top': [[key[len(prefix):], count] for key, count in self.disagreements.most_common()
                        if key.startswith(prefix)][:top]}

    def summary(self):
        """The counters as plain data, for the audit's run file."""
        return {'decisions': dict(self.decisions), 'agreed': dict(self.agreed),
                'differences': dict(self.differences), 'disagreements': dict(self.disagreements),
                'sources': dict(self.sources), 'sources_agreed': dict(self.sources_agreed),
                'frames': dict(self.frames), 'frames_agreed': dict(self.frames_agreed),
                'failed': sorted(self.failed)}
