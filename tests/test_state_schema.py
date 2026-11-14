"""The adventure database's schema version: an older file migrates once, a newer one is refused."""
from contextlib import closing
import json
import re
import sqlite3
import zipfile

import pytest

from pokesim import activity_ledger
from pokesim.app import legacy_import
from pokesim.app.backup import file_checksum, restore_backup
from pokesim.app.errors import Conflict
from pokesim.state import kv, schema
from pokesim.store import Store

NAMES = {re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', statement).group(1) for statement in schema.TABLES}


def legacy(path):
    """A journal from before versions: events without detail or priorities, progress rows without the
    long goals and shiny receipts without dates. Every table it lacks comes from migration 1."""
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, '
                   "type TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', "
                   "notable INTEGER NOT NULL DEFAULT 1, map TEXT NOT NULL DEFAULT '', "
                   "playtime TEXT NOT NULL DEFAULT '', shot TEXT, state TEXT)")
        db.execute("INSERT INTO events(ts, type, title) VALUES (1, 'badge', 'Boulder Badge')")
        db.execute("INSERT INTO events(ts, type, title, notable) VALUES (2, 'map', 'Route 1', 0)")
        db.execute('CREATE TABLE progress (ts REAL NOT NULL, badges INTEGER NOT NULL, '
                   'owned INTEGER NOT NULL, seen INTEGER, league INTEGER NOT NULL)')
        db.execute('INSERT INTO progress VALUES (1, 1, 2, 3, 0)')
        db.execute('CREATE TABLE shiny_receipts (kind TEXT NOT NULL, fingerprint TEXT NOT NULL, '
                   'dex INTEGER NOT NULL, PRIMARY KEY(kind,fingerprint))')
    return path


def newer(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute(f'PRAGMA user_version = {schema.VERSION + 1}')
    return path


def tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def read_version(path):
    with closing(sqlite3.connect(path)) as db:
        return schema.version(db)


def test_a_database_from_before_versions_gains_every_table_once(tmp_path):
    path = legacy(tmp_path / 'pokesim.sqlite')
    with closing(schema.connect(path)) as db:
        assert schema.version(db) == schema.VERSION == 5
        assert NAMES | {'claims'} <= tables(db)
        assert db.execute('SELECT title, priority FROM events ORDER BY id').fetchall() == [
            ('Boulder Badge', 5), ('Route 1', 1)]
        assert db.execute('SELECT level100, perfect FROM progress').fetchall() == [(None, None)]
        assert 'ts' in schema._columns(db, 'shiny_receipts')
    # A file from before versions has no version for an older PokeSim to open, so nothing was kept.
    assert sorted(path.parent.iterdir()) == [path]
    with closing(schema.connect(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 2


def test_a_newer_database_is_refused_and_left_as_it_is(tmp_path):
    path = newer(tmp_path / 'pokesim.sqlite')
    for read_only in (False, True):
        with pytest.raises(Conflict, match=schema.NEWER):
            schema.connect(path, read_only=read_only)
    with pytest.raises(Conflict, match=schema.NEWER):
        schema.intact(path)
    with pytest.raises(Conflict, match=schema.NEWER):
        Store(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert schema.version(db) == schema.VERSION + 1
        assert tables(db) == set()


def test_a_read_only_store_reads_an_old_file_in_todays_shape_without_changing_it(tmp_path):
    path = legacy(tmp_path / 'pokesim.sqlite')
    (tmp_path / 'shots').mkdir()
    (tmp_path / 'states').mkdir()
    before = path.read_bytes()
    with closing(Store(tmp_path, read_only=True)) as store:
        assert schema.version(store.db) == schema.VERSION
        assert NAMES <= tables(store.db)
    assert path.read_bytes() == before
    assert read_version(path) == 0


def test_a_read_only_store_fills_the_rows_an_old_file_never_stored(tmp_path):
    # A stopped adventure last run by 0.4.x has no activity ledger row, and booting the cartridge for
    # its pages updates that row, so the copy gains it as a writable open would.
    path = legacy(tmp_path / 'pokesim.sqlite')
    (tmp_path / 'shots').mkdir()
    (tmp_path / 'states').mkdir()
    before = path.read_bytes()
    with closing(Store(tmp_path, read_only=True)) as store:
        assert kv.get(store.db, activity_ledger.KEY) == {'started_at': None, 'available': False}
    assert path.read_bytes() == before


def test_a_failed_migration_leaves_the_database_at_its_old_version(tmp_path, monkeypatch):
    path = legacy(tmp_path / 'pokesim.sqlite')

    def broken(db):
        db.execute('CREATE TABLE half (x)')
        raise RuntimeError('migration failed partway')

    monkeypatch.setitem(schema.MIGRATIONS, 1, broken)
    with pytest.raises(RuntimeError, match='partway'):
        schema.connect(path)
    with closing(sqlite3.connect(path)) as db:
        assert schema.version(db) == 0
        assert 'half' not in tables(db)


def test_a_versioned_database_is_kept_whole_before_a_later_migration(tmp_path, monkeypatch):
    path = tmp_path / 'pokesim.sqlite'
    schema.connect(path).close()
    later = schema.VERSION + 1
    monkeypatch.setattr(schema, 'VERSION', later)
    monkeypatch.setitem(schema.MIGRATIONS, later, lambda db: db.execute('CREATE TABLE later (x)'))
    with closing(schema.connect(path)) as db:
        assert schema.version(db) == later
        assert 'later' in tables(db)
    kept = sorted(tmp_path.glob(f'pokesim.sqlite.pre-schema-{later}-*'))
    assert len(kept) == 1 and not list(tmp_path.glob('*.partial'))
    with closing(sqlite3.connect(kept[0])) as db:
        assert schema.version(db) == later - 1
        assert 'later' not in tables(db)
    # Once upgraded there is nothing more to keep.
    schema.connect(path).close()
    assert sorted(tmp_path.glob('pokesim.sqlite.pre-schema-*')) == kept


def test_a_legacy_peer_from_a_newer_pokesim_is_refused(tmp_path):
    path = newer(tmp_path / 'pokesim.sqlite')
    with pytest.raises(Conflict, match=schema.NEWER):
        with legacy_import._database(path):
            pass


def archive(tmp_path, adventure):
    """A whole-library backup holding one adventure database."""
    staging = tmp_path / 'staging'
    (staging / 'adventures' / 'a1').mkdir(parents=True)
    with closing(sqlite3.connect(staging / 'app.sqlite')) as db:
        db.execute('CREATE TABLE settings (k TEXT PRIMARY KEY, v TEXT)')
    adventure(staging / 'adventures' / 'a1' / 'pokesim.sqlite')
    files = {path.relative_to(staging).as_posix(): file_checksum(path)
             for path in staging.rglob('*') if path.is_file()}
    target = tmp_path / 'backup.zip'
    with zipfile.ZipFile(target, 'w') as output:
        output.writestr('backup.json', json.dumps({'format': 1, 'files': files}))
        for name in files:
            output.write(staging / name, name)
    return target


def test_a_backup_restores_an_adventure_from_before_versions_unchanged(tmp_path):
    restored = restore_backup(archive(tmp_path, legacy), tmp_path / 'restored')
    # Its own PokeSim migrates it when it first opens the adventure.
    assert read_version(restored / 'adventures' / 'a1' / 'pokesim.sqlite') == 0


@pytest.mark.parametrize('adventure, message', [
    (newer, schema.NEWER),
    (lambda path: path.write_bytes(b'not a database' * 512), 'adventure a1 is damaged'),
])
def test_a_backup_with_a_newer_or_damaged_adventure_is_not_restored(tmp_path, adventure, message):
    destination = tmp_path / 'restored'
    with pytest.raises(Conflict, match=message):
        restore_backup(archive(tmp_path, adventure), destination)
    assert not destination.exists()
