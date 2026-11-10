"""Typed progress events and encounter counters, for both generations (docs/design/goal-system.md, section 4).

Catches, receives, releases, marathon checkpoints and goal ends each write one row to
``progress_events``. ``net`` says whether a row counts as progress, from the Kinds table. The rows
are written in shadow mode: nothing reads them for a decision yet, and a stall, LoopGuard or the
watchdog still go by the journal.

``encounter_counts`` keeps one row per goal per game hour. Its writer comes with the goal record,
which knows the hunt's target and rule. Both tables come from the schema version (pokesim.state).
"""
import time

from .state.journal import add_progress

# Net per kind. An item is net only when it was needed, so its writer says which.
NET = {'dex': 1, 'improve': 1, 'badge': 1, 'league': 1, 'event': 1, 'area': 1, 'checkpoint': 1,
       'catch': 0, 'receive': 0, 'release': 0, 'room': 0, 'level': 0, 'goal': 0, 'plan': 0}
KINDS = frozenset(NET) | {'item'}
# Journal entries that stand for a Pokémon joining or leaving. Custom gifts skip add_event, so their
# receipts write the row instead.
JOURNAL = {'obtain': 'receive', 'trade': 'receive', 'hatch': 'receive', 'release': 'release'}
# Active PlayClock frames in one game hour, the encounter counters' bucket.
HOUR = 216000


def frame(store):
    """The adventure's PlayClock frame, or None where no emulator runs, as for a page or a trade worker."""
    clock = getattr(store, 'clock', None)
    return clock() if clock else None


def identity(trainer_id, dvs, species):
    """Trainer id, DVs and species, the key that tells two copies of a species apart."""
    return f'{"" if trainer_id is None else trainer_id}:{bytes(dvs).hex()}:{species}'


def record(db, kind, *, frame=None, goal='', tier='', species=None, identity=None, score=None, net=None):
    """Write one row inside the caller's transaction."""
    if kind not in KINDS:
        raise ValueError(f'Unknown progress event kind {kind!r}')
    if net is None:
        if kind not in NET:
            raise ValueError('An item row says whether the item was needed')
        net = NET[kind]
    add_progress(db, frame, time.time(), kind, goal or '', tier or '', species, identity, score, int(bool(net)))


def write(store, kind, **fields):
    """Write one row in a transaction of its own, at the adventure's PlayClock frame."""
    with store.transaction() as db:
        record(db, kind, frame=frame(store), **fields)


def journal(db, event_type, *, frame=None, species=None):
    """The receive or release row for a journal entry, written in the entry's own transaction."""
    kind = JOURNAL.get(event_type)
    if kind:
        record(db, kind, frame=frame, species=species)


def queued(kind, **fields):
    """A row for an emulator queue that otherwise holds journal entries, kept as plain data for the save."""
    return {'progress': kind, **fields}


def drain(store, rows):
    """Write the queued rows and return the journal entries left."""
    rows = list(rows)
    progress = [row for row in rows if isinstance(row, dict) and 'progress' in row]
    if progress:
        with store.transaction() as db:
            for row in progress:
                fields = dict(row)
                record(db, fields.pop('progress'), frame=frame(store), **fields)
    return [row for row in rows if not (isinstance(row, dict) and 'progress' in row)]


def checkpoints(before, after, goal):
    """A ``checkpoint`` row for each marathon checkpoint reached past the starting line.

    ``before`` and ``after`` count the starting line, as the race's own counter does. The score is the
    checkpoints reached so far.
    """
    return [queued('checkpoint', goal=goal, tier='RACE', score=point - 1)
            for point in range(max(before, 1) + 1, after + 1)]


class GoalWatch:
    """Writes a ``goal`` row when the running goal ends, seen as its key changing between decisions."""

    def __init__(self):
        self.key, self.tier = None, ''

    def observe(self, store, key, tier=''):
        if key == self.key:
            return
        if self.key:
            write(store, 'goal', goal=self.key, tier=self.tier)
        self.key, self.tier = key, tier
