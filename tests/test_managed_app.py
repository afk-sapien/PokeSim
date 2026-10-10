import hashlib
import json
import time
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
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=headers).status_code == 409
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
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=replacement).status_code == 409


def test_csrf_token_from_another_browser_cannot_authorize_a_write(client):
    client, manager = client
    first = login(client, manager)
    client.cookies.clear()
    second = login(client, manager)
    assert first != second
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=first).status_code == 403
    assert client.patch('/api/v1/settings', json={'max_running': 3}, headers=second).status_code == 409


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
        assert response.headers['cache-control'] == 'private, no-cache'
    custom = manager.root / 'adventures' / first['id'] / 'sprites'
    custom.mkdir()
    (custom / '25.png').write_bytes(b'custom portrait')
    assert client.get(f'/games/{first["id"]}/sprites/25.png').content == b'custom portrait'
    assert client.get(f'/games/{second["id"]}/sprites/25.png').content == b'shared portrait'
    assert client.get(f'/games/{second["id"]}/sprites/0.png').status_code == 404
    assert client.get(f'/games/{second["id"]}/sprites/252.png').status_code == 404


def test_gen2_portraits_cover_all_251_species(client):
    client, manager = client
    manager.registry.add_rom('fixture-silver', 'sha1', 'silver')
    folder = manager.assets.root / 'sprites' / 'silver'
    folder.mkdir(parents=True)
    (folder / '25.png').write_bytes(b'silver 25')
    (folder / '251.png').write_bytes(b'silver 251')
    row = manager.registry.create('Gen Two', 'fixture-silver', {'starter': 'random'}, identifier())
    for dex, body in ((25, b'silver 25'), (251, b'silver 251')):
        response = client.get(f'/games/{row["id"]}/sprites/{dex}.png')
        assert response.status_code == 200 and response.content == body
    assert client.get(f'/games/{row["id"]}/sprites/252.png').status_code == 404


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
    for asset in ('adventure-trading.js', 'trade-progress.js', 'routes.js', 'tokens.css', 'panel.css', 'panel.js', 'panel-trading.css'):
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


def test_speed_is_independent_and_editable_while_running(client):
    client, manager = client
    headers = login(client, manager)
    from pokesim.nicknames import NICKNAME_FIELDS
    assert set(client.get('/api/v1/settings').json()) == {'data_dir', 'nickname_catalog', *NICKNAME_FIELDS}
    for data in ({'speed': 4}, {'max_running': 3}):
        assert client.patch('/api/v1/settings', json=data, headers=headers).status_code == 409
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    first = manager.registry.create('Red', 'fixture-rom', {'speed': 8}, identifier())
    second = manager.registry.create('Blue', 'fixture-rom', {'speed': 2}, identifier())
    manager.registry.update(first['id'], state='running')
    route = '/api/v1/adventures/' + first['id']
    for value in (0, 0.5, 1, 4, 16):
        response = client.patch(route, json={'settings': {'speed': value}}, headers=headers)
        assert response.status_code == 200
        assert response.json()['settings']['speed'] == value
        assert manager.registry.adventure(second['id'])['settings']['speed'] == 2
    for value in (True, '0', -1, 17, 0.01, None):
        assert client.patch(route, json={'settings': {'speed': value}}, headers=headers).status_code == 409
    assert client.patch(route, json={'settings': {'speed': 4}}).status_code == 403
    assert client.patch(route, json={'settings': {'starter': 'squirtle'}}, headers=headers).status_code == 409


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


def test_legendary_return_interval_validation():
    from pokesim.app.manager import Manager
    assert Manager.validate_adventure_settings({'legendary_return_steps': 0})['legendary_return_steps'] == 0
    assert Manager.validate_adventure_settings({'legendary_return_steps': 1000000})['legendary_return_steps'] == 1000000
    for value in (-1, True, 0.5, '1000000', 1000000001):
        with pytest.raises(ValueError):
            Manager.validate_adventure_settings({'legendary_return_steps': value})


def test_library_resources_are_live_and_not_written_to_adventure_records(client, monkeypatch):
    browser, manager = client
    manager.registry.add_rom('usage-rom', 'sha1', 'red')
    row = manager.registry.create('Resource check', 'usage-rom', {}, identifier())
    usage = {'cpu_percent': 75.2, 'memory_bytes': 123456789}
    monkeypatch.setattr(manager.supervisor, 'resources', lambda aid: usage)
    assert browser.get('/api/v1/adventures').json()['adventures'][0]['resources'] == usage
    assert browser.get('/api/v1/adventures/' + row['id']).json()['resources'] == usage
    assert 'resources' not in manager.registry.adventure(row['id'])
    monkeypatch.setattr(manager.supervisor, 'resources', lambda aid: None)
    assert browser.get('/api/v1/adventures/' + row['id']).json()['resources'] is None


@pytest.mark.parametrize('field', ['event_return_steps', 'mew_return_steps'])
def test_walking_reward_interval_validation(field):
    from pokesim.app.manager import Manager
    assert Manager.validate_adventure_settings({field: 0})[field] == 0
    assert Manager.validate_adventure_settings({field: 100000})[field] == 100000
    for value in (-1, True, 1.5, '100000', 1000000001):
        with pytest.raises(ValueError):
            Manager.validate_adventure_settings({field: value})


def test_walking_reward_choice_validation():
    from pokesim.app.manager import Manager
    for field, choices in {'fossil_preference': ('auto', 'helix', 'dome', 'amber'),
                           'dojo_preference': ('auto', 'hitmonlee', 'hitmonchan')}.items():
        for choice in choices:
            assert Manager.validate_adventure_settings({field: choice})[field] == choice
        with pytest.raises(ValueError):
            Manager.validate_adventure_settings({field: 'random-garbage'})


def test_global_nickname_settings_are_validated_persisted_and_reset(client, monkeypatch):
    client, manager = client
    headers = login(client, manager)
    calls = []
    monkeypatch.setattr(manager.supervisor, 'update_nicknames', lambda: calls.append(True) or ['reconnecting'])
    payload = {'nickname_prefixes': [' spicy ', 'SPICY'], 'nickname_suffixes': ['goose']}
    assert client.patch('/api/v1/settings', json=payload).status_code == 403
    result = client.patch('/api/v1/settings', json=payload, headers=headers)
    assert result.status_code == 200
    assert result.json()['pending'] == ['reconnecting']
    saved = manager.registry.setting('nickname_parts')
    from pokesim.nicknames import nickname_defaults
    assert saved == {**nickname_defaults(), 'nickname_prefixes': ['SPICY'], 'nickname_suffixes': ['GOOSE']}
    assert client.get('/api/v1/settings').json()['nickname_prefixes'] == ['SPICY']
    assert client.patch('/api/v1/settings', json={**payload, 'speed': 4}, headers=headers).status_code == 409
    assert client.patch('/api/v1/settings', json={**payload, 'nickname_prefixes': ['<script>']}, headers=headers).status_code == 409
    assert manager.registry.setting('nickname_parts') == saved
    result = client.patch('/api/v1/settings', json={'nickname_prefixes': [], 'nickname_suffixes': []}, headers=headers)
    assert result.status_code == 200 and len(calls) == 2


def test_create_saves_normalized_intro_names_and_rejects_later_edits(client):
    client, manager = client
    headers = login(client, manager)
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    payload = {'name': 'Custom intro', 'rom_id': 'fixture-rom', 'trainer_name': ' ty ',
               'rival_name': 'gary', 'request_id': identifier()}
    row = client.post('/api/v1/adventures', headers=headers, json=payload).json()
    assert row['settings']['trainer_name'] == 'TY'
    assert row['settings']['rival_name'] == 'GARY'
    assert client.post('/api/v1/adventures', headers=headers, json=payload).json()['id'] == row['id']
    assert manager.registry.adventure(row['id'])['settings']['trainer_name'] == 'TY'
    response = client.patch(f"/api/v1/adventures/{row['id']}", headers=headers,
                            json={'settings': {'trainer_name': 'ASH'}})
    assert response.status_code == 409
    for bad in ('TOOLONGGG', 'A B', 'ASH!', 'ß', None, 5):
        response = client.post('/api/v1/adventures', headers=headers,
                               json={**payload, 'request_id': identifier(), 'rival_name': bad})
        assert response.status_code == 409
    assert len(manager.registry.adventures()) == 1


def test_audio_proxy_preserves_pcm_metadata_and_adventure_boundary(client, monkeypatch):
    import httpx
    client, manager = client
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    adventure = manager.registry.create('Audio Red', 'fixture-rom', {}, identifier())
    manager.registry.update(adventure['id'], state='running')
    child = SimpleNamespace(url='http://worker', token='private-worker-token')
    monkeypatch.setattr(manager.supervisor, 'child', lambda aid: child)
    def worker(request):
        assert request.url.path == '/api/audio'
        assert request.url.query == b'after=7'
        assert request.headers['authorization'] == 'Bearer private-worker-token'
        return httpx.Response(200, content=b'\x01\x02' * 800, headers={
            'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
            'X-Audio-State': 'playing', 'X-Audio-Rate': '48000', 'X-Audio-Sequence': '8',
            'X-Audio-Speed': '16', 'X-Audio-Mode': 'manual', 'X-Audio-Dropped': '3',
            'X-Private-Worker': 'must-not-leak',
        })
    client.app.state.children = httpx.AsyncClient(transport=httpx.MockTransport(worker))
    path = f'/games/{adventure["id"]}/api/audio?after=7'
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == b'\x01\x02' * 800
    assert response.headers['X-Audio-State'] == 'playing'
    assert response.headers['X-Audio-Rate'] == '48000'
    assert response.headers['X-Audio-Sequence'] == '8'
    assert response.headers['X-Audio-Speed'] == '16'
    assert response.headers['X-Audio-Mode'] == 'manual' and response.headers['X-Audio-Dropped'] == '3'
    assert 'X-Private-Worker' not in response.headers
    assert client.get(path, headers={'Origin': 'https://elsewhere.invalid'}).status_code == 403
    manager.registry.update(adventure['id'], state='stopped')
    assert client.get(path).status_code == 409


def test_palette_changes_live_and_requires_valid_authorized_settings(client, monkeypatch):
    client, manager = client
    headers = login(client, manager)
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'fixture-rom', {}, identifier())
    manager.registry.update(row['id'], state='running')
    route = '/api/v1/adventures/' + row['id']
    calls = []
    def push(aid):
        calls.append((aid, manager.registry.adventure(aid)['settings']['palette']))
        return True
    monkeypatch.setattr(manager.supervisor, 'push_palette', push)
    response = client.patch(route, json={'settings': {'palette': 'blue'}}, headers=headers)
    assert response.status_code == 200
    assert response.json()['palette_pending'] is True
    assert response.json()['state'] == 'running'
    assert calls == [(row['id'], 'blue')]
    for value in ('invalid', None, [], True):
        assert client.patch(route, json={'settings': {'palette': value}}, headers=headers).status_code == 409
    assert client.patch(route, json={'settings': {'palette': 'red'}}).status_code == 403
    assert manager.registry.adventure(row['id'])['settings']['palette'] == 'blue'
    assert len(calls) == 1


def test_manual_trade_endpoints_queue_report_and_cancel(client, monkeypatch):
    client, manager = client
    headers = login(client, manager)
    manager.registry.add_rom('rom', 'sha', 'red')
    games = [manager.registry.create(name, 'rom', {}, identifier()) for name in ('Red A', 'Red B')]
    for game in games:
        manager.registry.update(game['id'], state='running', desired_state='running')
    drains = []
    monkeypatch.setattr(manager.coordinator, 'drain_manual', lambda: drains.append(True))
    monkeypatch.setattr(manager.coordinator, 'manual_options', lambda: {'adventures': [{'id': games[0]['id'], 'pokemon': []}]})
    assert client.get('/trade').status_code == 200
    assert client.get('/api/v1/interactions/manual-trades/options').json()['adventures'][0]['id'] == games[0]['id']
    payload = {'left_id': games[0]['id'], 'right_id': games[1]['id'], 'left_key': 'a', 'right_key': 'b',
               'request_id': identifier()}
    assert client.post('/api/v1/interactions/manual-trades', json=payload).status_code == 403
    assert client.post('/api/v1/interactions/manual-trades', json={**payload, 'protect': False},
                       headers=headers).status_code == 409
    response = client.post('/api/v1/interactions/manual-trades', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status['id'] == payload['request_id']
    assert status['state'] == 'queued'
    assert status['position'] == 1
    # The drain is a background task on a worker thread; it can start just after the response.
    deadline = time.monotonic() + 5
    while not drains and time.monotonic() < deadline:
        time.sleep(0.01)
    assert drains
    assert client.get('/api/v1/interactions/manual-trades').json()['trades'][0]['id'] == status['id']
    assert client.get('/api/v1/interactions/manual-trades/' + status['id']).json()['state'] == 'queued'
    assert client.get('/api/v1/interactions/manual-trades/' + identifier()).status_code == 404
    cancelled = client.post(f'/api/v1/interactions/manual-trades/{status["id"]}/cancel', headers=headers).json()
    assert cancelled['state'] == 'cancelled'
    assert client.post(f'/api/v1/interactions/manual-trades/{identifier()}/cancel', headers=headers).status_code == 404


def test_a_slow_game_trade_history_does_not_stall_the_library(client, monkeypatch):
    """The game proxy shares one event loop with every page of every adventure."""
    import asyncio
    import threading
    import httpx
    client, manager = client
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'fixture-rom', {}, identifier())
    release = threading.Event()
    def slow_status(aid):
        release.wait(10)
        return {'adventure': {'id': aid}, 'active': [], 'history': [], 'recent_failures': [], 'attention': None}
    monkeypatch.setattr(manager.coordinator, 'adventure_status', slow_status)

    async def run():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as browser:
            timer = threading.Timer(3, release.set)
            timer.start()
            started = time.monotonic()
            slow = asyncio.create_task(browser.get(f'/games/{row["id"]}/api/interactions'))
            await asyncio.sleep(0.05)
            other = await browser.get(f'/games/{row["id"]}/trading')
            elapsed = time.monotonic() - started
            result = await slow
            timer.cancel()
            return other, elapsed, result
    other, elapsed, slow = asyncio.run(run())
    assert other.status_code == 200 and elapsed < 2
    assert slow.status_code == 200 and slow.json()['adventure']['id'] == row['id']
