"""Persist postgame priorities and outcomes across expeditions and restarts."""
from copy import deepcopy

from ..planning import arbiter
from ..planning.monitor import SPENT, STAND_DOWNS, STOOD_DOWN, Backoff, Monitor


def category(project):
    if project.get('legendary'):
        return 'legendary'
    method = project['method']
    if method == 'marathon':
        return 'recreation'
    if method == 'evolve':
        return 'evolution'
    if method == 'train':
        return 'training'
    if method in ('trainer', 'explore'):
        return 'exploration'
    if method in ('rematch', 'rod'):
        return 'supplies'
    return 'collection'


def new_entry(project):
    """True when finishing the project registers a species the Pokédex does not have yet."""
    kind = category(project)
    if kind == 'legendary':
        # A legendary that came back to a cartridge whose Pokédex has it, such as Red's Articuno, is a repeat.
        return not project.get('repeat') or bool(project.get('needed_capture'))
    if kind == 'evolution':
        return not project.get('upgrade_evolution')
    return kind == 'collection' and (not project.get('repeat') or bool(project.get('needed_capture')))


# A project that stood down waits a minute of play, 60000 elapsed frames, doubled for each stand-down
# in a row and three times at most. A project that made some progress waits the minute only.
RETRY = Backoff(60000, doublings=3)
# Keys the monitor remembers, oldest dropped first.
REMEMBERED = 128


class AdventureDirector:
    def __init__(self):
        self.outcomes = []
        self.completed = {}
        self.progress = {}
        self.monitor = Monitor(self.progress, RETRY)

    @property
    def failures(self):
        """Stand-downs in a row per project key."""
        return self.monitor._table(STAND_DOWNS)

    def state_dict(self):
        saved = deepcopy({key: getattr(self, key) for key in ('outcomes', 'completed')})
        saved['progress'] = {name: dict(table) for name, table in self.progress.items() if table}
        return saved

    def load(self, data):
        # An older save also kept the recent picks the decay read. The arbiter has no use for them.
        self.outcomes = deepcopy(data.get('outcomes', []))[-24:]
        self.completed = dict(data.get('completed', {}))
        progress = data.get('progress')
        if not isinstance(progress, dict):
            # An older save kept only the failure counts. Its retry times are in the collection.
            progress = {STAND_DOWNS: dict(data.get('failures', {}))}
        self.progress = deepcopy(progress)
        self.monitor = Monitor(self.progress, RETRY)
        self.trim()

    def trim(self):
        for name in (STOOD_DOWN, STAND_DOWNS, SPENT):
            table = self.monitor._table(name)
            for key in list(table)[:-REMEMBERED]:
                del table[key]

    def waiting(self, key, elapsed):
        """Whether the project ``key`` stood down and its wait has not run out at ``elapsed``."""
        return self.monitor.standing_down(key, elapsed)

    def forget_expired(self, elapsed):
        """Drop retry times that have passed. The counts stay, so the next stand-down still doubles."""
        stood = self.monitor._table(STOOD_DOWN)
        for key in [key for key in stood if not self.waiting(key, elapsed)]:
            del stood[key]

    def resume(self, key, deadline, elapsed):
        """Carry an older save's retry time for ``key`` over to the monitor."""
        if deadline > elapsed:
            self.monitor._table(STOOD_DOWN)[key] = deadline - RETRY.wait(self.failures.get(key, 0))

    @staticmethod
    def select(candidates, projects):
        """The project the utility arbiter picks from ``candidates``, or None.

        ``projects`` maps each candidate's key to its project. The arbiter takes the highest tier and
        then the most value per expected frame, with ties on key. The tier filters, fixed priorities and
        recent-kind decay that used to decide here are gone, since a stalled project now stands down
        and waits under the monitor's backoff.
        """
        pick = arbiter.choose(candidates)
        return None if pick is None else projects[pick.key]

    def finish(self, project, elapsed, success, reason, progressed=False):
        key = project.get('key', project['method'])
        kind = category(project)
        if success:
            self.completed[kind] = self.completed.get(kind, 0) + 1
        if success or progressed and new_entry(project):
            self.monitor.clear(key)
            retry = 0
        else:
            # Move the key to the newest end so trimming drops the projects left alone longest.
            count = self.failures.pop(key, None)
            if count is not None:
                self.failures[key] = count
            retry = self.monitor.stand_down(key, elapsed, progressed=progressed)
            if key in self.failures:
                self.failures[key] = min(self.failures[key], RETRY.doublings + 1)
            self.trim()
        self.outcomes = (self.outcomes + [{
            'key': key, 'category': kind, 'status': 'completed' if success else 'advanced' if progressed else 'deferred',
            'reason': reason, 'elapsed': elapsed, 'retry_at': retry,
            'target': project.get('target_level', project.get('species')),
            'gains': deepcopy(project.get('gains', {})),
            'timing': {key: project['training_session'][key] for key in ('preparation_frames', 'active_frames')}
                      if project.get('training_session') else None,
        }])[-24:]
        return retry
