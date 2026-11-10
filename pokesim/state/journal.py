"""The adventure journal, the events table, and the progress and stall truth rows that label it.

Each function runs inside its caller's transaction, on the handle ``Store.transaction()``,
``Store.reading()`` or ``Store.durable()`` yields, so an entry commits with the ledger change it
tells of. The journal's readers and the loop guard decide what an entry means. This module holds how
it is stored. See docs/design/adventure-state-store.md, slices R1 and R3.
"""


def _marks(kinds):
    return ','.join('?' * len(kinds))


# --- entries ---
def add(db, ts, kind, title, body, notable, priority, place, playtime='', detail=None):
    """Write one journal entry and return its id. ``detail`` is JSON text or None."""
    return db.execute('INSERT INTO events(ts,type,title,body,notable,priority,map,playtime,detail) '
                      'VALUES (?,?,?,?,?,?,?,?,?)',
                      (ts, kind, title, body, notable, priority, place, playtime, detail)).lastrowid


def champions(db):
    """(id, title, state, body) of every Champion entry, oldest first."""
    return db.execute("SELECT id,title,state,body FROM events WHERE type='champion' ORDER BY id").fetchall()


# --- the loop guard's scan ---
def marked(db, kinds):
    """(newest id whose type is in ``kinds`` other than a release, newest id of any of them).
    Each is None when the journal holds no such entry."""
    kinds = tuple(kinds)
    return tuple(db.execute(f"SELECT MAX(CASE WHEN type != 'release' THEN id END), MAX(id) FROM events "
                            f'WHERE type IN ({_marks(kinds)})', kinds).fetchone())


def marked_after(db, after, kinds):
    """(id, type, title) of the entries after id ``after`` whose type is in ``kinds``, oldest first."""
    kinds = tuple(kinds)
    return db.execute(f'SELECT id, type, title FROM events WHERE id > ? AND type IN ({_marks(kinds)}) ORDER BY id',
                      (after, *kinds)).fetchall()


def repeats(db, first, last, kind, title):
    """Whether an entry from id ``first`` to ``last`` has this type and title."""
    return db.execute('SELECT 1 FROM events WHERE id BETWEEN ? AND ? AND type = ? AND title = ? LIMIT 1',
                      (first, last, kind, title)).fetchone() is not None


def turnover(db, after, limit):
    """(type, title) of the newest ``limit`` receive and release entries after id ``after``, newest first."""
    return db.execute("SELECT type, title FROM events WHERE id > ? AND type IN ('obtain', 'release') "
                      'ORDER BY id DESC LIMIT ?', (after, limit)).fetchall()


# --- progress events ---
def add_progress(db, frame, ts, kind, goal, tier, species, identity, score, net):
    db.execute('INSERT INTO progress_events(frame, ts, kind, goal, tier, species, identity, score, net) '
               'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (frame, ts, kind, goal, tier, species, identity, score, net))


# --- stall truth ---
def add_stall_truth(db, frame, ts, kind, source, detail_json):
    db.execute('INSERT INTO stall_truth(frame, ts, kind, source, detail_json) VALUES (?, ?, ?, ?, ?)',
               (frame, ts, kind, source, detail_json))


def stall_truth(db, kind=None):
    """(id, frame, ts, kind, source, detail_json) of every row, or of one kind, oldest first."""
    sql = 'SELECT id, frame, ts, kind, source, detail_json FROM stall_truth'
    query = db.execute(sql + ' WHERE kind=? ORDER BY id', (kind,)) if kind else db.execute(sql + ' ORDER BY id')
    return query.fetchall()
