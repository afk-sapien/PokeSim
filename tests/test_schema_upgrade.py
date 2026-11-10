"""A Library that 0.6.x left on schema 1 opens here open as before, with every row kept."""
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import LIBRARY_OWNER, SCHEMA, TRADE_SETTINGS

# The tables as schema 1 made them, copied from the Registry of 0.6.x. They stay as written here
# when the Registry changes, so this test always opens a real Library from before accounts.
SCHEMA_1 = [
    'CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    'CREATE TABLE roms (id TEXT PRIMARY KEY, sha1 TEXT NOT NULL, version TEXT NOT NULL)',
    '''CREATE TABLE adventures (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL,
        rom_id TEXT NOT NULL, version TEXT NOT NULL, settings TEXT NOT NULL,
        desired_state TEXT NOT NULL, state TEXT NOT NULL, generation TEXT,
        archived INTEGER NOT NULL DEFAULT 0, error TEXT, summary TEXT NOT NULL DEFAULT '{}', provenance TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL)''',
    '''CREATE TABLE operations (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL)''',
    '''CREATE TABLE interactions (
        id TEXT PRIMARY KEY, plan TEXT NOT NULL, decision TEXT, phase TEXT NOT NULL,
        result TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)''',
    '''CREATE TABLE trade_offers (
        id TEXT PRIMARY KEY, from_id TEXT NOT NULL, from_key TEXT NOT NULL,
        to_id TEXT NOT NULL, to_key TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
        manual_id TEXT, display TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL, updated_at REAL NOT NULL)''',
    'CREATE INDEX trade_offers_from ON trade_offers (from_id)',
    'CREATE INDEX trade_offers_to ON trade_offers (to_id)',
]
RED, GOLD = 'a' * 32, 'b' * 32
ROWS = {
    'settings': [('application_id', json.dumps('c' * 32)), ('per_adventure_speed_v1', 'true'),
                 (TRADE_SETTINGS, json.dumps({GOLD: {'enabled': False}})), ('notifications', json.dumps({'enabled': True}))],
    'roms': [('red-rom', 'sha-red', 'red'), ('gold-rom', 'sha-gold', 'gold')],
    'adventures': [
        (RED, 'd' * 32, 'Kanto run', 'red-rom', 'red', json.dumps({'speed': 4, 'starter': 'random'}),
         'running', 'stopped', '7', 0, None, json.dumps({'badges': 3}), '{}', 1000.0),
        (GOLD, 'e' * 32, 'Old Gold', 'gold-rom', 'gold', json.dumps({'speed': 1}),
         'stopped', 'failed', None, 1, 'The worker exited', '{}', json.dumps({'imported': True}), 2000.0)],
    'operations': [('f' * 32, 'create', 'digest', json.dumps({'id': RED}))],
    'interactions': [('1' * 32, json.dumps({'participants': [RED, GOLD]}), 'COMMIT', 'completed',
                      json.dumps({'status': 'verified'}), None, 3000.0, 3100.0)],
    # An offer stored before 0.5.0. Nothing can answer it any more.
    'trade_offers': [('2' * 32, RED, '0', GOLD, 'party-1', 'pending', None, None, '{}', 4000.0, 4000.0)],
}


def rows(db, table):
    """The table's rows in its schema 1 columns, so columns added since leave them as they were."""
    blank = sqlite3.connect(':memory:')
    blank.executescript(';'.join(SCHEMA_1))
    columns = [row[1] for row in blank.execute(f'PRAGMA table_info({table})')]
    blank.close()
    return db.execute(f'SELECT {", ".join(columns)} FROM {table} ORDER BY 1').fetchall()


@pytest.fixture
def older(tmp_path, monkeypatch):
    for name in ('AUTH', 'POKESIM_ADMIN_USER', 'POKESIM_ADMIN_PASSWORD', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER'):
        monkeypatch.delenv(name, raising=False)
    with sqlite3.connect(tmp_path / 'app.sqlite') as db:
        for statement in SCHEMA_1:
            db.execute(statement)
        for table, values in ROWS.items():
            db.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(values[0]))})', values)
        db.execute('PRAGMA user_version=1')
    db.close()
    return tmp_path


def test_a_schema_1_library_opens_open_with_every_row_kept(older, monkeypatch):
    manager = Manager(older, 'http://testserver', auth='auto')
    monkeypatch.setattr(manager, 'start', lambda: None)
    try:
        assert manager.auth_mode == 'none' and not manager.needs_setup
        with TestClient(create_app(manager)) as client:
            # No login: the adventures list as before.
            listed = client.get('/api/v1/adventures').json()['adventures']
            assert {(row['id'], row['name']) for row in listed} >= {(RED, 'Kanto run')}
            assert client.get(f'/api/v1/adventures/{GOLD}').json()['name'] == 'Old Gold'
            assert client.get(f'/api/v1/interactions/trade-offers?adventure_id={RED}').status_code == 404
            # The stored offer holds no Pokémon back.
            assert (RED, '0') not in manager.coordinator.hand_picked_keys()
    finally:
        manager.close()
    with sqlite3.connect(older / 'app.sqlite') as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA
        for table, values in ROWS.items():
            kept = rows(db, table)
            if table == 'settings':
                # Opening a Library may add settings, and never changes one it had.
                assert set(values) <= set(kept)
            else:
                assert kept == sorted(values), table
        # Every adventure belongs to the Library until setup names an admin, and the offer has no sender.
        assert db.execute('SELECT DISTINCT owner_id FROM adventures').fetchall() == [(LIBRARY_OWNER,)]
        assert db.execute('SELECT sender_id FROM trade_offers').fetchall() == [(None,)]
        assert db.execute("SELECT 1 FROM settings WHERE key IN ('created_schema', 'accounts')").fetchall() == []
    db.close()
    # The copy from before the upgrade is schema 1 with the same rows, so 0.6.x can open it again.
    [copy] = older.glob(f'app.sqlite.pre-schema-{SCHEMA}-*')
    with sqlite3.connect(copy) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        for table, values in ROWS.items():
            assert rows(db, table) == sorted(values), table
        assert 'owner_id' not in {row[1] for row in db.execute('PRAGMA table_info(adventures)')}
    db.close()
    # A second start keeps it open and makes no second copy.
    again = Manager(older, auth='auto')
    assert again.auth_mode == 'none'
    again.close()
    assert len(list(older.glob('app.sqlite.pre-schema-*'))) == 1
