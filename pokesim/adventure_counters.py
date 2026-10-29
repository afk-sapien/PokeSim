"""Lifetime tallies of journal moments that outlive journal pruning, for both generations.

Faints, blackouts, trainer wins, evolutions and releases are journal entries, and old entries
can be pruned. Each one is also counted here, in the transaction that writes it. An adventure
recorded before these tallies starts from the entries its journal still holds.
"""
import json

KEY = 'adventure-counters-v1'
TYPES = {'faint': 'faints', 'blackout': 'blackouts', 'trainer': 'trainers_defeated',
         'evolve': 'evolutions', 'release': 'releases'}
NAMES = (*TYPES.values(), 'trainer_losses')
# A wild blackout names the wild foe in both generations. The journal has no other battle detail.
WILD = ' fighting a '


def _load(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    if row:
        value = json.loads(row[0])
        value['counts'] = {**dict.fromkeys(NAMES, 0), **value.get('counts', {})}
        return value
    first, since = db.execute('SELECT MIN(id), MIN(ts) FROM events').fetchone()
    table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
    issued = table and db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
    # Ids only grow, so a journal that no longer starts at entry 1 has been pruned.
    complete = first == 1 or first is None and not (issued and issued[0])
    return {'counts': dict.fromkeys(NAMES, 0), 'through': 0, 'complete_history': complete,
            'since': None if complete else since}


def _catch_up(db, value, until):
    """Count the entries after the last one counted, up to but not including ``until``.

    Entries written by an older version, or by a stopped adventure's backfill, are counted
    here exactly once, since ``through`` only moves forward.
    """
    marks = ','.join('?' * len(TYPES))
    rows = db.execute(f'SELECT type, body FROM events WHERE id > ? AND id < ? AND type IN ({marks})',
                      (value['through'], until, *TYPES))
    for kind, body in rows:
        value['counts'][TYPES[kind]] += 1
        if kind == 'blackout' and WILD not in (body or ''):
            # Both generations write the wild foe into the entry when they black out in a wild
            # battle, read from the battle mode at that moment. Any other blackout is a trainer loss.
            value['counts']['trainer_losses'] += 1
    value['through'] = max(value['through'], until - 1)


def _save(db, value):
    db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))


def initialize(db):
    """Bring the tallies up to the newest journal entry. Safe to run on every start."""
    value = _load(db)
    newest = db.execute('SELECT COALESCE(MAX(id), 0) FROM events').fetchone()[0]
    _catch_up(db, value, newest + 1)
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
    with store.lock:
        value = _load(store.db)
        newest = store.db.execute('SELECT COALESCE(MAX(id), 0) FROM events').fetchone()[0]
        # Read only. A stopped adventure's page never writes, so count any new entries here.
        _catch_up(store.db, value, newest + 1)
    counts = value['counts']
    battles = counts['trainers_defeated'] + counts['trainer_losses']
    return {**counts, 'trainer_battles': battles,
            'trainer_win_rate': round(100 * counts['trainers_defeated'] / battles, 1) if battles else None,
            'complete_history': value['complete_history'], 'since': value['since']}
