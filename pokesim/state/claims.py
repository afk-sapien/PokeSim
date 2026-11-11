"""The claims ledger: one row per gift a source earned (docs/design/goal-system.md section 7).

A row is ``open`` until its gift is delivered or declined. ``frame`` is the PlayClock frame when it
was earned, delivered or declined, whichever came last, so a reload to an earlier save sends a gift
delivered after that save back to open.
A row with no frame, such as one moved from the League ledger before rows, never reopens.
``seed`` is the seed of the gift a delivery wrote, so a reopened claim writes the same Pokémon and
a delivery can find it already held.

Each function runs on the handle ``Store.transaction()``, ``Store.reading()`` or ``Store.durable()``
yields.
"""
import time

OPEN, DELIVERED, DECLINED = 'open', 'delivered', 'declined'
STATES = (OPEN, DELIVERED, DECLINED)

TABLE = """CREATE TABLE IF NOT EXISTS claims (
  source TEXT NOT NULL,
  key TEXT NOT NULL,
  state TEXT NOT NULL,
  frame INTEGER,
  ts REAL NOT NULL,
  species INTEGER,
  seed TEXT,
  reasons TEXT NOT NULL DEFAULT '',
  reward_id TEXT,
  PRIMARY KEY (source, key)
)"""
INDEX = 'CREATE INDEX IF NOT EXISTS claims_state ON claims(source, state)'
FIELDS = ('source', 'key', 'state', 'frame', 'ts', 'species', 'seed', 'reasons', 'reward_id')


def put(db, source, key, state, *, frame=None, species=None, seed=None, reasons='', reward_id=None):
    """Write a claim's whole row, new or changed. A changed claim keeps its place in the order."""
    if state not in STATES:
        raise ValueError(f'Unknown claim state {state}')
    db.execute('INSERT INTO claims(source, key, state, frame, ts, species, seed, reasons, reward_id) '
               'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source, key) DO UPDATE SET state=excluded.state, '
               'frame=excluded.frame, ts=excluded.ts, species=excluded.species, seed=excluded.seed, '
               'reasons=excluded.reasons, reward_id=excluded.reward_id',
               (source, key, state, frame, time.time(), species, seed, reasons, reward_id))


def get(db, source, key):
    """One claim as a dict, or None."""
    row = db.execute(f'SELECT {", ".join(FIELDS)} FROM claims WHERE source=? AND key=?', (source, key)).fetchone()
    return dict(zip(FIELDS, row)) if row else None


def rows(db, source, state=None):
    """A source's claims as dicts, oldest first, or only those in ``state``."""
    query = f'SELECT {", ".join(FIELDS)} FROM claims WHERE source=?'
    values = [source]
    if state is not None:
        query += ' AND state=?'
        values.append(state)
    return [dict(zip(FIELDS, row)) for row in db.execute(query + ' ORDER BY rowid', values)]


def counts(db, source):
    """How many of a source's claims are in each state."""
    found = dict(db.execute('SELECT state, COUNT(*) FROM claims WHERE source=? GROUP BY state', (source,)).fetchall())
    return {state: found.get(state, 0) for state in STATES}


def reopen_after(db, frame, *, keep=None):
    """Send every claim delivered after PlayClock ``frame`` back to open, except the one delivered with
    reward id ``keep``. Returns the reopened claims' (source, key) pairs."""
    reopened = db.execute(
        'SELECT source, key FROM claims WHERE state=? AND frame IS NOT NULL AND frame > ? '
        'AND (reward_id IS NULL OR reward_id IS NOT ?)', (DELIVERED, frame, keep)).fetchall()
    reopened = [(source, key) for source, key in reopened]
    for source, key in reopened:
        db.execute("UPDATE claims SET state=?, ts=?, reasons='Reloaded an earlier save', reward_id=NULL "
                   'WHERE source=? AND key=?', (OPEN, time.time(), source, key))
    return reopened
