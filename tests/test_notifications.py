import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim import notify
from pokesim.app import notifications
from pokesim.app.manager import Manager, create_app
from pokesim.app.notifications import CATEGORIES, NotificationCenter, environment_defaults
from pokesim.app.registry import Registry, identifier
from pokesim.events import HIGH, LOW, NORMAL, URGENT, Event
from pokesim.notify import LiveNtfy
from test_managed_supervisor import FakeChild

SECRET = 'tk_secret_value_123'


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ('NTFY_URL', 'NTFY_TOKEN', 'NTFY_MIN_PRIORITY', 'NTFY_MUTE'):
        monkeypatch.delenv(name, raising=False)
    manager = Manager(tmp_path, 'http://testserver', child_factory=FakeChild)
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('rom', 'sha1', 'red')
    with TestClient(create_app(manager)) as client:
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        yield client, manager


def adventure(manager, name):
    return manager.registry.create(name, 'rom', {'starter': 'random'}, identifier())['id']


def sender(center, row):
    live = LiveNtfy()
    live.configure(center.worker_settings(row))
    return live


def test_defaults_need_no_account_and_cover_every_category(client):
    client, manager = client
    data = client.get('/api/v1/notifications').json()
    assert data['source'] == 'default'
    assert (data['enabled'], data['server'], data['topic'], data['token_set']) == (False, 'https://ntfy.sh', '', False)
    chosen = {row['key']: row['enabled'] for row in data['categories']}
    assert list(chosen) == [row[0] for row in CATEGORIES]
    assert chosen['stall'] and chosen['badges'] and chosen['league'] and chosen['other']
    assert not chosen['levels'] and not chosen['blackouts'] and not chosen['trades']
    assert client.get('/notifications').status_code == 200


def test_settings_are_validated_before_anything_is_saved(client):
    client, manager = client
    for change in ({'server': 'ftp://ntfy.sh'}, {'server': 'https://user:pass@ntfy.sh'}, {'server': 'https://'},
                   {'server': 'https://ntfy.sh/?a=1'}, {'server': 7}, {'topic': 'has space'}, {'topic': 'a/b'},
                   {'topic': 'x' * 65}, {'topic': None}, {'token': 'two words'}, {'token': 'line\nbreak'},
                   {'token': 'x' * 513}, {'enabled': 'yes'}, {'enabled': True}, {'min_priority': 0},
                   {'min_priority': True}, {'categories': {'nonsense': True}}, {'categories': {'badges': 1}},
                   {'adventures': {'f' * 32: False}}, {'mute': ['badge']}, {}):
        response = client.patch('/api/v1/notifications', json=change)
        assert response.status_code == 409, change
    assert manager.registry.setting('notifications') is None
    response = client.patch('/api/v1/notifications', json={'server': ' https://ntfy.example.com/push/ ', 'topic': 'Red_1-x'})
    assert response.status_code == 200
    assert response.json()['subscribe_url'] == 'https://ntfy.example.com/push/Red_1-x'


def test_settings_persist_in_the_application_database(client, tmp_path):
    client, manager = client
    aid = adventure(manager, 'Red')
    response = client.patch('/api/v1/notifications', json={
        'enabled': True, 'topic': 'pokesim-abc', 'min_priority': 3,
        'categories': {'levels': True, 'badges': False}, 'adventures': {aid: False}})
    assert response.status_code == 200, response.text
    assert response.json()['pending'] == []
    center = NotificationCenter(manager.registry, SimpleNamespace(), 'http://testserver', environ={})
    data = center.public()
    assert (data['source'], data['enabled'], data['topic'], data['min_priority']) == ('saved', True, 'pokesim-abc', 3)
    chosen = {row['key']: row['enabled'] for row in data['categories']}
    assert chosen['levels'] and not chosen['badges'] and chosen['league']
    assert data['adventures'] == [{'id': aid, 'name': 'Red', 'archived': False, 'enabled': False}]
    assert client.patch('/api/v1/notifications', json={'adventures': {aid: True}}).json()['adventures'][0]['enabled']


def test_access_token_is_never_disclosed_and_can_be_cleared(client):
    client, manager = client
    response = client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic', 'token': SECRET})
    assert response.status_code == 200
    assert response.json()['token_set'] is True
    assert manager.notifications.settings()['token'] == SECRET
    for reply in (response, client.get('/api/v1/notifications'), client.get('/notifications'),
                  client.get('/api/v1/settings'), client.get('/api/v1/adventures')):
        assert SECRET not in reply.text
    assert 'token' not in response.json() and 'token' not in client.get('/api/v1/notifications').json()
    kept = client.patch('/api/v1/notifications', json={'topic': 'other-topic'}).json()
    assert kept['token_set'] is True
    cleared = client.patch('/api/v1/notifications', json={'token': ''}).json()
    assert cleared['token_set'] is False
    assert manager.notifications.settings()['token'] == ''


def test_changes_need_the_same_browser_protection_as_other_settings(client):
    client, manager = client
    csrf = client.headers.pop('X-PokeSim-CSRF')
    assert client.patch('/api/v1/notifications', json={'topic': 'topic'}).status_code == 403
    assert client.post('/api/v1/notifications/test', json={}).status_code == 403
    headers = {'X-PokeSim-CSRF': csrf}
    assert client.patch('/api/v1/notifications', json={'topic': 'topic'}, headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/v1/notifications', headers={'Host': 'evil.example'}).status_code == 403
    assert client.patch('/api/v1/notifications', json={'topic': 'topic'}, headers=headers).status_code == 200


def test_each_adventure_and_category_is_filtered_separately(client):
    client, manager = client
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic', 'token': SECRET,
                                                'adventures': {blue: False}, 'categories': {'evolutions': False}})
    center = manager.notifications
    muted = center.worker_settings(manager.registry.adventure(blue))
    assert (muted['enabled'], muted['url'], muted['token']) == (False, '', '')
    assert not sender(center, manager.registry.adventure(blue)).wants(Event('badge', 'x', priority=URGENT))
    live = sender(center, manager.registry.adventure(red))
    assert (live.url, live.token, live.name) == ('https://ntfy.sh/topic', SECRET, 'Red')
    assert live.wants(Event('badge', 'x', priority=URGENT))
    assert live.wants(Event('catch', 'x', priority=HIGH))
    assert not live.wants(Event('evolve', 'x', priority=HIGH))
    assert not live.wants(Event('level', 'x', priority=HIGH))
    assert not live.wants(Event('blackout', 'x', priority=LOW))
    # One event type can belong to two categories, split by how important the event is.
    assert live.wants(Event('trainer', 'Defeated Lance', priority=URGENT))
    assert not live.wants(Event('trainer', 'Defeated rival', priority=HIGH))
    client.patch('/api/v1/notifications', json={'categories': {'pokedex': False, 'trainers': True, 'league': False}})
    live = sender(center, manager.registry.adventure(red))
    assert live.wants(Event('catch', 'Caught the legendary Mewtwo!', priority=URGENT))
    assert not live.wants(Event('catch', 'Caught Rattata!', priority=HIGH))
    assert live.wants(Event('trainer', 'Defeated rival', priority=HIGH))
    assert not live.wants(Event('trainer', 'Defeated Lance', priority=URGENT))
    assert not live.wants(Event('champion', 'x', priority=URGENT))
    client.patch('/api/v1/notifications', json={'min_priority': 5})
    live = sender(center, manager.registry.adventure(red))
    assert not live.wants(Event('trainer', 'Defeated rival', priority=HIGH))
    client.patch('/api/v1/notifications', json={'enabled': False})
    assert not sender(center, manager.registry.adventure(red)).wants(Event('badge', 'x', priority=URGENT))


def test_stall_has_its_own_category_and_unknown_types_follow_everything_else(client):
    client, manager = client
    red = adventure(manager, 'Red')
    client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic'})
    live = sender(manager.notifications, manager.registry.adventure(red))
    assert live.wants(Event('stall', 'Red has not moved for an hour', priority=HIGH))
    assert live.wants(Event('added_in_a_later_version', 'x', priority=NORMAL))
    assert live.wants(Event('playtime', 'x', priority=LOW))
    client.patch('/api/v1/notifications', json={'categories': {'other': False}})
    live = sender(manager.notifications, manager.registry.adventure(red))
    assert live.wants(Event('stall', 'x', priority=HIGH))
    assert not live.wants(Event('added_in_a_later_version', 'x', priority=URGENT))
    client.patch('/api/v1/notifications', json={'categories': {'other': True, 'stall': False}})
    live = sender(manager.notifications, manager.registry.adventure(red))
    assert not live.wants(Event('stall', 'x', priority=URGENT))
    assert live.wants(Event('added_in_a_later_version', 'x', priority=NORMAL))
    with pytest.raises(ValueError):
        live.configure({'enabled': True})
    assert live.wants(Event('added_in_a_later_version', 'x', priority=NORMAL))


def test_environment_is_the_default_until_the_library_saves(tmp_path):
    environ = {'NTFY_URL': 'https://ntfy.example.com/pokesim', 'NTFY_TOKEN': SECRET,
               'NTFY_MIN_PRIORITY': '3', 'NTFY_MUTE': 'map, item ,catch,money'}
    registry = Registry(tmp_path)
    registry.add_rom('rom', 'sha1', 'red')
    row = registry.create('Red', 'rom', {}, identifier())
    supervisor = SimpleNamespace(push_notifications=lambda: [])
    center = NotificationCenter(registry, supervisor, 'http://testserver', environ=environ)
    data = center.public()
    assert (data['source'], data['enabled'], data['server'], data['topic']) == (
        'environment', True, 'https://ntfy.example.com', 'pokesim')
    assert data['token_set'] and data['min_priority'] == 3
    chosen = {item['key']: item['enabled'] for item in data['categories']}
    assert not chosen['exploration'] and chosen['pokedex'] and chosen['legendary']
    live = sender(center, row)
    assert (live.url, live.token) == ('https://ntfy.example.com/pokesim', SECRET)
    assert live.wants(Event('badge', 'x', priority=URGENT))
    assert not live.wants(Event('catch', 'x', priority=URGENT))
    assert not live.wants(Event('money', 'x', priority=NORMAL))
    assert live.wants(Event('obtain', 'x', priority=HIGH))
    assert not live.wants(Event('evolve', 'x', priority=LOW))
    # Saving anything in the Library adopts these values, then the Library wins.
    center.update({'topic': 'from-library'})
    assert center.public()['source'] == 'saved'
    live = sender(center, row)
    assert (live.url, live.token) == ('https://ntfy.example.com/from-library', SECRET)
    assert live.wants(Event('catch', 'x', priority=URGENT))
    environ['NTFY_URL'] = 'https://elsewhere.example.com/ignored'
    assert center.public()['topic'] == 'from-library'
    registry.close()
    assert environment_defaults({}) is None
    assert environment_defaults({'NTFY_URL': 'https://ntfy.sh'}) is None
    assert environment_defaults({'NTFY_URL': 'https://ntfy.sh/ok', 'NTFY_MIN_PRIORITY': 'loud'}) is None
    assert environment_defaults({'NTFY_URL': 'https://ntfy.sh/ok'})['min_priority'] == 2


def test_running_adventures_receive_changes_without_restarting(client):
    client, manager = client
    supervisor = manager.supervisor
    supervisor.assets = SimpleNamespace(rom_path=lambda rid: manager.root / 'rom.gb', game_data_dir=manager.root,
                                        prepare=lambda report: None, cancelled=supervisor.assets.cancelled)
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    received = {red: [], blue: []}
    original = FakeChild.start
    def start(child):
        original(child)
        aid = child.bootstrap['adventure_id']
        def request(method, path, data=None, timeout=None):
            assert (method, path) == ('POST', '/internal/notifications')
            received[aid].append(data)
            return {'ok': True}
        child.request = request
    FakeChild.start = start
    try:
        for aid in (red, blue):
            manager.registry.request_lifecycle(aid, 'start', identifier())
            supervisor.start(aid)
    finally:
        FakeChild.start = original
    assert [rows[-1]['enabled'] for rows in received.values()] == [False, False]
    assert 'ntfy_url' not in supervisor.children[red].bootstrap['settings']
    response = client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic', 'adventures': {blue: False}})
    assert response.json()['pending'] == []
    assert received[red][-1]['url'] == 'https://ntfy.sh/topic' and received[red][-1]['name'] == 'Red'
    assert received[blue][-1]['enabled'] is False
    # Unchanged settings are not sent again, a rename is, and a failed delivery is retried by the monitor.
    count = len(received[red])
    supervisor.sync_notifications(red, supervisor.children[red])
    assert len(received[red]) == count
    manager.registry.update(red, name='Crimson')
    supervisor.sync_notifications(red, supervisor.children[red])
    assert received[red][-1]['name'] == 'Crimson'
    working = supervisor.children[blue].request
    def fail(*args, **kwargs):
        raise RuntimeError('Worker reconnecting')
    supervisor.children[blue].request = fail
    assert client.patch('/api/v1/notifications', json={'adventures': {blue: True}}).json()['pending'] == [blue]
    supervisor.children[blue].request = working
    supervisor.sync_notifications(blue, supervisor.children[blue])
    assert received[blue][-1]['enabled'] is True


def test_test_notification_reports_what_ntfy_said(client, monkeypatch):
    client, manager = client
    sent = []
    def publish(url, token, title, body, **extra):
        sent.append((url, token, title, extra.get('click')))
    monkeypatch.setattr(notifications, 'publish', publish)
    assert client.post('/api/v1/notifications/test', json={}).status_code == 409
    client.patch('/api/v1/notifications', json={'topic': 'saved-topic', 'token': SECRET})
    assert client.post('/api/v1/notifications/test', json={'request_id': identifier()}).json() == {
        'ok': True, 'subscribe_url': 'https://ntfy.sh/saved-topic'}
    # Values still being typed can be tried before they are saved.
    response = client.post('/api/v1/notifications/test', json={'server': 'https://ntfy.example.com', 'topic': 'draft', 'token': ''})
    assert response.json()['ok'] is True
    assert sent == [('https://ntfy.sh/saved-topic', SECRET, 'PokeSim · Test notification', 'http://testserver/notifications'),
                    ('https://ntfy.example.com/draft', '', 'PokeSim · Test notification', 'http://testserver/notifications')]
    assert manager.notifications.settings()['topic'] == 'saved-topic'
    assert client.post('/api/v1/notifications/test', json={'topic': 'not valid'}).status_code == 409
    def refuse(*args, **kwargs):
        raise RuntimeError('ntfy answered 403: forbidden')
    monkeypatch.setattr(notifications, 'publish', refuse)
    response = client.post('/api/v1/notifications/test', json={})
    assert response.status_code == 200
    assert response.json() == {'ok': False, 'error': 'ntfy answered 403: forbidden'}
    assert SECRET not in response.text


def test_publish_names_the_adventure_and_keeps_screenshot_and_link(monkeypatch):
    calls = []
    def request(method):
        def send(url, content, headers, timeout):
            calls.append((method, url, content, headers))
            return httpx.Response(200, json={'id': 'ok'})
        return send
    monkeypatch.setattr(httpx, 'put', request('PUT'))
    monkeypatch.setattr(httpx, 'post', request('POST'))
    monkeypatch.setattr(notify.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)))
    live = LiveNtfy()
    live.send('Earned the Boulder Badge', 'body')
    assert calls == []
    live.configure({'enabled': True, 'url': 'https://ntfy.sh/topic', 'token': SECRET, 'min_priority': 2,
                    'name': 'Red', 'routes': {}, 'other': True})
    live.send('Earned the Boulder Badge', '1/8 badges', tags='trophy', priority=5, image=b'png',
              click='http://testserver/games/abc/events/7')
    method, url, content, headers = calls.pop()
    assert (method, url, content) == ('PUT', 'https://ntfy.sh/topic', b'png')
    title = headers['Title']
    assert title.startswith('=?UTF-8?B?') and title.isascii()
    assert base64.b64decode(title[10:-2]).decode() == 'Red · Earned the Boulder Badge'
    assert headers['Authorization'] == 'Bearer ' + SECRET
    assert (headers['Click'], headers['Filename'], headers['Priority'], headers['Tags']) == (
        'http://testserver/games/abc/events/7', 'shot.png', '5', 'trophy')
    live.configure({'enabled': True, 'url': 'https://ntfy.sh/topic', 'token': '', 'min_priority': 2,
                    'name': '', 'routes': {}, 'other': True})
    live.send('Plain title', 'body')
    method, url, content, headers = calls.pop()
    assert (method, headers['Title'], content) == ('POST', 'Plain title', 'body')
    assert 'Authorization' not in headers
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: httpx.Response(403, json={'error': 'forbidden', 'http': 403}))
    with pytest.raises(RuntimeError, match='ntfy answered 403: forbidden'):
        notify.publish('https://ntfy.sh/topic', '', 'title', 'body')


def test_completed_trades_are_announced_once_for_both_adventures(client, monkeypatch):
    client, manager = client
    red, blue = adventure(manager, 'Red'), adventure(manager, 'Blue')
    sent = []
    monkeypatch.setattr(notifications, 'publish', lambda url, token, title, body, **extra: sent.append((url, title, body, extra['click'])))
    row = {'id': 't', 'plan': {'participants': [red, blue]}}
    display = {red: {'received': {'name': 'Gengar'}}, blue: {'received': {'name': 'Alakazam'}}}
    client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic'})
    assert manager.notifications.trade_completed(row, display) is None
    client.patch('/api/v1/notifications', json={'categories': {'trades': True}, 'adventures': {red: False}})
    manager.notifications.trade_completed(row, display).join(5)
    assert sent == [('https://ntfy.sh/topic', 'Red ⇄ Blue · Trade completed',
                     'Red received Gengar. Blue received Alakazam.', 'http://testserver/trading')]
    client.patch('/api/v1/notifications', json={'adventures': {blue: False}})
    assert manager.notifications.trade_completed(row, display) is None
