"""The control lease: one account plays an adventure by hand at a time, with roles below the owner."""
from types import SimpleNamespace

import pytest

from pokesim.app import lease as lease_module
from pokesim.app import policy
from pokesim.web.security import role_allows

from test_accounts import library, people  # noqa: F401


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def game(library, people, monkeypatch):  # noqa: F811
    """Alice owns Red. Bob can play it, Carol can manage it and Dave can watch it."""
    calls = []

    def request(aid):
        def send(method, path, body=None, timeout=None):
            calls.append((aid, path, (body or {}).get('action')))
            return {'ok': True}
        return send
    monkeypatch.setattr(library.manager.supervisor, 'child', lambda aid: SimpleNamespace(
        url='http://127.0.0.1:12345', token='private-worker-token', request=request(aid)))
    clock = Clock()
    library.manager.leases.clock = clock
    carol, dave = library.user('carol'), library.user('dave')
    auth = library.manager.auth
    auth.grant(people.red, people.bob['id'], 'player', people.alice['id'])
    auth.grant(people.red, carol['id'], 'manager', people.alice['id'])
    auth.grant(people.red, dave['id'], 'viewer', people.alice['id'])
    return SimpleNamespace(library=library, red=people.red, calls=calls, clock=clock,
                           alice=library.login('alice'), bob=library.login('bob'), carol=library.login('carol'),
                           dave=library.login('dave'), ids=SimpleNamespace(bob=people.bob['id'], carol=carol['id']))


def lease(client, aid, action=None, **extra):
    if action is None:
        return client.get(f'/games/{aid}/api/lease')
    return client.post(f'/games/{aid}/api/lease', json={'action': action, **extra})


def press(client, aid):
    return client.post(f'/games/{aid}/api/control', json={'action': 'press', 'value': 'a'})


def test_roles_map_to_controls():
    assert policy.game_action('POST', 'api/control', 'press') == 'adventure.play'
    assert policy.game_action('POST', 'api/control', 'pause') == 'adventure.manage'
    assert policy.game_action('POST', 'api/control', 'restart') == 'adventure.own'
    assert policy.game_action('POST', 'api/lease') == 'adventure.play'
    assert policy.game_action('GET', 'api/lease') == 'adventure.watch'
    assert policy.game_action('GET', 'api/states') == 'adventure.manage'
    assert role_allows('player', 'POST', '/api/control')
    assert not role_allows('player', 'POST', '/api/speed')
    assert role_allows('manager', 'POST', '/api/speed')
    assert not role_allows('manager', 'POST', '/api/export-save')


def test_a_press_needs_the_lease_and_the_first_request_wins(game):
    assert press(game.bob, game.red).status_code == 409
    granted = lease(game.bob, game.red, 'request').json()
    assert granted['you_hold'] and granted['role'] == 'player'
    assert (game.red, '/api/control', 'take_control') in game.calls
    assert press(game.bob, game.red).status_code == 200
    # A second person queues and cannot press.
    queued = lease(game.carol, game.red, 'request').json()
    assert not queued['you_hold'] and queued['queued']
    assert press(game.carol, game.red).status_code == 409
    # A watcher sees who plays, but not the queue or the holder's id.
    watched = lease(game.dave, game.red).json()
    assert watched['holder'] == {'name': 'bob'} and watched['queue'] == []
    assert lease(game.dave, game.red, 'request').status_code == 403
    assert press(game.dave, game.red).status_code == 403


def test_the_holder_hands_over_or_refuses(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    status = lease(game.bob, game.red).json()
    assert [entry['id'] for entry in status['queue']] == [game.ids.carol]
    lease(game.bob, game.red, 'refuse', user_id=game.ids.carol)
    assert lease(game.bob, game.red).json()['queue'] == []
    lease(game.carol, game.red, 'request')
    handed = lease(game.bob, game.red, 'handover', user_id=game.ids.carol).json()
    assert not handed['you_hold'] and handed['holder']['name'] == 'carol'
    assert press(game.carol, game.red).status_code == 200
    assert press(game.bob, game.red).status_code == 409


def test_an_owner_or_manager_takes_control_back(game):
    lease(game.bob, game.red, 'request')
    assert lease(game.bob, game.red, 'take').status_code == 403
    taken = lease(game.alice, game.red, 'take').json()
    assert taken['you_hold']
    assert press(game.bob, game.red).status_code == 409


def test_letting_go_passes_control_on_or_applies_the_owners_choice(game):
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    lease(game.bob, game.red, 'release')
    assert lease(game.carol, game.red).json()['you_hold']
    assert lease(game.bob, game.red, 'setting', end='pause').status_code == 403
    assert lease(game.alice, game.red, 'setting', end='pause').json()['end'] == 'pause'
    lease(game.carol, game.red, 'release')
    assert game.calls[-1] == (game.red, '/api/control', 'pause')
    assert lease(game.carol, game.red).json()['holder'] is None


def test_quiet_pages_and_idle_hands_lose_control(game, monkeypatch):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    game.clock.now += lease_module.HEARTBEAT_GRACE_SECONDS - 1
    lease(game.bob, game.red, 'heartbeat')
    game.clock.now += lease_module.HEARTBEAT_GRACE_SECONDS - 1
    leases.sweep()
    assert leases.holder(game.red) == game.ids.bob
    game.clock.now += 2
    leases.sweep()
    assert leases.holder(game.red) is None
    assert game.calls[-1] == (game.red, '/api/control', 'resume')
    # Heartbeats alone do not keep control: buttons must be pressed.
    monkeypatch.setenv('CONTROL_IDLE_SECONDS', '60')
    lease(game.bob, game.red, 'request')
    game.clock.now += 40
    lease(game.bob, game.red, 'heartbeat')
    status = lease(game.bob, game.red).json()
    assert status['idle_warning'] and status['idle_ends_in'] == 20
    game.clock.now += 21
    lease(game.bob, game.red, 'heartbeat')
    leases.sweep()
    assert leases.holder(game.red) is None


def test_losing_can_play_ends_the_lease(game):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    lease(game.carol, game.red, 'request')
    game.alice.post(f'/api/v1/adventures/{game.red}/grants', json={'user_id': game.ids.bob, 'role': 'viewer'})
    assert leases.holder(game.red) == game.ids.carol
    game.alice.delete(f'/api/v1/adventures/{game.red}/grants/{game.ids.carol}')
    assert leases.holder(game.red) is None


def test_a_trade_or_backup_ends_control(game):
    manager = game.library.manager
    lease(game.bob, game.red, 'request')
    assert manager.leases.end_all('backup') == [game.red]
    lease(game.bob, game.red, 'request')
    manager.suspended = True
    try:
        refused = lease(game.carol, game.red, 'take')
    finally:
        manager.suspended = False
    assert refused.status_code == 409 and 'backup' in refused.json()['detail']


def test_resume_and_pause_end_the_lease(game):
    leases = game.library.manager.leases
    lease(game.bob, game.red, 'request')
    assert game.bob.post(f'/games/{game.red}/api/control', json={'action': 'pause'}).status_code == 403
    assert game.carol.post(f'/games/{game.red}/api/control', json={'action': 'resume'}).status_code == 200
    assert leases.holder(game.red) is None


def test_the_worker_hears_the_role(game):
    game.library.forwarded.clear()
    game.bob.get(f'/games/{game.red}/api/state')
    game.carol.get(f'/games/{game.red}/api/state')
    game.alice.get(f'/games/{game.red}/api/state')
    roles = [request.headers.get('X-PokeSim-Role') for request in game.library.forwarded]
    assert roles == ['player', 'manager', None]


def test_an_open_stream_closes_when_watching_is_revoked(game, monkeypatch):
    import httpx
    monkeypatch.setattr('pokesim.app.manager.STREAM_RECHECK_SECONDS', 0)
    auth = game.library.manager.auth
    dave_id = auth.user_by_name('dave')['id']

    async def frames():
        yield b'--frame\r\n1'
        auth.revoke_grant(game.red, dave_id)
        for _ in range(5):
            yield b'--frame\r\n2'

    # The library fixture already replaced httpx.AsyncClient, so start from the real class.
    original = httpx._client.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=frames())), **kwargs))
    with game.dave.stream('GET', f'/games/{game.red}/stream') as response:
        body = b''.join(response.iter_bytes())
    assert body.count(b'--frame') == 1


def test_the_game_page_learns_there_is_a_lease(game, monkeypatch):
    import httpx
    from pokesim.web.pages import LEASE_META, SPRITE_META, SPRITE_VERSION
    page = f'<head>{SPRITE_META % SPRITE_VERSION}</head>'
    original = httpx._client.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, html=page)), **kwargs))
    assert LEASE_META in game.bob.get(f'/games/{game.red}/').text
    monkeypatch.setattr(lease_module.Leases, 'enforced', property(lambda self: False))
    assert LEASE_META not in game.bob.get(f'/games/{game.red}/').text


def test_watchers_never_learn_the_other_side_of_a_trade(game, monkeypatch):
    coordinator = game.library.manager.coordinator
    row = {'id': 't', 'peer_id': 'peer-xyz', 'peer_name': 'Secret adventure', 'failure_reason': 'Their box was full'}
    monkeypatch.setattr(coordinator, '_adventure_status', lambda aid: {
        'adventure': {}, 'active': [row], 'queued': [], 'recent_failures': [row], 'history': [row],
        'attention': {'message': 'Trade with Secret adventure failed', 'reason': 'box'}, 'auto_enabled': False})
    assert coordinator.adventure_status(game.red)['history'][0]['peer_name'] == 'Secret adventure'
    hidden = coordinator.adventure_status(game.red, watcher=True)
    assert 'Secret' not in repr(hidden) and 'peer-xyz' not in repr(hidden) and 'box' not in repr(hidden)


def test_an_old_view_link_becomes_a_share_link(library):  # noqa: F811
    from pokesim.app.registry import identifier
    row = library.manager.registry.create('Old', 'fixture', {}, identifier())
    admin = library.user('admin', 'admin')
    library.manager.bind_library_owner(admin['id'])
    client = library.login('admin')
    sharing = client.get(f"/api/v1/adventures/{row['id']}/sharing").json()
    assert sharing['legacy'] == {'path': f"/view/{row['id']}/"}
    made = client.post(f"/api/v1/adventures/{row['id']}/shares", json={'legacy': True})
    assert made.status_code == 200 and '/s/' in made.json()['url']
    assert client.get(f"/api/v1/adventures/{row['id']}/sharing").json()['legacy'] is None
    fresh = library.adventure('New', admin)
    assert client.get(f'/api/v1/adventures/{fresh}/sharing').json()['legacy'] is None


def test_without_accounts_take_control_needs_no_lease(tmp_path):
    from pokesim.app.manager import Manager
    manager = Manager(tmp_path, 'http://testserver', auth='none')
    try:
        assert not manager.leases.enforced
        with pytest.raises(lease_module.LeaseRefused):
            manager.leases.act('x', policy.Actor(None, {}), {}, 'request')
    finally:
        manager.close()
