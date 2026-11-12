"""Typed progress events and encounter counters, for both generations (docs/design/goal-system.md, section 4).

Catches, receives, releases, marathon checkpoints and goal ends each write one row to
``progress_events``. So do a new Pokédex entry, a badge, a League win, a new area and an item, each
from the journal entry that reports it, and story flags set for the first time this run. A caught or
received copy the worth oracle kept for an improve reason (pcvalue.improvement), such as rarer DVs
or a later stage its family lacks, writes an ``improve`` row. So does a level gain toward the next
boss's readiness target, the first time that Pokémon reaches the level (gained). Any other level
gain writes a ``level`` row. Each reload writes a ``plan`` row that
names its reason. ``net`` says
whether a row counts as progress, from the Kinds table. The rows are written in shadow mode: nothing
reads them for a decision yet, and a stall, LoopGuard or the watchdog still go by the journal.

``encounter_counts`` keeps one row per goal per game hour. The cartridge's wild battle hook counts
each encounter in memory and the next decision writes them, judged by the hunt's target and rule.
Both tables come from the schema version (pokesim.state).
"""
import logging
import time

from .state.journal import add_encounters, add_progress, best_level

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
# The story flags this run has seen set, as hex. A reload keeps it and a restart empties it (state/domains.py).
FLAGS_KEY = 'goal-watch-flags-v1'


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


def entry(store, db, ev, snapshot=None):
    """The rows for a journal entry, in its own transaction: receive or release, a level gain's row,
    and the kind the detector tagged it with, such as ``dex`` or ``badge``, under the running goal."""
    at, species = frame(store), getattr(ev, 'species', None)
    journal(db, ev.type, frame=at, species=species)
    watch = getattr(store, 'goal_watch', None)
    if ev.type == 'level' and species is not None and getattr(ev, 'identity', None):
        gained(db, watch, ev, at, snapshot)
    if kind := getattr(ev, 'progress', ''):
        record(db, kind, frame=at, goal=watch.key if watch else '', tier=watch.tier if watch else '',
               species=species, net=getattr(ev, 'needed', None))


def mon_identity(trainer_id, dvs, dex):
    """``identity`` for a party Pokémon, from its DVs as read or as the two bytes the cartridge holds."""
    return identity(trainer_id, packed(dvs), dex) if dvs else None


def readiness(watch, snapshot):
    """The next boss's readiness target from the emulator's hook (GoalWatch.readiness), or None."""
    hook = getattr(watch, 'readiness', None)
    if hook is None or snapshot is None:
        return None
    try:
        return hook(snapshot)
    except Exception:
        # A shadow row must never cost the run its journal entry.
        log.exception('Cannot read the readiness target')
        return None


def gained(db, watch, ev, at, snapshot):
    """The row for a Pokémon's level gain: ``improve`` the first time it reaches the level and only at
    or under the next boss's readiness target (planning/readiness.target), else ``level``.

    Every gain writes one row with the level as its score, so the rows keep each Pokémon's highest
    level and a reload, a trade back or a loop of losses cannot count a level twice. The target
    moves only when the next boss changes, so such a loop adds at most the levels left to it."""
    best = best_level(db, ev.species, ev.identity)
    kind = 'level'
    if best is None or ev.score > best:
        aim = readiness(watch, snapshot)
        if aim is not None and ev.score <= aim:
            kind = 'improve'
    record(db, kind, frame=at, goal=watch.key if watch else '', tier=watch.tier if watch else '',
           species=ev.species, identity=ev.identity, score=ev.score)


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


def packed(dvs):
    """The two DV bytes the cartridge holds, from HP, Attack, Defense, Speed and Special or as read."""
    if len(dvs) == 5:
        return bytes((dvs[1] << 4 | dvs[2], dvs[3] << 4 | dvs[4]))
    return bytes(dvs)


def improved(store, db, species, dvs, identity=None):
    """The ``improve`` row for a caught or received copy the worth oracle kept for an improve reason
    (pcvalue.improvement), in the catch's own transaction, under the goal that noted it."""
    watch = getattr(store, 'goal_watch', None)
    noted = watch.expected.pop((species, packed(dvs)), None) if watch is not None else None
    if noted:
        record(db, 'improve', frame=frame(store), goal=noted[0], tier=noted[1], species=species, identity=identity)


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
    next decision writes, and ``flags`` the story flags this run has seen set. ``expected`` holds the
    copies the worth oracle kept for an improve reason, by species and DV bytes, until one is caught
    or received (improved).
    """
    # The newest copies ``expected`` holds. One is noted at each catch decision, and most are never thrown at.
    EXPECTED = 32

    def __init__(self):
        self.key, self.tier, self.hunt = None, '', None
        self.pending, self.flags, self.expected = [], b'', {}
        # The emulator's hook from a snapshot to the next boss's readiness target, for level gains (gained).
        self.readiness = None

    def expect(self, species, dvs, found):
        """Note a copy ``found`` (pcvalue.Worth) keeps for an improve reason, under the running goal."""
        from .pcvalue import improvement
        if not improvement(found) or len(dvs) not in (2, 5):
            return
        key = (species, packed(dvs))
        self.expected.pop(key, None)
        self.expected[key] = (self.key or '', self.tier)
        while len(self.expected) > self.EXPECTED:
            del self.expected[next(iter(self.expected))]

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
        them. The flags seen stay seen, so a reload that sets them again writes nothing. They are kept
        on the store, so a worker that starts again after a reload does too: a Gold League run that
        restarted from its entry save beat Will, Koga and Bruno again after each worker start, and each
        win wrote a net row though the reload had taken it back. The score is the count of flags seen.
        """
        flags = bytes(flags)
        if not flags:
            return
        if not self.flags:
            kept = stored_flags(store)
            self.flags = union(kept, flags) if kept else flags
            if self.flags != kept:
                save_flags(store, self.flags)
            return
        seen = self.flags.ljust(len(flags), b'\0')
        if any(now & ~old for old, now in zip(seen, flags)):
            self.flags = union(seen, flags)
            save_flags(store, self.flags)
            write(store, 'event', goal=self.key, tier=self.tier, score=sum(byte.bit_count() for byte in self.flags))

    def restart(self):
        """A new game: no encounters, flags or kept copies of the old one carry over. The restart's
        transaction empties the stored flags (Store.restart)."""
        self.pending, self.flags, self.expected = [], b'', {}


def union(seen, flags):
    """Every flag set in either reading, as long as the longer one."""
    seen = seen.ljust(len(flags), b'\0')
    return bytes(old | now for old, now in zip(seen, flags)) + seen[len(flags):]


def stored_flags(store):
    """The story flags the run has seen set, as the store keeps them, or b'' when it keeps none."""
    try:
        return bytes.fromhex(store.get(FLAGS_KEY) or '')
    except (AttributeError, TypeError, ValueError):
        return b''


def save_flags(store, flags):
    if hasattr(store, 'set'):
        store.set(FLAGS_KEY, flags.hex())


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
