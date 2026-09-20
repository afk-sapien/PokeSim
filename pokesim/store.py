"""SQLite event log + key/value run state + screenshot files."""
from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from .checkpoints import CheckpointStore

log = logging.getLogger(__name__)

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
  state TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.shots = self.dir / "shots"
        self.states = self.dir / "states"
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
        self.lock = threading.Lock()

    def _migrate(self):
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(events)")}
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
                    if ev.type == 'champion':
                        from .league_partners import record
                        record(self.db, snapshot, ev.title, eid)
                    shot = f"{eid}.png" if shot_png else None
                    state = f"event-{eid}.state" if state_bytes else None
                    for directory, name, data in (
                        (self.shots, shot, shot_png), (self.states, state, state_bytes)
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

    def counts(self) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT type, COUNT(*) n FROM events GROUP BY type").fetchall()
        return {r["type"]: r["n"] for r in rows}

    # --- kv ---
    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def set(self, k, v):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)", (k, json.dumps(v)))

    def trade_preferences(self):
        from .trade.preferences import read
        with self.lock:
            return read(self.db)

    def set_trade_preference(self, key, value):
        from .trade.preferences import PREFIX
        with self.lock, self.db:
            hold = self.db.execute("SELECT v FROM kv WHERE k='trade_hold'").fetchone()
            if hold and json.loads(hold[0]):
                raise ValueError('An exchange is in progress. Try again when it finishes.')
            previous = self.db.execute('SELECT v FROM kv WHERE k=?', (PREFIX + key,)).fetchone()
            locked = previous and json.loads(previous[0]).get('state') == 'locked'
            if locked and value['state'] not in ('locked', 'unlocked'):
                raise ValueError('This Pokémon is locked. Unlock it before changing its trade availability.')
            if value['state'] == 'unlocked':
                if not locked:
                    raise ValueError('This Pokémon is no longer locked. Refresh its details.')
                value = {**value, 'state': 'auto'}
            self.db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)',
                            (PREFIX + key, json.dumps(value)))

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
        return self.checkpoints.write_checkpoint(state, metadata, name)

    def checkpoint_metadata(self, path: Path) -> dict | None:
        return self.checkpoints.checkpoint_metadata(path)

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
