"""Lifetime tallies of journal moments that outlive journal pruning, for both generations.

Faints, blackouts, trainer wins, evolutions and releases are journal entries, and old entries
can be pruned. Each one is also counted here, in the transaction that writes it. An adventure
recorded before these tallies starts from the entries its journal still holds.
"""
from .state import kv, tracking

KEY = 'adventure-counters-v1'
TYPES = {'faint': 'faints', 'blackout': 'blackouts', 'trainer': 'trainers_defeated',
         'evolve': 'evolutions', 'release': 'releases'}
NAMES = (*TYPES.values(), 'trainer_losses')
# A wild blackout names the wild foe in both generations. The journal has no other battle detail.
WILD = ' fighting a '


def _load(db):
    value = kv.get(db, KEY)
    if value is not None:
        value['counts'] = {**dict.fromkeys(NAMES, 0), **value.get('counts', {})}
        return value
    first, since = tracking.journal_start(db)
    # Ids only grow, so a journal that no longer starts at entry 1 has been pruned.
    complete = first == 1 or first is None and not tracking.issued(db)
    return {'counts': dict.fromkeys(NAMES, 0), 'through': 0, 'complete_history': complete,
            'since': None if complete else since}


def _catch_up(db, value, until):
    """Count the entries after the last one counted, up to but not including ``until``.

    Entries written by an older version, or by a stopped adventure's backfill, are counted
    here exactly once, since ``through`` only moves forward.
    """
    for kind, body in tracking.entries(db, value['through'], until, TYPES):
        value['counts'][TYPES[kind]] += 1
        if kind == 'blackout' and WILD not in (body or ''):
            # Both generations write the wild foe into the entry when they black out in a wild
            # battle, read from the battle mode at that moment. Any other blackout is a trainer loss.
            value['counts']['trainer_losses'] += 1
    value['through'] = max(value['through'], until - 1)


def _save(db, value):
    kv.put(db, KEY, value)


def initialize(db):
    """Bring the tallies up to the newest journal entry. Safe to run on every start."""
    value = _load(db)
    _catch_up(db, value, tracking.newest_entry(db) + 1)
    _save(db, value)


def record(db, eid, kind):
    """Count entry ``eid`` inside the transaction that writes it."""
    if kind not in TYPES:
        return
    value = _load(db)
    if eid <= value['through']:
        return
    # The new entry is already written, so catching up through it counts it too.
    _catch_up(db, value, eid + 1)
    _save(db, value)


def status(store):
    with store.reading() as db:
        value = _load(db)
        # Read only. A stopped adventure's page never writes, so count any new entries here.
        _catch_up(db, value, tracking.newest_entry(db) + 1)
    counts = value['counts']
    battles = counts['trainers_defeated'] + counts['trainer_losses']
    return {**counts, 'trainer_battles': battles,
            'trainer_win_rate': round(100 * counts['trainers_defeated'] / battles, 1) if battles else None,
            'complete_history': value['complete_history'], 'since': value['since']}
