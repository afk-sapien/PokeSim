"""The Library shelf under accounts: admins add and remove cartridges, and everyone who may create plays them."""
import hashlib
import sqlite3
import threading

import pytest

from pokesim.app.registry import Registry, identifier

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


def test_the_per_user_shelves_of_earlier_builds_go_and_every_rom_stays(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('kept', 'sha1', 'red')
    registry.add_rom('played', 'sha1', 'blue')
    files = []
    for rom_id in ('kept', 'played'):
        path = tmp_path / 'assets' / 'roms' / rom_id / 'rom.gb'
        path.parent.mkdir(parents=True)
        path.write_bytes(rom_id.encode())
        files.append(path)
    alice = identifier()
    registry.create('Blue', 'played', {}, identifier(), owner=alice)
    # An earlier build kept who had each cartridge, and only Alice had the one her adventure plays.
    with registry.lock, registry.db:
        registry.db.execute('''CREATE TABLE rom_owners (
            rom_id TEXT NOT NULL, user_id TEXT NOT NULL, added_at REAL, PRIMARY KEY (rom_id, user_id))''')
        registry.db.execute('INSERT INTO rom_owners VALUES (?, ?, ?)', ('played', alice, 1.0))
    registry.db.close()
    reopened = Registry(tmp_path)
    assert [row['id'] for row in reopened.roms()] == ['played', 'kept']
    assert all(path.exists() for path in files)
    reopened.db.close()
    with sqlite3.connect(tmp_path / 'app.sqlite') as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='rom_owners'").fetchone() is None


def test_everyone_sees_every_library_cartridge_and_only_their_own_adventures(shelves, people):  # noqa: F811
    upload(shelves.login('admin'), 'blue')
    alice, bob = shelves.login('alice'), shelves.login('bob')
    assert 'blue' in installed(alice) and 'blue' in installed(bob)
    assert any(row['version'] == 'blue' for row in bob.get('/api/v1/assets').json()['roms'])
    # Bob's slots list only Bob's adventures, never Alice's.
    names = {game['name'] for item in bob.get('/api/v1/cartridges').json()['slots'] for game in item['adventures']}
    assert names == {'Blue'}
    names = {game['name'] for item in shelves.login('admin').get('/api/v1/cartridges').json()['slots']
             for game in item['adventures']}
    assert names == {'Red', 'Blue'}


def test_a_member_cannot_add_or_remove_a_cartridge(shelves, people):  # noqa: F811
    upload(shelves.login('admin'), 'yellow')
    for name in ('alice', 'bob'):
        member = shelves.login(name)
        assert member.post('/api/v1/cartridges?slot=red', content=synthetic('red')).status_code == 403
        assert member.post('/api/v1/assets/rom', content=synthetic('red')).status_code == 403
        assert member.delete('/api/v1/cartridges/yellow').status_code == 403
    assert stored(shelves.manager, 'yellow').exists()
    assert not any(row['version'] == 'red' and row['id'] != 'fixture' for row in shelves.manager.registry.roms())


def test_a_member_can_start_an_adventure_from_an_admins_cartridge(shelves, people):  # noqa: F811
    rom_id = slot(upload(shelves.login('admin'), 'blue'), 'blue')['rom']['id']
    alice = shelves.login('alice')
    made = alice.post('/api/v1/adventures', json={'name': 'Mine', 'rom_id': rom_id, 'request_id': identifier()})
    assert made.status_code == 200, made.text
    assert made.json()['owner_id'] == people.alice['id']
    assert alice.get(f'/api/v1/adventures/{made.json()["id"]}').json()['rom_id'] == rom_id


def test_an_adventure_needs_a_cartridge_on_the_library_shelf(shelves, people):  # noqa: F811
    unknown = shelves.login('bob').post('/api/v1/adventures',
                                        json={'name': 'Guess', 'rom_id': 'f' * 64, 'request_id': identifier()})
    assert unknown.status_code == 409
    assert unknown.json()['detail'] == 'Add a game cartridge in Settings before creating an adventure'


def test_any_users_adventure_blocks_removal(shelves, people):  # noqa: F811
    admin = shelves.login('admin')
    rom_id = slot(upload(admin, 'yellow'), 'yellow')['rom']['id']
    shelves.manager.registry.create('Pika', rom_id, {}, identifier(), owner=people.bob['id'])
    refused = admin.delete('/api/v1/cartridges/yellow')
    assert refused.status_code == 409 and 'Pika' in refused.json()['detail']
    assert stored(shelves.manager, 'yellow').exists()


def test_an_unused_cartridge_is_removed_with_its_file(shelves, people):  # noqa: F811
    admin = shelves.login('admin')
    upload(admin, 'yellow')
    path = stored(shelves.manager, 'yellow')
    assert admin.delete('/api/v1/cartridges/yellow').status_code == 200
    assert not path.exists()
    assert 'yellow' not in installed(shelves.login('alice'))
    assert all(row['version'] != 'yellow' for row in shelves.manager.registry.roms())


def test_an_upload_during_a_removal_keeps_the_file(shelves, people, monkeypatch):  # noqa: F811
    admin = shelves.login('admin')
    upload(admin, 'yellow')
    path = stored(shelves.manager, 'yellow')
    assets = shelves.manager.assets
    delete = assets.delete_rom_files
    again = threading.Thread(target=assets.add_cartridge, args=(synthetic('yellow'), 'yellow'),
                             kwargs={'owner': people.admin['id']})

    def racing(rom_ids):
        # The same file is uploaded after the row is removed and before the file goes.
        again.start()
        again.join(1)
        delete(rom_ids)

    monkeypatch.setattr(assets, 'delete_rom_files', racing)
    assert admin.delete('/api/v1/cartridges/yellow').status_code == 200
    again.join(10)
    assert not again.is_alive()
    assert shelves.manager.registry.has_rom(path.parent.name)
    assert path.exists()


def test_an_upload_racing_its_uploaders_deletion_leaves_nothing(shelves, people, monkeypatch):  # noqa: F811
    from pokesim import cartridges
    manager = shelves.manager
    admin = shelves.login('admin')
    real = cartridges.identify

    def deleted_meanwhile(raw):
        # The admin deletes Alice while an upload in her name is still being checked.
        gone = admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                             json={'adventures': {people.red: 'archive'}})
        assert gone.status_code == 200, gone.text
        return real(raw)

    monkeypatch.setattr(cartridges, 'identify', deleted_meanwhile)
    with pytest.raises(ValueError, match='being deleted'):
        manager.assets.add_cartridge(synthetic('gold'), 'gold', owner=people.alice['id'])
    assert not any(row['version'] == 'gold' for row in manager.registry.roms())
    assert not (manager.assets.root / 'roms' / hashlib.sha256(synthetic('gold')).hexdigest()).exists()


def test_deleting_a_user_leaves_every_cartridge(shelves, people):  # noqa: F811
    admin = shelves.login('admin')
    upload(admin, 'gold')
    gold = stored(shelves.manager, 'gold')
    deleted = admin.request('DELETE', f'/api/v1/users/{people.alice["id"]}',
                            json={'adventures': {people.red: 'archive'}})
    assert deleted.status_code == 200, deleted.text
    assert gold.exists()
    assert 'gold' in installed(shelves.login('bob'))
