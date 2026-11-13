"""Durable application identity, library and operation records."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import uuid

from ..checkpoints import CheckpointStore
from . import lifecycle
from .errors import Conflict, NotFound

log = logging.getLogger(__name__)

SCHEMA = 2
# The adventure fields `update` and `transition` change. The state changes only by transition.
UPDATABLE = frozenset({'name', 'settings', 'desired_state', 'generation', 'archived', 'error', 'summary',
                       'campaign_id', 'provenance'})
# Adventures from before accounts belong to this placeholder user until setup names the first
# admin, and so do adventures whose owner no longer exists.
LIBRARY_OWNER = '0' * 32
# The setting that holds each adventure's trading switches, read through trade_settings.
TRADE_SETTINGS = 'trade_auto'


def identifier():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_id(value):
    if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise Conflict('Invalid adventure or operation ID')
    return value


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Users being deleted, or deleted. Nothing new may belong to them.
        self.leaving = set()
        self.db = sqlite3.connect(self.root / 'app.sqlite', check_same_thread=False)
        try:
            # Library settings can hold an ntfy access token.
            (self.root / 'app.sqlite').chmod(0o600)
        except OSError:
            pass
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA:
            self.db.close()
            raise ValueError('This application needs a newer PokeSim version')
        new = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone() is None
        if version < SCHEMA and not new:
            self._keep_before_migration()
        self.db.execute('PRAGMA synchronous=FULL')
        with self.db:
            # sqlite3 commits a CREATE TABLE on its own, so the whole migration opens its own
            # transaction, and a start stopped partway leaves the database as it was.
            self.db.execute('BEGIN')
            self.db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS roms (id TEXT PRIMARY KEY, sha1 TEXT NOT NULL, version TEXT NOT NULL)')
            self.db.execute('''CREATE TABLE IF NOT EXISTS adventures (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL,
                rom_id TEXT NOT NULL, version TEXT NOT NULL, settings TEXT NOT NULL,
                desired_state TEXT NOT NULL, state TEXT NOT NULL, generation TEXT,
                archived INTEGER NOT NULL DEFAULT 0, error TEXT, summary TEXT NOT NULL DEFAULT '{}', provenance TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS interactions (
                id TEXT PRIMARY KEY, plan TEXT NOT NULL, decision TEXT, phase TEXT NOT NULL,
                result TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            # Offers one adventure makes to another. An accepted offer links to the manual trade it queued.
            self.db.execute('''CREATE TABLE IF NOT EXISTS trade_offers (
                id TEXT PRIMARY KEY, from_id TEXT NOT NULL, from_key TEXT NOT NULL,
                to_id TEXT NOT NULL, to_key TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
                manual_id TEXT, display TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            self.db.execute('CREATE INDEX IF NOT EXISTS trade_offers_from ON trade_offers (from_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS trade_offers_to ON trade_offers (to_id)')
            # The account that sent an offer, for its limits and its own history. Older offers have none.
            if 'sender_id' not in {row[1] for row in self.db.execute('PRAGMA table_info(trade_offers)')}:
                self.db.execute('ALTER TABLE trade_offers ADD COLUMN sender_id TEXT')
            columns = {row[1] for row in self.db.execute('PRAGMA table_info(adventures)')}
            if 'provenance' not in columns:
                self.db.execute("ALTER TABLE adventures ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'")
            if 'owner_id' not in columns:
                self.db.execute(f"ALTER TABLE adventures ADD COLUMN owner_id TEXT NOT NULL DEFAULT '{LIBRARY_OWNER}'")
            # The Library has one shelf that admins manage, so the per-user shelves of earlier
            # builds go. Only that table is dropped, and every ROM row and file stays.
            self.db.execute('DROP TABLE IF EXISTS rom_owners')
            self.db.execute(f'PRAGMA user_version={SCHEMA}')
        if self.setting('application_id') is None:
            self.set_setting('application_id', identifier())
        self._migrate_adventure_speeds()

    def _keep_before_migration(self):
        """Copy the Library database before a schema change, since the older PokeSim that made
        it cannot open it after. Restoring the copy is how to go back to that version."""
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        path = self.root / f'app.sqlite.pre-schema-{SCHEMA}-{stamp}'
        # The copy is written under a temporary name and renamed once whole, so the name the
        # rollback docs restore never holds a partial copy. mkstemp makes it private before
        # anything is written, since settings can hold an ntfy access token.
        descriptor, temporary = tempfile.mkstemp(prefix=f'{path.name}.', suffix='.partial', dir=self.root)
        os.close(descriptor)
        try:
            copy = sqlite3.connect(temporary)
            try:
                # The backup API reads through the write-ahead log, so the copy is one whole file.
                self.db.backup(copy)
            finally:
                copy.close()
            # Opened for writing, since Windows flushes only a handle that can write.
            with open(temporary, 'r+b') as written:
                os.fsync(written.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        if os.name != 'nt':
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        log.warning('Kept a copy of the Library database from before this upgrade at %s. '
                    'Restore it to go back to an older PokeSim.', path)

    def _migrate_adventure_speeds(self):
        with self.lock, self.db:
            if self.setting('per_adventure_speed_v1'):
                return
            # The old supervisor overrode every game, including stale per-game values.
            speed = self.setting('speed', 1)
            rows = list(self.db.execute('SELECT id, settings FROM adventures'))
            for row in rows:
                settings = {**json.loads(row['settings']), 'speed': speed}
                self.db.execute('UPDATE adventures SET settings=? WHERE id=?',
                                (json.dumps(settings), row['id']))
            self.db.execute("DELETE FROM settings WHERE key IN ('speed', 'max_running')")
            self.db.execute('INSERT INTO settings VALUES (?, ?)', ('per_adventure_speed_v1', 'true'))
        for row in rows:
            self.write_manifest(self.adventure(row['id']))

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(value)))

    @staticmethod
    def decode(row):
        if row is None:
            return None
        item = dict(row)
        for key in ('settings', 'summary', 'provenance'):
            item[key] = json.loads(item[key])
        from ..runtime.settings import without_retired
        item['settings'] = without_retired(item['settings'])
        item['archived'] = bool(item['archived'])
        item['url'] = f"/games/{item['id']}/"
        return item

    def adventure(self, adventure_id):
        validate_id(adventure_id)
        with self.lock:
            result = self.decode(self.db.execute('SELECT * FROM adventures WHERE id=?', (adventure_id,)).fetchone())
        if result is None:
            raise NotFound('Adventure not found')
        return result

    def adventures(self):
        with self.lock:
            return [self.decode(row) for row in self.db.execute('SELECT * FROM adventures ORDER BY created_at, id')]

    def roms(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM roms ORDER BY version, id')]

    def has_rom(self, rom_id):
        with self.lock:
            return self.db.execute('SELECT 1 FROM roms WHERE id=?', (rom_id,)).fetchone() is not None

    def add_rom(self, rom_id, sha1, version):
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO roms VALUES (?, ?, ?)', (rom_id, sha1, version))
        return {'id': rom_id, 'sha1': sha1, 'version': version}

    def remove_roms(self, rom_ids):
        with self.lock, self.db:
            self.db.executemany('DELETE FROM roms WHERE id=?', [(rom_id,) for rom_id in rom_ids])

    @staticmethod
    def scoped_request(request_id, owner):
        """Request ids come from browsers, so each user gets their own space of them."""
        validate_id(request_id)
        if owner == LIBRARY_OWNER:
            return request_id
        return hashlib.sha256(f'{validate_id(owner)}:{request_id}'.encode()).hexdigest()[:32]

    def create(self, name, rom_id, settings, request_id, *, owner=LIBRARY_OWNER):
        name = str(name).strip()
        if not name or len(name) > 120:
            raise Conflict('Choose an adventure name of 1 to 120 characters')
        request_id = self.scoped_request(request_id, owner)
        payload = dict(name=name, rom_id=rom_id, settings=settings)
        fingerprint = digest(payload)
        with self.lock, self.db:
            if owner in self.leaving:
                raise Conflict('This account is being deleted')
            previous = self.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != 'create' or previous['digest'] != fingerprint:
                    raise Conflict('This request ID already belongs to a different operation')
                return self.adventure(json.loads(previous['result'])['id'])
            rom = self.db.execute('SELECT * FROM roms WHERE id=?', (rom_id,)).fetchone()
            if rom is None:
                raise Conflict('Add a game cartridge in Settings before creating an adventure')
            from .validation import validate_generation_settings, validate_starter
            validate_starter(settings.get('starter', 'random'), rom['version'])
            validate_generation_settings(settings, rom['version'])
            aid = identifier()
            campaign = identifier()
            self.db.execute('''INSERT INTO adventures
                (id,campaign_id,name,rom_id,version,settings,desired_state,state,created_at,owner_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (aid, campaign, name, rom_id, rom['version'], json.dumps({'speed': 1, **settings}), 'stopped', 'stopped', time.time(),
                 validate_id(owner)))
            self.db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)',
                            (request_id, 'create', fingerprint, json.dumps({'id': aid})))
        result = self.adventure(aid)
        self.write_manifest(result)
        return result

    def rebind_owners(self, owner, known):
        """Give the placeholder's adventures, and those of users that no longer exist, to `owner`."""
        validate_id(owner)
        with self.lock, self.db:
            rows = [row['id'] for row in self.db.execute('SELECT id, owner_id FROM adventures')
                    if row['owner_id'] == LIBRARY_OWNER or row['owner_id'] not in known]
            self.db.executemany('UPDATE adventures SET owner_id=? WHERE id=?', [(owner, aid) for aid in rows])
        return rows

    def set_owner(self, aid, owner):
        """Ownership moves only here, by a transfer or when a user is deleted."""
        validate_id(owner)
        self.adventure(aid)
        with self.lock, self.db:
            if owner in self.leaving:
                raise Conflict('This account is being deleted')
            before = self.db.execute('SELECT owner_id FROM adventures WHERE id=?', (aid,)).fetchone()
            self.db.execute('UPDATE adventures SET owner_id=? WHERE id=?', (owner, aid))
            if before is not None and before[0] != owner:
                self._reset_trading(aid)
        result = self.adventure(aid)
        self.write_manifest(result)
        return result

    def _reset_trading(self, aid):
        """Inside a transaction: a new owner has not opted in to trading with other people, so
        the adventure's trading switches go back to their defaults."""
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (TRADE_SETTINGS,)).fetchone()
        settings = json.loads(row[0]) if row else {}
        if not isinstance(settings, dict) or not isinstance(settings.get(aid), dict):
            return
        # Other stored keys, such as an old wish list, stay as they were.
        settings[aid] = {key: value for key, value in settings[aid].items()
                         if key not in {'enabled', 'open_to_offers', 'across_owners'}}
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (TRADE_SETTINGS, json.dumps(settings)))

    def request_lifecycle(self, aid, action, request_id, *, owner=LIBRARY_OWNER):
        request_id = self.scoped_request(request_id, owner)
        self.adventure(aid)  # an unknown adventure raises KeyError here
        if action not in {'start', 'stop'}:
            raise ValueError('Unknown lifecycle action')
        fingerprint = digest({'adventure_id': aid, 'action': action})
        desired = 'running' if action == 'start' else 'stopped'
        with self.lock, self.db:
            previous = self.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != action or previous['digest'] != fingerprint:
                    raise Conflict('This request ID already belongs to another operation')
                return False
            self.db.execute('UPDATE adventures SET desired_state=? WHERE id=?', (desired, aid))
            self.db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)',
                            (request_id, action, fingerprint, json.dumps({'id': aid})))
        return True

    def update(self, aid, **values):
        """Change an adventure's fields other than its state, which only `transition` changes."""
        if 'state' in values:
            raise ValueError('Change an adventure state with transition')
        if not values:
            raise ValueError('Unsupported registry update')
        return self._write(aid, values)

    def transition(self, aid, to, reason, **values):
        """Move an adventure to state `to` for `reason`, writing any other fields in `values` with
        it. A move the lifecycle does not allow is logged as an error and still written."""
        if 'state' in values:
            raise ValueError('Unsupported registry update')
        return self._write(aid, values, to, reason)

    def _write(self, aid, values, to=None, reason=None):
        if not set(values) <= UPDATABLE:
            raise ValueError('Unsupported registry update')
        self.adventure(aid)
        encoded = {key: json.dumps(value) if key in {'settings', 'summary', 'provenance'} else value for key, value in values.items()}
        with self.lock, self.db:
            if to is not None:
                self.move(aid, to, reason)
            if encoded:
                self.db.execute('UPDATE adventures SET ' + ','.join(f'{key}=?' for key in encoded) + ' WHERE id=?',
                                (*encoded.values(), aid))
        result = self.adventure(aid)
        self.write_manifest(result)
        return result

    def move(self, aid, to, reason):
        """Record a state move and log it. Call it with `lock` held inside a write, so the check and
        the change are one step. `transition` calls it, and so does a write that must change other
        tables in the same step."""
        if to not in lifecycle.STATES:
            raise ValueError(f'Unknown adventure state {to}')
        row = self.db.execute('SELECT state FROM adventures WHERE id=?', (aid,)).fetchone()
        if row is None:
            raise NotFound('Adventure not found')
        before = row['state']
        self.db.execute('UPDATE adventures SET state=? WHERE id=?', (to, aid))
        if before == to:
            return before
        if lifecycle.allowed(before, to):
            log.info('Adventure %s went from %s to %s: %s', aid, before, to, reason)
        else:
            log.error('Adventure %s went from %s to %s, a move the lifecycle does not allow: %s',
                      aid, before, to, reason)
        return before

    def write_manifest(self, adventure):
        root = self.root / 'adventures' / adventure['id']
        root.mkdir(parents=True, exist_ok=True)
        CheckpointStore.atomic_write(root / 'adventure.json', json.dumps(adventure, indent=2).encode())

    @staticmethod
    def _interaction(row):
        item = dict(row)
        item['plan'] = json.loads(item['plan'])
        item['result'] = json.loads(item['result']) if item['result'] else None
        return item

    def transaction(self, tid):
        with self.lock:
            row = self.db.execute('SELECT * FROM interactions WHERE id=?', (tid,)).fetchone()
        if not row:
            raise NotFound('Interaction not found')
        return self._interaction(row)

    def transactions(self, unresolved=False, *, adventure_id=None):
        with self.lock:
            query = 'SELECT * FROM interactions'
            conditions = []
            parameters = []
            if unresolved:
                conditions.append("phase NOT IN ('completed','aborted')")
            if adventure_id is not None:
                validate_id(adventure_id)
                conditions.append("EXISTS (SELECT 1 FROM json_each(interactions.plan, '$.participants') WHERE value = ?)")
                parameters.append(adventure_id)
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            # One query, decoded outside the lock: the trading pages read this on every refresh.
            rows = self.db.execute(query + ' ORDER BY created_at DESC LIMIT 1000', parameters).fetchall()
        return [self._interaction(row) for row in rows]

    def completed_trade_visits(self):
        """Individuals previously held by each campaign, including both trade sides."""
        query = '''SELECT participant.value,
                   json_extract(interactions.plan, '$.campaign_ids.' || participant.value),
                   json_extract(interactions.plan, '$.left_key')
                   FROM interactions, json_each(interactions.plan, '$.participants') AS participant
                   WHERE phase = 'completed' AND decision = 'COMMIT'
                   UNION
                   SELECT participant.value,
                   json_extract(interactions.plan, '$.campaign_ids.' || participant.value),
                   json_extract(interactions.plan, '$.right_key')
                   FROM interactions, json_each(interactions.plan, '$.participants') AS participant
                   WHERE phase = 'completed' AND decision = 'COMMIT' '''
        with self.lock:
            return {tuple(row) for row in self.db.execute(query) if row[2]}

    def create_transaction(self, tid, plan):
        validate_id(tid)
        with self.lock, self.db:
            row = self.db.execute('SELECT plan FROM interactions WHERE id=?', (tid,)).fetchone()
            if row:
                if digest(json.loads(row[0])) != digest(plan):
                    raise Conflict('Interaction ID already has another plan')
            else:
                now = time.time()
                self.db.execute('INSERT INTO interactions VALUES (?, ?, NULL, ?, NULL, NULL, ?, ?)',
                                (tid, json.dumps(plan), 'preparing', now, now))
        return self.transaction(tid)

    def update_transaction(self, tid, **values):
        if not set(values) <= {'decision', 'phase', 'result', 'error'}:
            raise ValueError('Invalid interaction update')
        with self.lock, self.db:
            previous = self.transaction(tid)
            if previous['decision'] and 'decision' in values and values['decision'] != previous['decision']:
                raise Conflict('A durable interaction decision cannot change')
            encoded = {key: json.dumps(value) if key == 'result' else value for key, value in values.items()}
            encoded['updated_at'] = time.time()
            self.db.execute('UPDATE interactions SET ' + ','.join(f'{key}=?' for key in encoded) + ' WHERE id=?',
                            (*encoded.values(), tid))
        return self.transaction(tid)

    @staticmethod
    def _decode_offer(row):
        if row is None:
            return None
        item = dict(row)
        item['display'] = json.loads(item['display'])
        return item

    def trade_offer(self, oid):
        validate_id(oid)
        with self.lock:
            row = self.db.execute('SELECT * FROM trade_offers WHERE id=?', (oid,)).fetchone()
        if row is None:
            raise NotFound('Trade offer not found')
        return self._decode_offer(row)

    def trade_offers(self, adventure_id=None, statuses=None):
        """Offers from or to one adventure, or every offer, newest first."""
        query, parameters, conditions = 'SELECT * FROM trade_offers', [], []
        if adventure_id is not None:
            validate_id(adventure_id)
            conditions.append('(from_id=? OR to_id=?)')
            parameters += [adventure_id, adventure_id]
        if statuses is not None:
            statuses = list(statuses)
            conditions.append('status IN (' + ','.join('?' * len(statuses)) + ')')
            parameters += statuses
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        with self.lock:
            rows = self.db.execute(query + ' ORDER BY created_at DESC, id LIMIT 1000', parameters).fetchall()
        return [self._decode_offer(row) for row in rows]

    def create_trade_offer(self, offer):
        now = time.time()
        with self.lock, self.db:
            self.db.execute('''INSERT INTO trade_offers (id, from_id, from_key, to_id, to_key, status, reason,
                manual_id, display, created_at, updated_at, sender_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (offer['id'], offer['from_id'], offer['from_key'], offer['to_id'], offer['to_key'] or '',
                             'pending', None, None, json.dumps(offer.get('display') or {}), now, now,
                             offer.get('sender_id')))
        return self.trade_offer(offer['id'])

    def update_trade_offer(self, oid, expect=None, **values):
        """Change an offer, only while its status is still one of `expect` when given."""
        if not values or not set(values) <= {'status', 'reason', 'manual_id', 'to_key', 'display'}:
            raise ValueError('Unsupported trade offer update')
        if 'display' in values:
            values['display'] = json.dumps(values['display'] or {})
        with self.lock, self.db:
            current = self.trade_offer(oid)
            if expect is not None and current['status'] not in expect:
                return None
            self.db.execute('UPDATE trade_offers SET ' + ','.join(f'{key}=?' for key in values) + ', updated_at=? WHERE id=?',
                            (*values.values(), time.time(), oid))
        return self.trade_offer(oid)

    def prune_trade_offers(self, keep):
        """Forget each sender's oldest finished offers beyond their newest `keep`."""
        with self.lock, self.db:
            self.db.execute('''DELETE FROM trade_offers WHERE id IN (SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY COALESCE(sender_id, '') ORDER BY updated_at DESC) AS place
                FROM trade_offers WHERE status NOT IN ('pending','accepted')) WHERE place > ?)''', (keep,))

    def count_trade_offers(self, *, sender_id=None, to_ids=None, statuses=None, since=None):
        """How many offers one account sent, or a set of adventures received."""
        conditions, parameters = [], []
        if sender_id is not None:
            conditions.append('sender_id=?')
            parameters.append(sender_id)
        if to_ids is not None:
            to_ids = list(to_ids) or ['']
            conditions.append('to_id IN (' + ','.join('?' * len(to_ids)) + ')')
            parameters += to_ids
        if statuses is not None:
            statuses = list(statuses)
            conditions.append('status IN (' + ','.join('?' * len(statuses)) + ')')
            parameters += statuses
        if since is not None:
            conditions.append('created_at >= ?')
            parameters.append(since)
        query = 'SELECT COUNT(*) FROM trade_offers' + (' WHERE ' + ' AND '.join(conditions) if conditions else '')
        with self.lock:
            return self.db.execute(query, parameters).fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()
