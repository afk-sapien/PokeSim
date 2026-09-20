"""Durable application identity, library and operation records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from ..checkpoints import CheckpointStore

SCHEMA = 1


def identifier():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_id(value):
    if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Invalid adventure or operation ID')
    return value


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
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
        self.db.execute('PRAGMA synchronous=FULL')
        with self.db:
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
            columns = {row[1] for row in self.db.execute('PRAGMA table_info(adventures)')}
            if 'provenance' not in columns:
                self.db.execute("ALTER TABLE adventures ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'")
            self.db.execute(f'PRAGMA user_version={SCHEMA}')
        if self.setting('application_id') is None:
            self.set_setting('application_id', identifier())
            self.set_setting('max_running', 2)

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
        item['archived'] = bool(item['archived'])
        item['url'] = f"/games/{item['id']}/"
        return item

    def adventure(self, adventure_id):
        validate_id(adventure_id)
        with self.lock:
            result = self.decode(self.db.execute('SELECT * FROM adventures WHERE id=?', (adventure_id,)).fetchone())
        if result is None:
            raise KeyError('Adventure not found')
        return result

    def adventures(self):
        with self.lock:
            return [self.decode(row) for row in self.db.execute('SELECT * FROM adventures ORDER BY created_at, id')]

    def roms(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM roms ORDER BY version, id')]

    def add_rom(self, rom_id, sha1, version):
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO roms VALUES (?, ?, ?)', (rom_id, sha1, version))
        return {'id': rom_id, 'sha1': sha1, 'version': version}

    def create(self, name, rom_id, settings, request_id):
        name = str(name).strip()
        if not name or len(name) > 120:
            raise ValueError('Choose an adventure name of 1 to 120 characters')
        validate_id(request_id)
        payload = dict(name=name, rom_id=rom_id, settings=settings)
        fingerprint = digest(payload)
        with self.lock, self.db:
            previous = self.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != 'create' or previous['digest'] != fingerprint:
                    raise ValueError('This request ID already belongs to a different operation')
                return self.adventure(json.loads(previous['result'])['id'])
            rom = self.db.execute('SELECT * FROM roms WHERE id=?', (rom_id,)).fetchone()
            if rom is None:
                raise ValueError('Add a verified ROM before creating an adventure')
            aid = identifier()
            campaign = identifier()
            self.db.execute('''INSERT INTO adventures
                (id,campaign_id,name,rom_id,version,settings,desired_state,state,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (aid, campaign, name, rom_id, rom['version'], json.dumps(settings), 'stopped', 'stopped', time.time()))
            self.db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)',
                            (request_id, 'create', fingerprint, json.dumps({'id': aid})))
        result = self.adventure(aid)
        self.write_manifest(result)
        return result

    def request_lifecycle(self, aid, action, request_id):
        validate_id(request_id)
        adventure = self.adventure(aid)
        if action not in {'start', 'stop'}:
            raise ValueError('Unknown lifecycle action')
        fingerprint = digest({'adventure_id': aid, 'action': action})
        desired = 'running' if action == 'start' else 'stopped'
        with self.lock, self.db:
            previous = self.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != action or previous['digest'] != fingerprint:
                    raise ValueError('This request ID already belongs to another operation')
                return False
            self.db.execute('UPDATE adventures SET desired_state=? WHERE id=?', (desired, aid))
            self.db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)',
                            (request_id, action, fingerprint, json.dumps({'id': aid})))
        return True

    def update(self, aid, **values):
        allowed = {'name', 'settings', 'desired_state', 'state', 'generation', 'archived', 'error', 'summary', 'campaign_id', 'provenance'}
        if not values or not set(values) <= allowed:
            raise ValueError('Unsupported registry update')
        self.adventure(aid)
        encoded = {key: json.dumps(value) if key in {'settings', 'summary', 'provenance'} else value for key, value in values.items()}
        with self.lock, self.db:
            self.db.execute('UPDATE adventures SET ' + ','.join(f'{key}=?' for key in encoded) + ' WHERE id=?',
                            (*encoded.values(), aid))
        result = self.adventure(aid)
        self.write_manifest(result)
        return result

    def write_manifest(self, adventure):
        root = self.root / 'adventures' / adventure['id']
        root.mkdir(parents=True, exist_ok=True)
        CheckpointStore.atomic_write(root / 'adventure.json', json.dumps(adventure, indent=2).encode())

    def transaction(self, tid):
        with self.lock:
            row = self.db.execute('SELECT * FROM interactions WHERE id=?', (tid,)).fetchone()
        if not row:
            raise KeyError('Interaction not found')
        item = dict(row)
        item['plan'] = json.loads(item['plan'])
        item['result'] = json.loads(item['result']) if item['result'] else None
        return item

    def transactions(self, unresolved=False, *, adventure_id=None):
        with self.lock:
            query = 'SELECT id FROM interactions'
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
            ids = [row[0] for row in self.db.execute(query + ' ORDER BY created_at DESC LIMIT 1000', parameters)]
        return [self.transaction(tid) for tid in ids]

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
                    raise ValueError('Interaction ID already has another plan')
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
                raise ValueError('A durable interaction decision cannot change')
            encoded = {key: json.dumps(value) if key == 'result' else value for key, value in values.items()}
            encoded['updated_at'] = time.time()
            self.db.execute('UPDATE interactions SET ' + ','.join(f'{key}=?' for key in encoded) + ' WHERE id=?',
                            (*encoded.values(), tid))
        return self.transaction(tid)

    def close(self):
        with self.lock:
            self.db.close()
