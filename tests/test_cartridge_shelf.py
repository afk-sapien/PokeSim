"""The cartridge shelf API: one slot per game, placed by hash, removable only when unused."""
import hashlib
import io
import zipfile

from fastapi.testclient import TestClient
import pytest

from pokesim import cartridges
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier


def synthetic(version):
    """A made-up cartridge image that only stands in for a real one inside these tests."""
    return f'synthetic {version} cartridge for tests'.encode() * 64


def shelf(monkeypatch, versions=('red', 'blue', 'gold', 'silver', 'crystal')):
    fake = tuple(cartridges.Cartridge(version, 2 if version in {'gold', 'silver', 'crystal'} else 1,
                                      hashlib.sha1(synthetic(version)).hexdigest(), f'Pokémon {version.capitalize()}',
                                      cartridges.JOHTO_STARTERS if version in {'gold', 'silver', 'crystal'} else cartridges.KANTO_STARTERS)
                 for version in versions)
    monkeypatch.setattr(cartridges, 'CARTRIDGES', fake)


@pytest.fixture
def client(tmp_path, monkeypatch):
    shelf(monkeypatch)
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    monkeypatch.setattr(manager.assets, 'install_portraits_quietly', lambda raw: 0)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        yield client, manager, headers


def slot(data, version):
    return next(item for item in data['slots'] if item['version'] == version)


def test_empty_shelf_lists_every_game_in_order(client):
    client, manager, headers = client
    data = client.get('/api/v1/cartridges').json()
    assert [item['version'] for item in data['slots']] == ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal']
    assert not any(item['installed'] for item in data['slots'])
    assert slot(data, 'yellow')['supported'] is False
    assert slot(data, 'gold')['starters'] == ['chikorita', 'cyndaquil', 'totodile']
    assert data['supported'] == 'Red, Blue, Gold, Silver or Crystal'


def test_upload_to_its_own_slot_and_details(client):
    client, manager, headers = client
    response = client.post('/api/v1/cartridges?slot=red', content=synthetic('red'), headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['version'] == 'red' and data['moved'] is False and data['status'] == 'added'
    assert data['message'] == 'Pokémon Red added. It is ready for new adventures.'
    red = slot(data, 'red')
    assert red['installed'] and red['rom']['size'] == len(synthetic('red'))
    assert red['rom']['short_hash'] == hashlib.sha1(synthetic('red')).hexdigest()[:8]
    assert red['rom']['added_at'] > 0
    again = client.post('/api/v1/cartridges?slot=red', content=synthetic('red'), headers=headers).json()
    assert again['status'] == 'same' and 'nothing changed' in again['message']
    assert len(manager.registry.roms()) == 1


def test_wrong_slot_upload_lands_in_the_right_slot(client):
    client, manager, headers = client
    data = client.post('/api/v1/cartridges?slot=red', content=synthetic('blue'), headers=headers).json()
    assert data['version'] == 'blue' and data['moved'] is True
    assert data['message'] == 'That file is Pokémon Blue, not Pokémon Red, so it went into the Blue slot.'
    assert slot(data, 'blue')['installed'] and not slot(data, 'red')['installed']


def test_zip_upload_is_identified(client):
    client, manager, headers = client
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('game.gbc', synthetic('crystal'))
    data = client.post('/api/v1/cartridges', content=buffer.getvalue(), headers=headers).json()
    assert data['version'] == 'crystal' and data['moved'] is False


def test_unknown_file_is_rejected_in_plain_words(client):
    client, manager, headers = client
    response = client.post('/api/v1/cartridges?slot=gold', content=b'not a game at all', headers=headers)
    assert response.status_code == 409
    detail = response.json()['detail']
    assert detail.startswith('This file is not a game PokeSim can play.')
    assert 'Red, Blue, Gold, Silver or Crystal' in detail
    assert client.post('/api/v1/cartridges', content=b'', headers=headers).status_code == 409
    assert client.post('/api/v1/cartridges?slot=emerald', content=synthetic('red'), headers=headers).status_code == 409
    assert manager.registry.roms() == []


def test_yellow_slot_accepts_yellow_once_it_is_identified(client, monkeypatch):
    client, manager, headers = client
    assert client.post('/api/v1/cartridges?slot=yellow', content=synthetic('yellow'), headers=headers).status_code == 409
    shelf(monkeypatch, ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal'))
    data = client.post('/api/v1/cartridges?slot=yellow', content=synthetic('yellow'), headers=headers).json()
    assert data['version'] == 'yellow' and slot(data, 'yellow')['installed'] and slot(data, 'yellow')['supported']
    assert 'Yellow' in client.get('/api/v1/cartridges').json()['supported']


def test_remove_needs_an_unused_cartridge(client):
    client, manager, headers = client
    rom = client.post('/api/v1/cartridges', content=synthetic('silver'), headers=headers).json()['rom']
    created = client.post('/api/v1/adventures', json={'name': 'Johto walk', 'rom_id': rom['id'], 'starter': 'random',
                                                      'request_id': identifier()}, headers=headers).json()
    manager.registry.update(created['id'], archived=True)
    refused = client.delete('/api/v1/cartridges/silver', headers=headers)
    assert refused.status_code == 409
    assert 'Johto walk (archived)' in refused.json()['detail']
    assert (manager.assets.root / 'roms' / rom['id'] / 'rom.gb').exists()
    manager.registry.db.execute('DELETE FROM adventures')
    manager.registry.db.commit()
    removed = client.delete('/api/v1/cartridges/silver', headers=headers)
    assert removed.status_code == 200, removed.text
    assert not slot(removed.json(), 'silver')['installed']
    assert not (manager.assets.root / 'roms' / rom['id']).exists()
    assert client.delete('/api/v1/cartridges/silver', headers=headers).status_code == 404
    assert client.delete('/api/v1/cartridges/red').status_code == 403


def test_existing_rom_rows_fill_their_slots(client):
    client, manager, headers = client
    manager.registry.add_rom('legacy-gold', 'f' * 40, 'gold')
    gold = slot(client.get('/api/v1/cartridges').json(), 'gold')
    assert gold['installed'] and gold['rom']['file_missing'] and gold['rom']['short_hash'] == 'ffffffff'


def test_old_routes_still_work(client):
    client, manager, headers = client
    row = client.post('/api/v1/assets/rom', content=synthetic('gold'), headers=headers).json()
    assert row['version'] == 'gold' and row['id'] == hashlib.sha256(synthetic('gold')).hexdigest()
    assets = client.get('/api/v1/assets').json()
    assert assets['roms'] == [{'id': row['id'], 'sha1': row['sha1'], 'version': 'gold'}]
    assert slot({'slots': assets['cartridges']}, 'gold')['installed']


def test_damaged_stored_copy_is_repaired_by_a_new_upload(client):
    client, manager, headers = client
    rom = client.post('/api/v1/cartridges', content=synthetic('red'), headers=headers).json()['rom']
    (manager.assets.root / 'roms' / rom['id'] / 'rom.gb').write_bytes(b'damaged')
    data = client.post('/api/v1/cartridges?slot=red', content=synthetic('red'), headers=headers).json()
    assert data['status'] == 'repaired'
    assert manager.assets.rom_path(rom['id']).read_bytes() == synthetic('red')


def test_upload_extracts_portraits_in_the_background(tmp_path, monkeypatch):
    shelf(monkeypatch)
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    seen = []
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: seen.append(raw) or 0)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        assert client.post('/api/v1/cartridges', content=synthetic('blue'), headers=headers).status_code == 200
    assert seen == [synthetic('blue')]
