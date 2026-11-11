"""Typed progress events and encounter counters, for both generations (docs/design/goal-system.md, section 4).

Catches, receives, releases, marathon checkpoints and goal ends each write one row to
``progress_events``. So do a new Pokédex entry, a badge, a League win, a new area and an item, each
from the journal entry that reports it, and story flags set for the first time this run. Each reload
writes a ``plan`` row that names its reason. ``net`` says
whether a row counts as progress, from the Kinds table. The rows are written in shadow mode: nothing
reads them for a decision yet, and a stall, LoopGuard or the watchdog still go by the journal.

``encounter_counts`` keeps one row per goal per game hour. The cartridge's wild battle hook counts
each encounter in memory and the next decision writes them, judged by the hunt's target and rule.
Both tables come from the schema version (pokesim.state).
"""
import logging
import time

from .state.journal import add_encounters, add_progress

log = logging.getLogger(__name__)

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


def entry(store, db, ev):
    """The rows for a journal entry, in its own transaction: receive or release, and the kind the
    detector tagged it with, such as ``dex`` or ``badge``, under the running goal."""
    at, species = frame(store), getattr(ev, 'species', None)
    journal(db, ev.type, frame=at, species=species)
    if kind := getattr(ev, 'progress', ''):
        watch = getattr(store, 'goal_watch', None)
        record(db, kind, frame=at, goal=watch.key if watch else '', tier=watch.tier if watch else '',
               species=species, net=getattr(ev, 'needed', None))


def reload(store, why):
    """A ``plan`` row for a reload or power cycle under the running goal. Its identity names the
    reason, such as ``reload:battle cannot end``, so a progress model can read it as a flag."""
    watch = getattr(store, 'goal_watch', None)
    try:
        write(store, 'plan', goal=watch.key if watch else '', tier=watch.tier if watch else '', identity=f'reload:{why}')
    except Exception:
        # A shadow row must never cost the run its reload.
        log.exception('Cannot record the reload row')


def encounter(store, species, dvs):
    """Count a wild encounter for the running goal. It stays in memory until the next decision."""
    watch, at = getattr(store, 'goal_watch', None), frame(store)
    if watch is not None and at is not None:
        watch.pending.append((watch.key or '', at // HOUR, watch.hunt, species, bytes(dvs)))


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
    """The running goal as the shadow writers see it, kept on the store as ``store.goal_watch``.

    It writes a ``goal`` row when the running goal ends, seen as its key changing between decisions.
    ``hunt`` is the goal's target species and rule for the encounter counters, or None. A target of
    None takes any species, and a rule of None takes any DVs. ``pending`` holds the encounters the
    next decision writes, and ``flags`` the story flags this run has seen set.
    """

    def __init__(self):
        self.key, self.tier, self.hunt = None, '', None
        self.pending, self.flags = [], b''

    def observe(self, store, key, tier='', hunt=None):
        """Called at each decision: write the encounters so far, then take the goal now running."""
        self.flush(store)
        self.hunt = hunt
        if key == self.key:
            return
        if self.key:
            write(store, 'goal', goal=self.key, tier=self.tier)
        self.key, self.tier = key, tier

    def flush(self, store):
        """Add the pending encounters to ``encounter_counts``, one row per goal per game hour."""
        if not self.pending:
            return
        counts = {}
        for goal, hour, hunt, species, dvs in self.pending:
            row = counts.setdefault((goal, hour), [0, 0, 0])
            row[0] += 1
            if hunt and hunt[0] in (None, species):
                row[1] += 1
                row[2] += met(hunt[1], dvs)
        self.pending = []
        with store.transaction() as db:
            for (goal, hour), row in counts.items():
                add_encounters(db, goal, hour, *row)

    def story(self, store, flags):
        """Write an ``event`` row when story flags are set that this run has not seen set before.

        The first reading only takes the flags already set, so a start or a restart counts none of
        them. The flags seen stay seen, so a reload that sets them again writes nothing. The score is
        the count of flags seen.
        """
        flags = bytes(flags)
        if not flags:
            return
        if not self.flags:
            self.flags = flags
            return
        seen = self.flags.ljust(len(flags), b'\0')
        if any(now & ~old for old, now in zip(seen, flags)):
            self.flags = bytes(old | now for old, now in zip(seen, flags)) + seen[len(flags):]
            write(store, 'event', goal=self.key, tier=self.tier, score=sum(byte.bit_count() for byte in self.flags))

    def restart(self):
        """A new game: no encounters or flags of the old one carry over."""
        self.pending, self.flags = [], b''


def met(rule, dvs):
    """Whether a target encounter's DVs meet the hunt's rule. A rule that fails counts as not met, so
    the shadow counters never stop a game."""
    if rule is None:
        return 1
    try:
        return int(bool(rule(dvs)))
    except Exception:
        log.exception('The hunt rule failed on a wild encounter')
        return 0
