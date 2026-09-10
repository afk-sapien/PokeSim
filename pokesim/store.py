"""SQLite event log + key/value run state + screenshot files."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import sqlite3
import threading
import time
from pathlib import Path

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
            cur = self.db.execute(
                "INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (?,?,?,?,?,?,?,?)",
                (ts, ev.type, ev.title, ev.body, int(ev.notable), int(ev.priority), snapshot.map_name,
                 "%d:%02d:%02d" % snapshot.playtime))
            eid = cur.lastrowid
            shot = state = None
            if shot_png:
                shot = f"{eid}.png"
                (self.shots / shot).write_bytes(shot_png)
            if state_bytes:
                state = f"event-{eid}.state"
                (self.states / state).write_bytes(state_bytes)
            self.db.execute("UPDATE events SET shot=?, state=? WHERE id=?", (shot, state, eid))
            self.db.commit()
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
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)", (k, json.dumps(v)))
            self.db.commit()

    # --- save states ---
    def autosave_path(self) -> Path:
        return self.states / f"auto-v1-{time.time_ns()}.state"

    def autosaves(self) -> list[Path]:
        return sorted(self.states.glob("auto-*.state"), key=lambda p: p.stat().st_mtime_ns)

    def latest_state(self) -> Path | None:
        saves = self.autosaves()
        return saves[-1] if saves else None

    def prune_autosaves(self, keep: int):
        for p in self.autosaves()[:-keep] if keep > 0 else []:
            p.unlink(missing_ok=True)
            p.with_suffix(".json").unlink(missing_ok=True)

    def state_path(self, name: str) -> Path | None:
        if Path(name).name != name or "\\" in name or not name.endswith(".state"):
            return None
        p = self.states / name
        return p if p.is_file() else None

    @staticmethod
    def atomic_write(path: Path, data: bytes):
        """Publish a complete file only after its contents reach disk."""
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def write_checkpoint(self, state: bytes, metadata: dict) -> Path:
        path = self.autosave_path()
        manifest = dict(metadata, format=1, sha256=hashlib.sha256(state).hexdigest())
        self.atomic_write(path, state)
        self.atomic_write(path.with_suffix(".json"), json.dumps(manifest).encode())
        return path

    def checkpoint_metadata(self, path: Path) -> dict | None:
        manifest = path.with_suffix(".json")
        if not manifest.exists() and not path.name.startswith("auto-v1-"):
            return None
        data = json.loads(manifest.read_text())
        if data.get("format") != 1:
            raise ValueError("Unsupported checkpoint format")
        if data.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("Checkpoint checksum does not match")
        if not isinstance(data.get("policy_state"), dict) or not isinstance(data.get("run_memory"), dict):
            raise ValueError("Checkpoint memory is invalid")
        return data

    def prune_events(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        with self.lock:
            rows = self.db.execute("SELECT id, shot, state FROM events WHERE ts < ?", (cutoff,)).fetchall()
            self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            self.db.commit()
        for row in rows:
            for directory, name in ((self.shots, row["shot"]), (self.states, row["state"])):
                if name and Path(name).name == name:
                    (directory / name).unlink(missing_ok=True)
        return len(rows)

    def close(self):
        with self.lock:
            self.db.close()
