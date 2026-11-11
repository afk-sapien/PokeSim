"""Persist postgame priorities and outcomes across expeditions and restarts.

The outcomes ride in the policy's save. The stand-downs and spent frames live in the supervisor's
tables (runtime.supervision.Tables), so a reload keeps them, and their times are PlayClock frames.
"""
from copy import deepcopy

from ..planning import arbiter
from ..planning.monitor import STAND_DOWNS, STOOD_DOWN, Backoff, Monitor
from ..runtime.supervision import Tables


def category(project):
    """The project's category for the outcome counts, its kind's (policies/kinds.py) unless it is a legendary."""
    if project.get('legendary'):
        return 'legendary'
    from .kinds import rules
    return rules(project['method']).category


def new_entry(project):
    """True when finishing the project registers a species the Pokédex does not have yet."""
    kind = category(project)
    if kind == 'legendary':
        # A legendary that came back to a cartridge whose Pokédex has it, such as Red's Articuno, is a repeat.
        return not project.get('repeat') or bool(project.get('needed_capture'))
    if kind == 'evolution':
        return not project.get('upgrade_evolution')
    return kind == 'collection' and (not project.get('repeat') or bool(project.get('needed_capture')))


# A project that stood down waits about 17 game minutes, 60000 PlayClock frames, doubled for each
# stand-down in a row and three times at most. A project that made some progress waits the base only.
RETRY = Backoff(60000, doublings=3)
# Keys the monitor remembers, oldest dropped first.
REMEMBERED = 128


class AdventureDirector:
    def __init__(self):
        self.outcomes = []
        self.completed = {}
        self.attach(Tables())

    def attach(self, tables):
        """Keep the stand-downs and spent frames in ``tables``, which Store.attach hands the policy."""
        self.progress = tables
        self.monitor = Monitor(tables, RETRY)

    def state_dict(self):
        return deepcopy({key: getattr(self, key) for key in ('outcomes', 'completed')})

    def load(self, data, elapsed=0, attempts=None):
        """Take a save's outcomes, and its stand-downs only when there are none yet.

        A save from before the tables moved to the supervisor carries its own, timed on the
        collection's ``elapsed`` frames, and an older one still its ``attempts`` retry times. True when
        there were no tables, so the caller may take the save's budget figures as well.
        """
        # An older save also kept the recent picks the decay read. The arbiter has no use for them.
        self.outcomes = deepcopy(data.get('outcomes', []))[-24:]
        self.completed = dict(data.get('completed', {}))
        progress = data.get('progress')
        if not isinstance(progress, dict):
            # An older save kept only the failure counts, with its retry times in the collection.
            progress = {STAND_DOWNS: dict(data.get('failures', {}))}
        progress = deepcopy(progress)
        counts = progress.get(STAND_DOWNS) or {}
        for key, deadline in (attempts or {}).items():
            if deadline > elapsed:
                progress.setdefault(STOOD_DOWN, {})[key] = deadline - RETRY.wait(counts.get(key, 0))
        if not self.progress.adopt(progress, elapsed):
            return False
        self.trim()
        return True

    def trim(self):
        self.monitor.trim(REMEMBERED)

    def waiting(self, key, clock):
        """Whether the project ``key`` stood down and its wait has not run out at PlayClock frame ``clock``."""
        return self.monitor.standing_down(key, clock)

    def forget_expired(self, clock):
        """Drop retry times that have passed. The counts stay, so the next stand-down still doubles."""
        self.monitor.expire(clock)

    @staticmethod
    def select(candidates, projects, pinned=None):
        """The project the utility arbiter picks from ``candidates``, or None.

        ``projects`` maps each candidate's key to its project. The arbiter takes the highest tier and
        then the most value per expected frame, with ties on key. The tier filters, fixed priorities and
        recent-kind decay that used to decide here are gone, since a stalled project now stands down
        and waits under the monitor's backoff. ``pinned`` is the key a manager set as the next activity.
        """
        pick = arbiter.choose(candidates, pinned=pinned)
        return None if pick is None else projects[pick.key]

    def finish(self, project, clock, success, reason, progressed=False):
        key = project.get('key', project['method'])
        kind = category(project)
        if success:
            self.completed[kind] = self.completed.get(kind, 0) + 1
        if success or progressed and new_entry(project):
            self.monitor.clear(key)
            retry = 0
        else:
            # The key moves to the newest end so trimming drops the projects left alone longest.
            retry = self.monitor.stand_down(key, clock, progressed=progressed, most=RETRY.doublings + 1)
            self.trim()
        self.outcomes = (self.outcomes + [{
            'key': key, 'category': kind, 'status': 'completed' if success else 'advanced' if progressed else 'deferred',
            'reason': reason, 'clock': clock, 'retry_at': retry,
            'target': project.get('target_level', project.get('species')),
            'gains': deepcopy(project.get('gains', {})),
            'timing': {key: project['training_session'][key] for key in ('preparation_frames', 'active_frames')}
                      if project.get('training_session') else None,
        }])[-24:]
        return retry
