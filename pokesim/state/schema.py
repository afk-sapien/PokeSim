"""The schema version of an adventure's pokesim.sqlite, and the one way to open it.

``PRAGMA user_version`` holds the version. Each migration runs once, in order, in a transaction of
its own, and sets the version as it commits. A database from a newer PokeSim is refused before
anything reads it, as the registry refuses a newer app.sqlite. Before a migration past version 1
changes a database, a copy of it is kept beside it, since the older PokeSim cannot open it after.

Version 1 is the shape every database had before versions. A database from before them may lack
any part of it, so migration 1 creates what is missing and runs the column checks and the one-time
changes that each start used to run. Version 2 adds the claims ledger (pokesim/state/claims.py).
Version 3 moves the legendary returns' tickets into its rows (pokesim/return_claims.py), version 4
the event returns' tickets, and version 5 the Mew returns' delivered counts.
"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from ..app.errors import Conflict

NEWER = 'This adventure was saved by a newer PokeSim version'

TABLES = (
    """CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      body TEXT NOT NULL DEFAULT '',
      notable INTEGER NOT NULL DEFAULT 1,
      priority INTEGER NOT NULL DEFAULT 3,
      map TEXT NOT NULL DEFAULT '',
      playtime TEXT NOT NULL DEFAULT '',
      shot TEXT,
      state TEXT,
      detail TEXT
    )""",
    'CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)',
    """CREATE TABLE IF NOT EXISTS progress (
      ts REAL NOT NULL,
      badges INTEGER NOT NULL,
      owned INTEGER NOT NULL,
      seen INTEGER,
      league INTEGER NOT NULL,
      level100 INTEGER,
      perfect INTEGER
    )""",
    'CREATE TABLE IF NOT EXISTS statistics_history (bucket INTEGER PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS activity_counts ('
    'kind TEXT NOT NULL, subject INTEGER NOT NULL, total INTEGER NOT NULL, PRIMARY KEY(kind,subject))',
    'CREATE TABLE IF NOT EXISTS activity_receipts ('
    'kind TEXT NOT NULL, fingerprint BLOB NOT NULL, PRIMARY KEY(kind,fingerprint))',
    'CREATE TABLE IF NOT EXISTS pokemon_trade_receipts ('
    'id TEXT PRIMARY KEY, sent INTEGER NOT NULL, received INTEGER NOT NULL)',
    """CREATE TABLE IF NOT EXISTS progress_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      frame INTEGER,
      ts REAL NOT NULL,
      kind TEXT NOT NULL,
      goal TEXT NOT NULL DEFAULT '',
      tier TEXT NOT NULL DEFAULT '',
      species INTEGER,
      identity TEXT,
      score REAL,
      net INTEGER NOT NULL,
      rewound INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS encounter_counts (
      goal TEXT NOT NULL,
      hour INTEGER NOT NULL,
      encounters INTEGER NOT NULL DEFAULT 0,
      target INTEGER NOT NULL DEFAULT 0,
      met_rule INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (goal, hour)
    )""",
    """CREATE TABLE IF NOT EXISTS stall_truth (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      frame INTEGER,
      ts REAL NOT NULL,
      kind TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT '',
      detail_json TEXT NOT NULL DEFAULT '{}'
    )""",
    'CREATE TABLE IF NOT EXISTS capture_receipts '
    '(fingerprint TEXT PRIMARY KEY, dex INTEGER NOT NULL, recorded_at REAL NOT NULL)',
    'CREATE TABLE IF NOT EXISTS shiny_receipts '
    '(kind TEXT NOT NULL, fingerprint TEXT NOT NULL, dex INTEGER NOT NULL, PRIMARY KEY(kind,fingerprint))',
    'CREATE TABLE IF NOT EXISTS gen2_shiny_receipts '
    '(kind TEXT NOT NULL, fingerprint TEXT NOT NULL, dex INTEGER NOT NULL, PRIMARY KEY(kind,fingerprint))',
    # The legacy two-container trade's idempotency markers.
    'CREATE TABLE IF NOT EXISTS completed_trades (id TEXT PRIMARY KEY)',
    'CREATE TABLE IF NOT EXISTS completed_events (id TEXT PRIMARY KEY)',
)

INDEXES = (
    'CREATE INDEX IF NOT EXISTS events_ts ON events(ts)',
    "CREATE INDEX IF NOT EXISTS statistics_marathons ON events(id) "
    "WHERE type='marathon' AND title='Kanto Marathon finished!'",
    "CREATE INDEX IF NOT EXISTS statistics_johto_marathons ON events(id) "
    "WHERE type='marathon' AND title='Johto Marathon finished!'",
    'CREATE INDEX IF NOT EXISTS progress_events_kind ON progress_events(kind, species)',
)


def _columns(db, table):
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def _version_1(db):
    """The shape before versions, built on whatever part of it a database already has."""
    for statement in TABLES:
        db.execute(statement)
    events = _columns(db, 'events')
    if 'detail' not in events:
        # Entries written before events could carry structured detail keep their text and have none.
        db.execute('ALTER TABLE events ADD COLUMN detail TEXT')
    if 'priority' not in events:
        # Entries from before priorities get the ones their kinds used to have.
        db.execute('ALTER TABLE events ADD COLUMN priority INTEGER NOT NULL DEFAULT 3')
        db.execute("""UPDATE events SET priority = CASE
            WHEN notable = 0 THEN 1
            WHEN type IN ('badge', 'champion') THEN 5
            WHEN type IN ('catch', 'evolve', 'obtain', 'item') THEN 4
            WHEN type IN ('map', 'blackout', 'playtime') THEN 2
            ELSE 3 END""")
    # 0.4.0 progress rows predate the long goals and keep none, so those lines start at the upgrade.
    progress = _columns(db, 'progress')
    for name in ('level100', 'perfect'):
        if name not in progress:
            db.execute(f'ALTER TABLE progress ADD COLUMN {name} INTEGER')
    for table in ('shiny_receipts', 'gen2_shiny_receipts'):
        if 'ts' not in _columns(db, table):
            # Receipts from before dates were kept stay undated. Their dates are never guessed.
            db.execute(f'ALTER TABLE {table} ADD COLUMN ts REAL')
    for statement in INDEXES:
        db.execute(statement)
    from ..trade.preferences import migrate as migrate_trade_settings
    migrate_trade_settings(db)


def _version_2(db):
    """The claims ledger, with the League gifts the kv ledger counted moved into its rows."""
    from . import claims
    from ..rewards import adopt
    db.execute(claims.TABLE)
    db.execute(claims.INDEX)
    adopt(db)


def _version_3(db):
    """The legendary returns' tickets, both generations, moved from their kv values into claims rows."""
    from ..return_claims import adopt
    adopt(db)


def _version_4(db):
    """The event returns' tickets, both generations, moved into claims rows and walking clocks."""
    from ..return_claims import adopt_events
    adopt_events(db)


def _version_5(db):
    """The Mew returns' delivered counts, both generations, moved into claims rows."""
    from ..return_claims import adopt_mew
    adopt_mew(db)


MIGRATIONS = {1: _version_1, 2: _version_2, 3: _version_3, 4: _version_4, 5: _version_5}
VERSION = 5


def version(db):
    return db.execute('PRAGMA user_version').fetchone()[0]


def refuse_newer(db):
    """The database's version, or Conflict when a newer PokeSim wrote it."""
    current = version(db)
    if current > VERSION:
        raise Conflict(NEWER)
    return current


def _keep(db, path, current):
    """Copy the database beside itself before a migration, under the name the rollback restores."""
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    target = path.with_name(f'{path.name}.pre-schema-{VERSION}-{stamp}')
    # Written under a temporary name and renamed once whole, so the kept name never holds part of one.
    descriptor, temporary = tempfile.mkstemp(prefix=f'{target.name}.', suffix='.partial', dir=path.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(temporary)) as copy:
            db.backup(copy)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target


def migrate(db, path=None):
    """Bring a writable connection's database to VERSION. ``path`` names its file, which is copied
    first when the database already has a version older than this one. Returns the connection."""
    current = refuse_newer(db)
    if current == VERSION:
        return db
    if current and path is not None:
        _keep(db, Path(path), current)
    for number in range(current + 1, VERSION + 1):
        db.execute('BEGIN IMMEDIATE')
        try:
            # Another process may have migrated it while this one waited for the lock.
            if version(db) < number:
                MIGRATIONS[number](db)
                db.execute(f'PRAGMA user_version = {number}')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return db


def connect(path, *, read_only=False, timeout=5.0, **options):
    """Open an adventure's pokesim.sqlite, the only way to outside ``pokesim.store.Store``.

    A writable connection migrates the database first. A read-only one leaves the file as it is and
    reads an older version in its older shape. Either refuses a database from a newer PokeSim.
    """
    path = Path(path)
    if read_only:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=timeout, **options)
    else:
        db = sqlite3.connect(path, timeout=timeout, **options)
    try:
        if read_only:
            refuse_newer(db)
        else:
            migrate(db, path)
    except BaseException:
        db.close()
        raise
    return db


def intact(path):
    """Whether a copied adventure database opens and passes SQLite's integrity check. A database
    from a newer PokeSim is refused with Conflict. The file is not changed."""
    try:
        with closing(connect(path, read_only=True)) as db:
            return db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    except sqlite3.DatabaseError:
        return False


def copy(source, target, *, read_only=False):
    """Copy an adventure database whole into a new file, as a trade keeps the game before it.

    A read-only copy leaves the source as it is, so the new file keeps the source's version.
    """
    with closing(connect(source, read_only=read_only)) as db, closing(sqlite3.connect(target)) as destination:
        db.backup(destination)
