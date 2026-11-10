"""The tables behind the catch, shiny, statistics, tally and record trackers of both generations.

Each function runs inside its caller's transaction, on the handle ``Store.transaction()`` or
``Store.reading()`` yields, so a tracker's changes commit together. The trackers decide what to
count. This module holds how it is stored. See docs/design/adventure-state-store.md, slice R2.
"""
import json

# The receipt table of each generation's shiny ledger.
SHINY_RECEIPTS = {1: 'shiny_receipts', 2: 'gen2_shiny_receipts'}
# The progress columns an adventure record can be dated from.
PROGRESS_COLUMNS = frozenset({'badges', 'league', 'owned', 'level100', 'perfect'})
PROGRESS = 'SELECT ts, league, owned, level100 FROM progress'
# The headline numbers of a progress row, in column order (pokesim/progress.py).
PROGRESS_FIELDS = ('badges', 'owned', 'seen', 'league', 'level100', 'perfect')
_FIELDS = ', '.join(PROGRESS_FIELDS)
# Past this many rows, the progress history comes back thinned to about this many.
SHOWN_PROGRESS = 600
# A committed custom gift's receipt is keyed by its journal entry.
GIFT = "c.fingerprint LIKE 'gift-event:%'"
GIFT_ENTRY = 'CAST(SUBSTR(c.fingerprint, 12) AS INTEGER)'


# --- captures ---
def add_capture(db, fingerprint, dex, now):
    """Keep one capture receipt. Returns whether it is new, so a capture played again counts once."""
    return bool(db.execute('INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
                           (fingerprint, dex, now)).rowcount)


def has_capture_receipts(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_receipts'").fetchone() is not None


def undated_gifts(db):
    """Whether a gift receipt's journal entry is gone, so the gift's date is unknown."""
    return db.execute(f'SELECT 1 FROM capture_receipts c WHERE {GIFT} '
                      f'AND NOT EXISTS (SELECT 1 FROM events e WHERE e.id = {GIFT_ENTRY}) LIMIT 1').fetchone() is not None


def captures_between(db, since, until):
    """Receipts dated from ``since`` to ``until``. A gift carries its journal entry's date, since a
    gift recovered from an older journal was written later."""
    return db.execute(f'SELECT COUNT(*) FROM capture_receipts c LEFT JOIN events e ON {GIFT} AND e.id = {GIFT_ENTRY} '
                      f'WHERE CASE WHEN {GIFT} THEN e.ts ELSE c.recorded_at END BETWEEN ? AND ?',
                      (since, until)).fetchone()[0]


def obtained(db):
    """(id, title) of every ``obtain`` journal entry."""
    return db.execute("SELECT id, title FROM events WHERE type='obtain'").fetchall()


# --- shinies ---
def add_shiny(db, generation, kind, fingerprint, dex, now):
    """Keep one shiny receipt in the generation's table. Returns whether it is new."""
    return bool(db.execute(f'INSERT OR IGNORE INTO {SHINY_RECEIPTS[generation]}(kind, fingerprint, dex, ts) '
                           'VALUES (?,?,?,?)', (kind, fingerprint, dex, now)).rowcount)


def shiny_receipts(db, generation, limit):
    """(kind, dex, ts) of the newest shiny receipts, newest first. Receipts from before dates were
    kept come last."""
    return db.execute(f'SELECT kind, dex, ts FROM {SHINY_RECEIPTS[generation]} '
                      'ORDER BY ts IS NOT NULL DESC, ts DESC, rowid DESC LIMIT ?', (limit,)).fetchall()


# --- statistics ---
def marathons(db, title):
    """Journal entries of type ``marathon`` titled ``title``."""
    return db.execute("SELECT COUNT(*) FROM events WHERE type='marathon' AND title=?", (title,)).fetchone()[0]


def add_history(db, now, current):
    """Keep ``current`` as the statistics of the hour ``now`` falls in, over that hour's earlier row."""
    db.execute('INSERT OR REPLACE INTO statistics_history VALUES (?, ?, ?)', (int(now // 3600), now, json.dumps(current)))


def thin_history(db, before, width):
    """Of the history rows older than ``before``, keep only the newest in each ``width`` seconds."""
    db.execute('DELETE FROM statistics_history WHERE ts < ? AND bucket NOT IN ('
               'SELECT MAX(bucket) FROM statistics_history GROUP BY CAST(ts / ? AS INTEGER))', (before, width))


def history(db, limit):
    """About ``limit`` history rows spread over the whole span, the first and the newest among them.
    The choice runs in SQL, so an old adventure never sends an unbounded history to the browser."""
    bounds = db.execute('SELECT MIN(ts), MAX(ts) FROM statistics_history').fetchone()
    if bounds[0] is None:
        return []
    width = max(1, (bounds[1] - bounds[0]) / (limit - 2))
    rows = db.execute('SELECT ts, data FROM statistics_history WHERE bucket IN ('
                      'SELECT MAX(bucket) FROM statistics_history GROUP BY CAST((ts - ?) / ? AS INTEGER)'
                      ' UNION SELECT MIN(bucket) FROM statistics_history) ORDER BY ts', (bounds[0], width))
    return [{'ts': row[0], **json.loads(row[1])} for row in rows]


def latest_progress(db):
    """(ts, league, owned, level100) of the newest progress row, or None."""
    return db.execute(PROGRESS + ' ORDER BY rowid DESC LIMIT 1').fetchone()


def progress_from(db, cutoff):
    """The first progress row at or after ``cutoff``, or None."""
    return db.execute(PROGRESS + ' WHERE ts >= ? ORDER BY rowid LIMIT 1', (cutoff,)).fetchone()


def progress_until(db, cutoff):
    """The last progress row at or before ``cutoff``, or None."""
    return db.execute(PROGRESS + ' WHERE ts <= ? ORDER BY rowid DESC LIMIT 1', (cutoff,)).fetchone()


# --- progress history ---
def last_progress(db):
    """The PROGRESS_FIELDS of the newest progress row as a tuple, or None."""
    row = db.execute(f'SELECT {_FIELDS} FROM progress ORDER BY rowid DESC LIMIT 1').fetchone()
    return tuple(row) if row else None


def add_progress_row(db, ts, numbers):
    """Write one progress row. ``numbers`` holds the PROGRESS_FIELDS in order."""
    db.execute(f'INSERT INTO progress(ts, {_FIELDS}) VALUES (?,?,?,?,?,?,?)', (ts, *numbers))


def has_progress(db):
    return db.execute('SELECT 1 FROM progress LIMIT 1').fetchone() is not None


def backfill_progress(db, rows):
    """Write (ts, badges, owned, seen, league) rows rebuilt from the journal."""
    db.executemany('INSERT INTO progress(ts, badges, owned, seen, league) VALUES (?,?,?,?,?)', rows)


def progress_history(db):
    """(ts, *PROGRESS_FIELDS) of the progress rows, oldest first.

    Past SHOWN_PROGRESS rows it keeps the first row and the newest of each of about that many even spans.
    """
    count, first, last = db.execute('SELECT COUNT(*), MIN(rowid), MAX(rowid) FROM progress').fetchone()
    if count > SHOWN_PROGRESS:
        span = SHOWN_PROGRESS - 2
        return db.execute(
            f'SELECT ts, {_FIELDS} FROM progress WHERE rowid IN ('
            'SELECT MAX(rowid) FROM progress GROUP BY CAST((rowid - ?) / ? AS INTEGER) '
            'UNION SELECT MIN(rowid) FROM progress) ORDER BY rowid', (first, (last - first + span) // span)).fetchall()
    return db.execute(f'SELECT ts, {_FIELDS} FROM progress ORDER BY rowid').fetchall()


def activity_totals(db):
    """(wild battles, catches) the activity ledger counted over every species."""
    return tuple(db.execute("SELECT COALESCE(SUM(CASE WHEN kind='wild' THEN total END), 0), "
                            "COALESCE(SUM(CASE WHEN kind='caught' THEN total END), 0) FROM activity_counts").fetchone())


# --- activity ledger ---
def add_activity_receipt(db, kind, fingerprint):
    """Keep one action receipt. Returns whether it is new, so an action played again counts once."""
    return bool(db.execute('INSERT OR IGNORE INTO activity_receipts VALUES (?,?)', (kind, fingerprint)).rowcount)


def count_activity(db, kind, subject, amount=1):
    db.execute('INSERT INTO activity_counts VALUES (?,?,?) '
               'ON CONFLICT(kind,subject) DO UPDATE SET total=total+excluded.total',
               (kind, subject, amount))


def activity_counts(db):
    """{(kind, subject): total} over every count."""
    return {(row[0], row[1]): row[2] for row in db.execute('SELECT * FROM activity_counts')}


def forget_caught(db):
    db.execute("DELETE FROM activity_counts WHERE kind='caught'")


def receipt_counts(db):
    """(``caught`` or ``gift``, dex, receipts) for each species in the capture receipts."""
    return db.execute("SELECT CASE WHEN fingerprint LIKE 'gift-event:%' THEN 'gift' ELSE 'caught' END, "
                      'dex, COUNT(*) FROM capture_receipts GROUP BY 1,2').fetchall()


# --- records ---
def first_progress(db, column, threshold):
    """When ``column`` of the progress first reached ``threshold``, or None."""
    if column not in PROGRESS_COLUMNS:
        raise ValueError(f'progress has no column {column!r}')
    row = db.execute(f'SELECT ts FROM progress WHERE {column} >= ? ORDER BY rowid LIMIT 1', (threshold,)).fetchone()
    return row[0] if row else None


def playtime_at(db, ts):
    """The cartridge playtime of the first journal entry written at ``ts``, or None."""
    row = db.execute('SELECT playtime FROM events WHERE ts=? ORDER BY id LIMIT 1', (ts,)).fetchone()
    return row[0] if row else None


# --- journal tallies ---
def journal_start(db):
    """(id, ts) of the oldest journal entry left, both None for an empty journal."""
    return tuple(db.execute('SELECT MIN(id), MIN(ts) FROM events').fetchone())


def issued(db):
    """The last journal id SQLite issued, which pruning never lowers, or None before the first."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone():
        return None
    row = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
    return row[0] if row else None


def newest_entry(db):
    """The newest journal id, 0 for an empty journal."""
    return db.execute('SELECT COALESCE(MAX(id), 0) FROM events').fetchone()[0]


def entries(db, after, until, types):
    """(type, body) of the journal entries after id ``after`` and before id ``until`` whose type is in ``types``."""
    types = tuple(types)
    marks = ','.join('?' * len(types))
    return db.execute(f'SELECT type, body FROM events WHERE id > ? AND id < ? AND type IN ({marks})',
                      (after, until, *types)).fetchall()
