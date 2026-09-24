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
        assert row['settings']['league_rewards'] is True
        assert row['settings']['mew_event'] is True
        assert client.post('/api/v1/adventures', json=payload, headers=headers).json()['id'] == row['id']
        created.append(row)
    assert len(client.get('/api/v1/adventures').json()['adventures']) == 2
    assert created[0]['id'] != created[1]['id']
    assert client.get(created[0]['url']).status_code == 200
    assert client.get(created[0]['url'] + 'internal/health').status_code == 404
    assert client.get(created[0]['url'] + 'api/trade').status_code == 404
    assert client.post(f"/api/v1/adventures/{created[0]['id']}/archive", json={}, headers=headers).json()['archived']


def test_reward_defaults_respect_explicit_choices_and_existing_adventures(client):
    client, manager = client
    headers = login(client, manager)
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    response = client.post('/api/v1/adventures', headers=headers, json={
        'name': 'No gifts', 'rom_id': 'fixture-rom',
        'league_rewards': False, 'mew_event': False,
    })
    assert response.status_code == 200
    row = response.json()
    route = f"/api/v1/adventures/{row['id']}"
    edited = client.patch(route, headers=headers, json={'settings': {'auto_start': True}}).json()
    assert edited['settings']['league_rewards'] is False
    assert edited['settings']['mew_event'] is False
    legacy = manager.registry.create('Existing', 'fixture-rom', {}, identifier())
    response = client.patch(f"/api/v1/adventures/{legacy['id']}", headers=headers,
                            json={'settings': {'auto_start': True}})
    assert response.status_code == 200
    assert not response.json()['settings'].get('league_rewards', False)
    assert not response.json()['settings'].get('mew_event', False)


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


def test_shared_portraits_work_for_new_adventures_and_allow_local_overrides(client):
    client, manager = client
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    shared = manager.assets.root / 'sprites'
    shared.mkdir(parents=True)
    (shared / '25.png').write_bytes(b'shared portrait')
    first = manager.registry.create('First', 'fixture-rom', {'starter': 'random'}, identifier())
    second = manager.registry.create('Later', 'fixture-rom', {'starter': 'random'}, identifier())
    for row in (first, second):
        response = client.get(f'/games/{row["id"]}/sprites/25.png')
        assert response.headers['content-type'] == 'image/png'
        assert response.content == b'shared portrait'
    custom = manager.root / 'adventures' / first['id'] / 'sprites'
    custom.mkdir()
    (custom / '25.png').write_bytes(b'custom portrait')
    assert client.get(f'/games/{first["id"]}/sprites/25.png').content == b'custom portrait'
    assert client.get(f'/games/{second["id"]}/sprites/25.png').content == b'shared portrait'
    assert client.get(f'/games/{second["id"]}/sprites/0.png').status_code == 404
    assert client.get(f'/games/{second["id"]}/sprites/152.png').status_code == 404


def test_game_trading_stays_scoped_and_available_when_stopped(client):
    client, manager = client
    registry = manager.registry
    registry.add_rom('fixture-rom', 'sha1', 'red')
    a, b, c = [registry.create(name, 'fixture-rom', {}, identifier())
               for name in ('First Red', 'Second Red', 'Third Red')]
    def transaction(left, right, phase, decision=None):
        row = registry.create_transaction(identifier(), {'participants': [left['id'], right['id']],
            'left_id': left['id'], 'right_id': right['id']})
        return registry.update_transaction(row['id'], phase=phase, decision=decision)
    done = transaction(a, b, 'completed', 'COMMIT')
    transaction(a, b, 'aborted', 'ABORT')
    active = transaction(b, c, 'preparing')
    for _ in range(1001):
        transaction(b, c, 'completed', 'COMMIT')
    base = f'/games/{a["id"]}'
    response = client.get(base + '/trading', follow_redirects=False)
    assert response.status_code == 200
    assert 'location' not in response.headers
    assert 'First Red' in response.text
    assert f'href="{base}/trading"' in response.text
    assert f'href="{base}/pc?scope=all"' in response.text
    assert 'href="/trading"' not in response.text
    for asset in ('adventure-trading.js', 'routes.js', 'tokens.css', 'panel.css', 'panel.js', 'panel-trading.css'):
        assert client.get(base + '/static/' + asset).status_code == 200
    data = client.get(base + '/api/interactions').json()
    assert data['adventure']['id'] == a['id']
    assert data['active'] == []
    assert [row['id'] for row in data['history']] == [done['id']]
    assert data['history'][0]['peer_name'] == 'Second Red'
    second = client.get(f'/games/{b["id"]}/api/interactions').json()
    assert second['adventure']['id'] == b['id']
    assert len(second['history']) == 20
    assert [row['id'] for row in second['active']] == [active['id']]
    assert second['active'][0]['peer_name'] == 'Third Red'
    assert client.get('/trading').status_code == 200
    assert client.get('/games/' + 'f' * 32 + '/api/interactions').status_code == 404


def test_pace_is_a_global_setting_and_rejects_per_adventure_edits(client):
    client, manager = client
    headers = login(client, manager)
    assert client.get('/api/v1/settings').json()['speed'] == 1
    for value in (0, 1, 16):
        response = client.patch('/api/v1/settings', json={'speed': value}, headers=headers)
        assert response.status_code == 200
        assert response.json()['speed'] == value
        assert manager.registry.setting('speed') == value
    for value in (True, '0', -1, 17):
        assert client.patch('/api/v1/settings', json={'speed': value}, headers=headers).status_code == 409
    assert client.patch('/api/v1/settings', json={'speed': 4}).status_code == 403
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    game = manager.registry.create('Red', 'fixture-rom', {'speed': 8}, identifier())
    route = '/api/v1/adventures/' + game['id']
    response = client.patch(route, json={'settings': {'speed': 4}}, headers=headers)
    assert response.status_code == 409
    assert 'Library Settings' in response.text
    response = client.patch(route, json={'settings': {'auto_start': True}}, headers=headers)
    assert response.status_code == 200
    assert 'speed' not in response.json()['settings']


def test_event_retention_is_configurable_per_adventure():
    """Every notable event stores a full save state, so the journal grows ~40 MB an hour.

    The setting existed in the runtime and was validated there, but the Library's own
    whitelist left it out, so a managed adventure could never bound its own history.
    """
    settings = Manager.validate_adventure_settings({'event_retention_days': 30})
    assert settings['event_retention_days'] == 30
    assert Manager.validate_adventure_settings({'event_retention_days': 0})['event_retention_days'] == 0
    for invalid in (-1, 40000, 'thirty', 1.5):
        with pytest.raises(ValueError):
            Manager.validate_adventure_settings({'event_retention_days': invalid})


def test_runtime_accepts_the_retention_setting_the_library_now_sends(tmp_path):
    """The supervisor passes adventure settings straight into the worker bootstrap."""
    from pokesim.runtime.settings import SimulationSettings

    rom = tmp_path / 'rom.gb'
    rom.write_bytes(b'\x00')
    settings = SimulationSettings(rom_path=str(rom), data_dir=str(tmp_path),
                                  game_data_dir=str(tmp_path), event_retention_days=30)
    assert settings.event_retention_days == 30
