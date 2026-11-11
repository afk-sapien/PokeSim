"""SQLite event log + key/value run state + screenshot files."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
import logging
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from . import adventure_counters, progress, progress_events, stall_truth
from .checkpoints import CheckpointStore, compress_state
from .state import domains, schema

log = logging.getLogger(__name__)

# Seconds between tries to move older trade settings while the collection cannot be read in full.
TRADE_KEY_RETRY_SECONDS = 30
# A notable entry at this priority or above is a milestone: badges, the League, new Pokédex entries,
# evolutions, hatches, key items, the Elite Four and similar. It keeps its screenshot and save forever.
MILESTONE_PRIORITY = 4
ATTACHMENT_ROUND = 500

class Store:
    def __init__(self, data_dir: Path, *, read_only=False):
        self.dir = Path(data_dir)
        self.shots = self.dir / "shots"
        self.states = self.dir / "states"
        # A stopped adventure's pages read its files without changing them. They work on a copy
        # of the database in memory, so what the emulator records while it restores a save,
        # and the setup every tracker runs, never reaches the disk.
        self.read_only = read_only
        # The running emulator's PlayClock frames, which dates progress rows. None where none runs.
        self.clock = None
        # The running emulator's goal for progress rows and encounter counters. None where none runs.
        self.goal_watch = None
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
            source = schema.connect(database, read_only=True)
            try:
                self.db = sqlite3.connect(':memory:', check_same_thread=False)
                source.backup(self.db)
            finally:
                source.close()
            # An older file is read in today's shape, which the copy gains here and the file never does.
            schema.migrate(self.db)
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
        self.db = schema.connect(self.dir / "pokesim.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # A restart committed its new game but stopped before the old game's autosaves were gone.
        # Finish it before anything restores, so the new game starts and the old one never resumes.
        if self.db.execute('SELECT 1 FROM kv WHERE k=?', (domains.RESTART_PENDING,)).fetchone():
            self._finish_restart()
        # The tables come from the schema version. These fill what an older journal never stored,
        # and each is safe to run on every start.
        with self.db:
            progress.backfill(self.db)
            from .activity_ledger import initialize as initialize_activity
            initialize_activity(self.db)
            from .trade_statistics import initialize as initialize_trade_statistics
            initialize_trade_statistics(self.db)
            adventure_counters.initialize(self.db)

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
                    progress_events.entry(self, self.db, ev)
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
            cached = (self._cache_reads and k in domains.CACHED and getattr(self._read_local, 'depth', 0)
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

    @contextmanager
    def transaction(self):
        """The store's lock and one transaction, for repository calls that commit together.

        The functions in ``pokesim.state`` take the handle it yields. An exception rolls it back.
        """
        with self.lock, self.db:
            yield self.db

    @contextmanager
    def reading(self):
        """The store's lock, for repository reads that must agree with each other."""
        with self.lock:
            yield self.db

    @contextmanager
    def durable(self):
        """One write transaction that is on the disk when it ends.

        It starts with ``BEGIN IMMEDIATE``, so no other writer can come between its reads and its
        writes, and commits under ``synchronous=FULL``. The connection's own setting comes back after.
        An exception rolls the whole transaction back.
        """
        with self.lock:
            previous = self.db.execute('PRAGMA synchronous').fetchone()[0]
            self.db.execute('PRAGMA synchronous=FULL')
            try:
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    yield self.db
                except BaseException:
                    self.db.rollback()
                    raise
                self.db.commit()
            finally:
                self.db.execute(f'PRAGMA synchronous={int(previous)}')

    def restart(self, generation, values):
        """Start the adventure's next game, all of it or none of it.

        One durable transaction empties every domain a restart of this generation resets and every
        domain a reload rewinds, and writes ``values`` in their place: the fresh rows the trackers
        and the emulator start the new game with. A reset row with no value in ``values`` is deleted,
        as a new adventure never had it. The same transaction sets ``restart-pending-v1``. After the
        commit the old game's autosaves go and the marker clears. A crash before the commit leaves
        the old game whole, and one after it starts the new game whole when the store opens again.
        """
        if self.read_only:
            raise PermissionError('A stopped adventure is read only')
        reset = domains.restarted(generation)
        unknown = set(values) - {domain.key for domain in reset if domain.kind == domains.KEY}
        if unknown:
            raise ValueError(f'A restart does not reset {sorted(unknown)}')
        with self.durable() as db:
            for domain in reset:
                if domain.kind == domains.TABLE:
                    db.execute(f'DELETE FROM {domain.key}')
                elif domain.kind == domains.PREFIX:
                    db.execute('DELETE FROM kv WHERE substr(k, 1, ?) = ?', (len(domain.key), domain.key))
                elif domain.key in values:
                    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (domain.key, json.dumps(values[domain.key])))
                else:
                    db.execute('DELETE FROM kv WHERE k=?', (domain.key,))
            db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (domains.RESTART_PENDING, json.dumps(True)))
        self._finish_restart()

    def _finish_restart(self):
        """Drop the old game's autosaves, then clear the marker the restart left for this step."""
        self.checkpoints.drop_autosaves()
        with self.lock, self.db:
            self.db.execute('DELETE FROM kv WHERE k=?', (domains.RESTART_PENDING,))

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

    def league_marks(self, generation=1):
        """The marks of every League reward delivered so far (rewards.marks)."""
        from . import rewards
        with self.lock:
            return rewards.marks(self.db, generation)

    def release_requests(self):
        """The owner's pending PC releases: trade identity to 'release', or pcvalue.LAST_COPY when the
        confirm named a last copy."""
        return dict(self.get('release_requests', {}) or {})

    def _change_release_requests(self, change):
        with self.lock, self.db:
            row = self.db.execute("SELECT v FROM kv WHERE k='release_requests'").fetchone()
            requests = dict(json.loads(row["v"]) if row else {})
            changed = change(dict(requests))
            if changed != requests:
                self.db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES ('release_requests',?)", (json.dumps(changed),))
            return changed

    def set_release_request(self, key, value):
        """Add a release request, or drop it when ``value`` is empty."""
        return self._change_release_requests(
            lambda requests: {**requests, key: value} if value else {k: v for k, v in requests.items() if k != key})

    def prune_release_requests(self, held):
        """Drop requests for Pokémon no longer held, once their release is done."""
        return self._change_release_requests(
            lambda requests: {key: value for key, value in requests.items() if key in held})

    def pc_favor(self):
        """The Favor shiny or Favor DVs setting from the PC tab, or None."""
        value = self.get('pc_favor')
        return value if value in ('shiny', 'dvs') else None

    def attach(self, policy, generation=1):
        """Give a policy the stored trade settings, the release inputs pcvalue reads, its boss losses and
        the progress monitor's tables (runtime.supervision.Tables)."""
        from .planning.losses import Losses
        from .runtime.supervision import Tables
        policy.losses = Losses(self)
        policy.monitor_tables = Tables(self)
        policy.trade_preferences = self.trade_preferences
        policy.trade_partners = self.trade_partners
        policy.league_marks = lambda: self.league_marks(generation)
        policy.release_requests = self.release_requests
        policy.prune_release_requests = self.prune_release_requests
        policy.pc_favor = self.pc_favor

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

    def write_checkpoint(self, state: bytes, metadata: dict, name: str | None = None, compress=False) -> Path:
        if self.read_only:
            raise PermissionError('A stopped adventure is read only')
        return self.checkpoints.write_checkpoint(state, metadata, name, compress=compress)

    def checkpoint_metadata(self, path: Path) -> dict | None:
        return self.checkpoints.checkpoint_metadata(path)

    def keep_as(self, path: Path, name: str):
        self.checkpoints.keep_as(path, name)

    def held(self, path: Path, replaced: str):
        return self.checkpoints.held(path, replaced)

    def write_stall_bundle(self, state: bytes, metadata: dict, report: dict, png: bytes | None,
                           before: Path | None, keep: int, segments=()) -> Path:
        """Keep a stall bundle, and a row for it that stays when the folder is pruned."""
        folder = self.checkpoints.write_stall_bundle(state, metadata, report, png, before, keep, segments)
        stall_truth.bundle(self, folder, report)
        return folder

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

    def prune_attachments(self, keep: int) -> int:
        """Keep the screenshot and save of only the newest ``keep`` routine entries, and return how many lost theirs.

        Milestones keep theirs forever and every entry keeps its text. The oldest go first. Files go
        before the row forgets them, so an interrupted pass leaves a row naming a missing file, which
        the journal already treats as having none, and never a file that no row names.

        This runs inside the adventure's own process, which holds its runtime lock. Backups, restores
        and deletions take the app's maintenance guard and stop the adventure before touching its
        files, so they never overlap. ``self.lock`` keeps a new entry from landing mid pass.
        """
        if keep <= 0:
            return 0
        removed = 0
        while True:
            with self.lock:
                routine = "(shot IS NOT NULL OR state IS NOT NULL) AND NOT (notable=1 AND priority>=?)"
                total = self.db.execute(f"SELECT COUNT(*) FROM events WHERE {routine}",
                                        (MILESTONE_PRIORITY,)).fetchone()[0]
                if total <= keep:
                    return removed
                # Rounds of a few hundred keep a first pass over a long adventure from blocking new entries.
                rows = self.db.execute(f"SELECT id, shot, state FROM events WHERE {routine} ORDER BY id LIMIT ?",
                                       (MILESTONE_PRIORITY, min(total - keep, ATTACHMENT_ROUND))).fetchall()
                cleared = []
                for row in rows:
                    names = [(self.shots, row["shot"]), (self.states, row["state"])]
                    if row["state"]:
                        names.append((self.states, str(Path(row["state"]).with_suffix(".json"))))
                    try:
                        for directory, name in names:
                            if name and Path(name).name == name:
                                (directory / name).unlink(missing_ok=True)
                    except OSError:
                        log.exception("Cannot remove the attachments of event %d", row["id"])
                        continue
                    cleared.append((row["id"],))
                with self.db:
                    self.db.executemany("UPDATE events SET shot=NULL, state=NULL WHERE id=?", cleared)
                removed += len(cleared)
                if len(cleared) < len(rows):
                    return removed

    def prune_reward_results(self, min_age: float = 3600) -> int:
        """Remove the saves of custom rewards and purchases that are finished, and return how many went.

        Each one writes an uncompressed 167 KB ``result.state`` that only crash recovery of the pending
        reward reads, and it used to be kept forever. The pending reward's folder and any folder newer
        than ``min_age`` seconds, which may be one being staged, are left alone.
        """
        root = self.dir / "custom-rewards"
        if not root.is_dir():
            return 0
        pending = self.get(domains.PENDING_REWARD) or {}
        keep = pending.get("id") if pending.get("phase") != "complete" else None
        cutoff = time.time() - min_age
        removed = 0
        for folder in root.iterdir():
            try:
                if folder.name == keep or not folder.is_dir() or folder.stat().st_mtime > cutoff:
                    continue
                shutil.rmtree(folder)
                removed += 1
            except OSError:
                log.exception("Cannot remove the finished custom reward %s", folder.name)
        return removed

    def close(self):
        with self.lock:
            self.db.close()
