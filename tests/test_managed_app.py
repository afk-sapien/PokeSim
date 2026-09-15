import hashlib
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim import desktop_setup


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        yield client, manager


def login(client, manager):
    response = client.post('/api/v1/session', json={'token': manager.owner_token})
    assert response.status_code == 200
    return {'X-PokeSim-CSRF': response.json()['csrf_token']}


def test_library_without_rom_and_auth_boundaries(client):
    client, manager = client
    assert client.get('/').status_code == 200
    assert client.get('/health/ready').json()['adventures'] == 0
    assert client.get('/api/v1/adventures').status_code == 401
    assert client.post('/api/v1/session', json={'token': 'wrong'}).status_code == 401
    headers = login(client, manager)
    assert client.get('/api/v1/adventures').json() == {'adventures': []}
    assert client.patch('/api/v1/settings', json={'max_running': 3}).status_code == 403
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=headers).status_code == 200
    assert client.patch('/api/v1/settings', json={'max_running': 2}, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/v1/settings', headers={'Host': 'evil.example'}).status_code == 403


def test_library_upload_reuse_same_version_and_stopped_page(client, monkeypatch):
    client, manager = client
    headers = login(client, manager)
    raw = b'private-test-rom'
    monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Pokémon Red')
    rom = client.post('/api/v1/assets/rom', content=raw, headers=headers).json()
    created = []
    for name in ('Red A', 'Red B'):
        payload = {'name': name, 'rom_id': rom['id'], 'starter': 'random', 'request_id': identifier()}
        response = client.post('/api/v1/adventures', json=payload, headers=headers)
        assert response.status_code == 200, response.text
        row = response.json()
        assert client.post('/api/v1/adventures', json=payload, headers=headers).json()['id'] == row['id']
        created.append(row)
    assert len(client.get('/api/v1/adventures').json()['adventures']) == 2
    assert created[0]['id'] != created[1]['id']
    assert client.get(created[0]['url']).status_code == 200
    assert client.get(created[0]['url'] + 'internal/health').status_code == 404
    assert client.get(created[0]['url'] + 'api/trade').status_code == 404
    assert client.post(f"/api/v1/adventures/{created[0]['id']}/archive", json={}, headers=headers).json()['archived']


def test_full_backup_and_verified_restore(client, tmp_path):
    client, manager = client
    headers = login(client, manager)
    response = client.post('/api/v1/backups', json={}, headers=headers)
    assert response.status_code == 200, response.text
    backup = response.json()
    assert client.get('/api/v1/backups/' + backup['id'] + '/download').status_code == 200
    from pokesim.app.backup import restore_backup
    target = tmp_path / 'restored'
    restore_backup(backup['path'], target)
    assert (target / 'app.sqlite').is_file()
    assert not (target / 'owner.token').exists()
