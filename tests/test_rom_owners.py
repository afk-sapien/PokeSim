"""Each person's cartridge shelf under accounts: one stored file, many owners, nothing shown across shelves."""
import threading

import pytest

from pokesim.app.registry import LIBRARY_OWNER, Registry, identifier

from test_accounts import library, people  # noqa: F401  (fixtures)
from test_cartridge_shelf import shelf, slot, synthetic


@pytest.fixture
def shelves(library, people, monkeypatch):  # noqa: F811
    """The people fixture's Library with made-up cartridges and no background work."""
    shelf(monkeypatch)
    monkeypatch.setattr(library.manager, 'background', lambda function, *args: None)
    return library


def upload(client, version='red'):
    response = client.post(f'/api/v1/cartridges?slot={version}', content=synthetic(version))
    assert response.status_code == 200, response.text
    return response.json()


def installed(client):
    return [item['version'] for item in client.get('/api/v1/cartridges').json()['slots'] if item['installed']]


def stored(manager, version='red'):
    rom = next(row for row in manager.registry.roms() if row['version'] == version)
    return manager.assets.root / 'roms' / rom['id'] / 'rom.gb'


def test_older_roms_go_to_the_library_owner_and_adventure_owners_keep_theirs(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('kept', 'sha1', 'red')
    registry.add_rom('played', 'sha1', 'blue')
    alice = identifier()
    registry.create('Blue', 'played', {}, identifier(), owner=alice)
    # A database from before shelves has no rom_owners table at all.
    with registry.lock, registry.db:
        registry.db.execute('DROP TABLE rom_owners')
    registry.db.close()
    reopened = Registry(tmp_path)
    assert [row['id'] for row in reopened.roms(LIBRARY_OWNER)] == ['played', 'kept']
    assert [row['id'] for row in reopened.roms(alice)] == ['played']
    # The migration runs once. A shelf emptied later stays empty.
    reopened.release_roms(['kept'], LIBRARY_OWNER)
    reopened.db.close()
    assert [row['id'] for row in Registry(tmp_path).roms(LIBRARY_OWNER)] == ['played']


def test_an_upgrade_stopped_after_making_the_shelves_still_fills_them(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('kept', 'sha1', 'red')
    registry.add_rom('played', 'sha1', 'blue')
    alice = identifier()
    registry.create('Blue', 'played', {}, identifier(), owner=alice)
    # The upgrade start made the empty table and stopped before filling it.
    with registry.lock, registry.db:
        registry.db.execute('DELETE FROM rom_owners')
    registry.db.close()
    reopened = Registry(tmp_path)
    assert [row['id'] for row in reopened.roms(LIBRARY_OWNER)] == ['played', 'kept']
    assert [row['id'] for row in reopened.roms(alice)] == ['played']


def test_the_shelf_migration_is_one_transaction(tmp_path, monkeypatch):
    registry = Registry(tmp_path)
    registry.add_rom('kept', 'sha1', 'red')
    with registry.lock, registry.db:
        registry.db.execute('DROP TABLE rom_owners')
    registry.db.close()
    import sqlite3
    real = sqlite3.connect

    class Stopping(sqlite3.Connection):
        # The start stops when it begins to fill the new shelves.
        def execute(self, sql, *rows):
            if sql.startswith('INSERT OR IGNORE INTO rom_owners'):
                raise RuntimeError('stopped')
            return super().execute(sql, *rows)

        def executemany(self, sql, rows):
            if sql.startswith('INSERT OR IGNORE INTO rom_owners'):
                raise RuntimeError('stopped')
            return super().executemany(sql, rows)
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **options: real(*args, factory=Stopping, **options))
    with pytest.raises(RuntimeError, match='stopped'):
        Registry(tmp_path)
    monkeypatch.setattr(sqlite3, 'connect', real)
    with sqlite3.connect(tmp_path / 'app.sqlite') as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='rom_owners'").fetchone() is None


def test_each_person_sees_only_their_own_shelf(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    upload(alice, 'blue')
    assert 'blue' in installed(alice) and 'blue' not in installed(bob)
    assets = bob.get('/api/v1/assets').json()
    assert all(row['version'] != 'blue' for row in assets['roms'])
    # Bob's slots list only Bob's adventures, never Alice's.
    names = {game['name'] for item in bob.get('/api/v1/cartridges').json()['slots'] for game in item['adventures']}
    assert names == {'Blue'}


def test_an_upload_answers_the_same_whether_or_not_someone_has_it(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    first = upload(alice, 'yellow')
    second = upload(bob, 'yellow')
    assert first['status'] == second['status'] == 'added'
    assert first['message'] == second['message']
    assert slot(second, 'yellow')['rom']['added_at'] >= slot(first, 'yellow')['rom']['added_at']
    assert upload(bob, 'yellow')['status'] == 'same'


def test_removing_ends_only_your_ownership_until_the_last_owner_goes(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    upload(alice, 'yellow')
    upload(bob, 'yellow')
    path = stored(shelves.manager, 'yellow')
    assert alice.delete('/api/v1/cartridges/yellow').status_code == 200
    assert 'yellow' not in installed(alice) and 'yellow' in installed(bob)
    assert path.exists()
    assert bob.delete('/api/v1/cartridges/yellow').status_code == 200
    assert not path.exists()
    assert all(row['version'] != 'yellow' for row in shelves.manager.registry.roms())


def test_an_upload_during_the_last_removal_keeps_the_file(shelves, people, monkeypatch):  # noqa: F811
    alice = shelves.login('alice')
    upload(alice, 'yellow')
    path = stored(shelves.manager, 'yellow')
    assets = shelves.manager.assets
    delete = assets.delete_rom_files
    bob = threading.Thread(target=assets.add_cartridge, args=(synthetic('yellow'), 'yellow'),
                           kwargs={'owner': people.bob['id']})

    def racing(rom_ids):
        # Bob uploads the same file after Alice's row is released and before the file goes.
        bob.start()
        bob.join(1)
        delete(rom_ids)

    monkeypatch.setattr(assets, 'delete_rom_files', racing)
    assert alice.delete('/api/v1/cartridges/yellow').status_code == 200
    bob.join(10)
    assert not bob.is_alive()
    assert shelves.manager.registry.owns_rom(path.parent.name, people.bob['id'])
    assert path.exists()


def test_your_own_adventure_blocks_removal_but_someone_elses_does_not(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    upload(alice, 'yellow')
    upload(bob, 'yellow')
    rom_id = slot(alice.get('/api/v1/cartridges').json(), 'yellow')['rom']['id']
    shelves.manager.registry.create('Pika', rom_id, {}, identifier(), owner=people.bob['id'])
    refused = bob.delete('/api/v1/cartridges/yellow')
    assert refused.status_code == 409 and 'Pika' in refused.json()['detail']
    removed = alice.delete('/api/v1/cartridges/yellow')
    assert removed.status_code == 200 and 'Pika' not in removed.text
    # Bob's game keeps its file even after Bob's shelf lets go, because an adventure still plays it.
    shelves.manager.registry.release_roms([rom_id], people.bob['id'])
    assert stored(shelves.manager, 'yellow').exists()


def test_members_who_can_create_add_cartridges_and_others_cannot(shelves, people):  # noqa: F811
    upload(shelves.login('alice'), 'red')
    shelves.manager.auth.update_user(people.bob['id'], can_create=False)
    bob = shelves.login('bob')
    assert bob.post('/api/v1/cartridges?slot=red', content=synthetic('red')).status_code == 403
    assert bob.delete('/api/v1/cartridges/red').status_code == 403


def test_an_adventure_needs_a_rom_from_your_own_shelf(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    rom_id = slot(upload(alice, 'blue'), 'blue')['rom']['id']
    unknown = bob.post('/api/v1/adventures', json={'name': 'Guess', 'rom_id': 'f' * 64, 'request_id': identifier()})
    foreign = bob.post('/api/v1/adventures', json={'name': 'Borrow', 'rom_id': rom_id, 'request_id': identifier()})
    assert unknown.status_code == foreign.status_code == 409
    assert unknown.json()['detail'] == foreign.json()['detail']
    made = alice.post('/api/v1/adventures', json={'name': 'Mine', 'rom_id': rom_id, 'request_id': identifier()})
    assert made.status_code == 200, made.text


def test_a_shared_adventure_hides_its_rom_from_people_without_it(shelves, people):  # noqa: F811
    registry = shelves.manager.registry
    registry.add_rom('alices-own', 'sha1', 'yellow', people.alice['id'])
    aid = registry.create('Pika', 'alices-own', {}, identifier(), owner=people.alice['id'])['id']
    shelves.manager.auth.grant(aid, people.bob['id'], 'viewer', people.alice['id'])
    bob = shelves.login('bob')
    assert 'rom_id' not in bob.get(f'/api/v1/adventures/{aid}').json()
    assert all('rom_id' not in game for game in bob.get('/api/v1/adventures').json()['adventures'] if game['id'] == aid)
    assert shelves.login('alice').get(f'/api/v1/adventures/{aid}').json()['rom_id'] == 'alices-own'


def test_an_imported_cartridge_is_the_importers_and_stays_gone_once_removed(shelves, people, tmp_path):  # noqa: F811
    """Imports filed the cartridge under the placeholder owner too. Removing it left that row, and the
    next start gave it to the first admin, so the removed cartridge came back on someone's shelf."""
    import sqlite3
    from contextlib import closing
    from pokesim.app.deletion import delete_adventure
    from pokesim.app.migration import import_directory
    manager = shelves.manager
    source = tmp_path / 'legacy'
    source.mkdir()
    with closing(sqlite3.connect(source / 'pokesim.sqlite')) as db, db:
        db.execute('CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)')
    (source / 'rom.gb').write_bytes(synthetic('yellow'))
    adventure = import_directory(manager, source, name='Old', stopped=True, owner=people.bob['id'])
    rom_id = adventure['rom_id']
    assert not manager.registry.owns_rom(rom_id, LIBRARY_OWNER)
    path = stored(manager, 'yellow')
    delete_adventure(manager, adventure['id'], 'Old')
    bob = shelves.login('bob')
    assert bob.delete('/api/v1/cartridges/yellow').status_code == 200
    assert not path.exists()
    assert all(row['version'] != 'yellow' for row in manager.registry.roms())
    # A restart hands the placeholder's shelf to the library owner, and there is nothing left to hand over.
    manager.bind_library_owner()
    assert 'yellow' not in installed(shelves.login('admin'))


def test_a_deleted_users_shelf_goes_with_them(shelves, people):  # noqa: F811
    alice, bob = shelves.login('alice'), shelves.login('bob')
    upload(alice, 'gold')
    upload(alice, 'silver')
    upload(bob, 'silver')
    gold, silver = stored(shelves.manager, 'gold'), stored(shelves.manager, 'silver')
    deleted = shelves.login('admin').request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                                              json={'adventures': {people.red: 'archive'}})
    assert deleted.status_code == 200, deleted.text
    assert not gold.exists() and silver.exists()
    assert 'silver' in installed(bob)
