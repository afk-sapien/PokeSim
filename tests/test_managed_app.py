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
    response = client.get('/api/v1/session')
    assert response.status_code == 200
    return {'X-PokeSim-CSRF': response.json()['csrf_token']}


def test_keyless_library_retains_request_boundaries(client):
    client, manager = client
    assert client.get('/').status_code == 200
    assert client.get('/health/ready').json()['adventures'] == 0
    assert client.get('/api/v1/adventures').json() == {'adventures': []}
    assert not (manager.root / 'owner.token').exists()
    assert 'Owner key' not in client.get('/').text
    assert client.get('/api/v1/session', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    headers = login(client, manager)
    assert client.get('/api/v1/adventures').json() == {'adventures': []}
    assert client.patch('/api/v1/settings', json={'max_running': 3}).status_code == 403
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=headers).status_code == 200
    assert client.patch('/api/v1/settings', json={'max_running': 2}, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/v1/settings', headers={'Host': 'evil.example'}).status_code == 403
    assert client.patch('/api/v1/settings', json={'max_running': 2}, headers={**headers, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/api/v1/session').json()['csrf_token'] == headers['X-PokeSim-CSRF']
    assert client.cookies.get('pokesim_session')


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


def test_expired_browser_session_is_recreated_without_login(client):
    client, manager = client
    headers = login(client, manager)
    for session in manager.sessions.values():
        session['expires'] = 0
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=headers).status_code == 403
    replacement = login(client, manager)
    assert replacement != headers
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=replacement).status_code == 200


def test_csrf_token_from_another_browser_cannot_authorize_a_write(client):
    client, manager = client
    first = login(client, manager)
    client.cookies.clear()
    second = login(client, manager)
    assert first != second
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=first).status_code == 403
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=second).status_code == 200
