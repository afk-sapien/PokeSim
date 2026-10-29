"""SQLite event log + key/value run state + screenshot files."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
import logging
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from . import adventure_counters, progress
from .checkpoints import CheckpointStore, compress_state

log = logging.getLogger(__name__)

# Seconds between tries to move older trade settings while the collection cannot be read in full.
TRADE_KEY_RETRY_SECONDS = 30

OBSERVATION_READ_KEYS = frozenset({
    'cartridge-steps-v1', 'mew-returns-v1', 'pokesim-mew-v1', 'legendary-returns-v1',
    'step-events-v1', 'pokedex-milestones-v1', 'shiny-statistics-v1',
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
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
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir: Path, *, read_only=False):
        self.dir = Path(data_dir)
        self.shots = self.dir / "shots"
        self.states = self.dir / "states"
        # A stopped adventure's pages read its files without changing them. They work on a copy
        # of the database in memory, so what the emulator records while it restores a save,
        # and the setup every tracker runs, never reaches the disk.
        self.read_only = read_only
        self.lock = threading.Lock()
        self._read_local = threading.local()
        self._read_cache = {}
        self._read_epoch = None
        self._cache_reads = os.environ.get('POKESIM_EXPERIMENT_READ_CACHE', '1') != '0'
        if read_only:
            database = self.dir / "pokesim.sqlite"
            if not all(path.exists() for path in (database, self.shots, self.states)):
                raise FileNotFoundError(f"{self.dir} has no adventure to show")
            self.checkpoints = CheckpointStore(self.states)
            source = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                self.db = sqlite3.connect(':memory:', check_same_thread=False)
                source.backup(self.db)
            finally:
                source.close()
            self.db.row_factory = sqlite3.Row
            return
        for d in (self.dir, self.shots, self.states):
            d.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryFile(dir=d):
                    pass
            except OSError as error:
                raise OSError(f"DATA_DIR must be writable, including {d}. Check volume ownership.") from error
        self.checkpoints = CheckpointStore(self.states)
        self.db = sqlite3.connect(self.dir / "pokesim.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        with self.db:
            self.db.executescript(progress.SCHEMA)
            progress.migrate(self.db)
            progress.backfill(self.db)
            from .statistics import initialize
            initialize(self.db)
            from .activity_ledger import initialize as initialize_activity
            initialize_activity(self.db)
            from .trade_statistics import initialize as initialize_trade_statistics
            initialize_trade_statistics(self.db)
            adventure_counters.initialize(self.db)

    def _migrate(self):
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(events)")}
        if "detail" not in cols:
            # older databases: entries written before events could carry structured detail keep
            # their text and simply have none of it.
            self.db.execute("ALTER TABLE events ADD COLUMN detail TEXT")
            self.db.commit()
        if "priority" not in cols:
            # older databases: add the column and backfill from the priorities events used to have
            self.db.execute("ALTER TABLE events ADD COLUMN priority INTEGER NOT NULL DEFAULT 3")
            self.db.execute("""UPDATE events SET priority = CASE
                WHEN notable = 0 THEN 1
                WHEN type IN ('badge', 'champion') THEN 5
                WHEN type IN ('catch', 'evolve', 'obtain', 'item') THEN 4
                WHEN type IN ('map', 'blackout', 'playtime') THEN 2
                ELSE 3 END""")
            self.db.commit()
        from .trade.preferences import migrate as migrate_trade_settings
        with self.db:
            migrate_trade_settings(self.db)

    # --- events ---
    def add_event(self, ev, snapshot, shot_png: bytes | None, state_bytes: bytes | None) -> int:
        ts = time.time()
        with self.lock:
            attachments = []
            try:
                with self.db:
                    cur = self.db.execute(
                        "INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (?,?,?,?,?,?,?,?)",
                        (ts, ev.type, ev.title, ev.body, int(ev.notable), int(ev.priority), snapshot.map_name,
                         "%d:%02d:%02d" % snapshot.playtime))
                    eid = cur.lastrowid
                    won = False
                    if ev.type == 'champion' and getattr(snapshot, 'generation', 1) == 2:
                        won = True
                    elif ev.type == 'champion':
                        from .league_partners import record
                        won = record(self.db, snapshot, ev.title, eid)
                    progress.record(self.db, ts, snapshot, won)
                    adventure_counters.record(self.db, eid, ev.type)
                    shot = f"{eid}.png" if shot_png else None
                    state = f"event-{eid}.state" if state_bytes else None
                    # A save state is about 167 KB of mostly zeroed RAM and compresses
                    # roughly thirteen to one. One is kept for every notable entry and they
                    # are only ever added to, so uncompressed they dominate an adventure's disk.
                    for directory, name, data in (
                        (self.shots, shot, shot_png),
                        (self.states, state, compress_state(state_bytes) if state_bytes else None),
                    ):
                        if name:
                            path = directory / name
                            attachments.append(path)
                            path.write_bytes(data)
                    self.db.execute("UPDATE events SET shot=?, state=? WHERE id=?", (shot, state, eid))
            except Exception:
                for path in attachments:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        log.exception("Cannot remove failed event attachment %s", path)
                raise
        return eid

    def replace_shot(self, eid: int, png: bytes):
        """Swap an entry's screenshot for a better one, taken moments later."""
        with self.lock:
            path = self.shots / f"{eid}.png"
            partial = path.with_suffix(".png.tmp")
            partial.write_bytes(png)
            partial.replace(path)
            with self.db:
                self.db.execute("UPDATE events SET shot=? WHERE id=?", (path.name, eid))

    def events(self, limit=50, notable_only=False, types=None, before=None, min_priority=None) -> list[dict]:
        q, args = "SELECT * FROM events", []
        conds = []
        if notable_only:
            conds.append("notable=1")
        if min_priority:
            conds.append("priority >= ?")
            args.append(int(min_priority))
        if types:
            conds.append("type IN (%s)" % ",".join("?" * len(types)))
            args += list(types)
        if before:
            conds.append("id < ?")
            args.append(before)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(q, args)]

    def event(self, eid: int) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        return dict(r) if r else None

    def progress(self) -> list[dict]:
        with self.lock:
            return progress.history(self.db)

    def counts(self) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT type, COUNT(*) n FROM events GROUP BY type").fetchall()
        return {r["type"]: r["n"] for r in rows}

    # --- kv ---
    @contextmanager
    def observation_reads(self):
        """Reuse committed observation facts within an observation phase.

        External commits are checked at each scope entry. Same-connection writes
        invalidate immediately. Trade controls and reads in transactions always
        query SQLite. Returned objects remain detached from the cache.
        """
        depth = getattr(self._read_local, 'depth', 0)
        if self._cache_reads:
            with self.lock:
                version = self.db.execute('PRAGMA data_version').fetchone()[0]
                epoch = (version, self.db.total_changes)
                if epoch != self._read_epoch:
                    self._read_cache.clear()
                    self._read_epoch = epoch
        self._read_local.depth = depth + 1
        try:
            yield
        finally:
            self._read_local.depth = depth

    def get(self, k, default=None):
        with self.lock:
            cached = (self._cache_reads and k in OBSERVATION_READ_KEYS and getattr(self._read_local, 'depth', 0)
                      and not self.db.in_transaction)
            if cached:
                epoch = (self._read_epoch[0], self.db.total_changes)
                if epoch != self._read_epoch:
                    self._read_cache.clear()
                    self._read_epoch = epoch
                if k in self._read_cache:
                    exists, value = self._read_cache[k]
                    return deepcopy(value) if exists else default
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
            if cached:
                value = json.loads(r["v"]) if r else None
                self._read_cache[k] = (r is not None, value)
                return deepcopy(value) if r else default
        return json.loads(r["v"]) if r else default

    def set(self, k, v):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)", (k, json.dumps(v)))

    def trade_preferences(self):
        from .trade.preferences import read
        with self.lock:
            return read(self.db)

    def trade_partners(self):
        """Trainer ids of linked adventures, whose Pokémon a release may let go like the player's own."""
        # A release decision asks on every step while storage is tight, so the set is read once and
        # kept until add_trade_partners changes it.
        cached = getattr(self, '_trade_partners', None)
        if cached is not None:
            return cached
        from .trade.partners import read
        with self.lock:
            self._trade_partners = read(self.db)
            return self._trade_partners

    def add_trade_partners(self, ids):
        from .trade.partners import add
        with self.lock, self.db:
            self._trade_partners = add(self.db, ids)
            return self._trade_partners

    def upgrade_trade_preferences(self, collection):
        """Move trade settings saved under older trainer and DV keys, once per process.

        ``collection`` returns every held Pokémon record. It is only called until the move
        has run, and at most once every TRADE_KEY_RETRY_SECONDS while it waits for a readable
        collection, so the emulators can offer it on every observed frame.
        """
        if getattr(self, '_trade_keys_current', False):
            return
        now = time.monotonic()
        if now < getattr(self, '_trade_keys_retry_at', 0):
            return
        from .trade.preferences import upgrade
        with self.lock, self.db:
            self._trade_keys_current = upgrade(self.db, collection())
        self._trade_keys_retry_at = now + TRADE_KEY_RETRY_SECONDS

    def set_trade_preference(self, key, value):
        from pokecore.identity import legacy
        from .trade.preferences import LEGACY, PREFIX, sync_legacy
        # One setting per Pokémon and no lock order: Can trade, Prefer to trade or Never trade.
        value = {**value, 'state': LEGACY.get(value['state'], value['state'])}
        with self.lock, self.db:
            hold = self.db.execute("SELECT v FROM kv WHERE k='trade_hold'").fetchone()
            if hold and json.loads(hold[0]):
                raise ValueError('An exchange is in progress. Try again when it finishes.')
            self.db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)',
                            (PREFIX + key, json.dumps(value)))
            if key != legacy(key):
                sync_legacy(self.db, legacy(key))

    def clear_trade_preferences(self):
        from .trade.preferences import PREFIX
        with self.lock, self.db:
            self.db.execute('DELETE FROM kv WHERE k LIKE ?', (PREFIX + '%',))

    # --- save states ---
    def autosave_path(self) -> Path:
        return self.checkpoints.autosave_path()

    def autosaves(self) -> list[Path]:
        return self.checkpoints.autosaves()

    def latest_state(self) -> Path | None:
        return self.checkpoints.latest_state()

    def prune_autosaves(self, keep: int):
        self.checkpoints.prune_autosaves(keep)

    def state_path(self, name: str) -> Path | None:
        return self.checkpoints.state_path(name)

    atomic_write = staticmethod(CheckpointStore.atomic_write)

    def write_checkpoint(self, state: bytes, metadata: dict, name: str | None = None) -> Path:
        if self.read_only:
            raise PermissionError('A stopped adventure is read only')
        return self.checkpoints.write_checkpoint(state, metadata, name)

    def checkpoint_metadata(self, path: Path) -> dict | None:
        return self.checkpoints.checkpoint_metadata(path)

    def keep_as(self, path: Path, name: str):
        self.checkpoints.keep_as(path, name)

    def write_stall_bundle(self, *args, **kwargs) -> Path:
        return self.checkpoints.write_stall_bundle(*args, **kwargs)

    def prune_events(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        with self.lock, self.db:
            rows = self.db.execute("SELECT id, shot, state FROM events WHERE ts < ?", (cutoff,)).fetchall()
            self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        for row in rows:
            for directory, name in ((self.shots, row["shot"]), (self.states, row["state"])):
                if name and Path(name).name == name:
                    (directory / name).unlink(missing_ok=True)
        return len(rows)

    def close(self):
        with self.lock:
            self.db.close()
