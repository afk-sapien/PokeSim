"""Accounts: setup, login, invites, who sees and controls which adventure, share links and sign-in providers."""
import ipaddress
import os
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim.app import policy
from pokesim.app.accounts import USER_LOCKOUT
from pokesim.app.auth import Limiter
from pokesim.app.cli import reset_password, run
from pokesim.app.manager import Manager, create_app
from pokesim.app.providers import OIDC, ProxyAuth, forwarded_client, proxy_networks
from pokesim.app.registry import identifier

PASSWORD = 'correct horse battery'


class Library:
    def __init__(self, manager, app, client, forwarded):
        self.manager, self.app, self.client, self.forwarded = manager, app, client, forwarded

    def browser(self):
        """Another browser on the same app, with its own cookies."""
        client = TestClient(self.app)
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        return client

    def user(self, name, role='member', **options):
        return self.manager.auth.create_user(name, PASSWORD, role=role, **options)

    def login(self, name, password=PASSWORD):
        client = self.browser()
        response = client.post('/api/v1/auth/login', json={'username': name, 'password': password})
        assert response.status_code == 200, response.text
        client.headers['X-PokeSim-CSRF'] = response.json()['csrf_token']
        return client

    def adventure(self, name, owner):
        row = self.manager.registry.create(name, 'fixture', {}, identifier(), owner=owner['id'])
        self.manager.registry.update(row['id'], state='running')
        return row['id']


@pytest.fixture
def library(tmp_path, monkeypatch):
    for name in ('AUTH', 'OIDC_ISSUER', 'AUTH_PROXY_HEADER', 'DISABLE_PASSWORD_LOGIN'):
        monkeypatch.delenv(name, raising=False)
    manager = Manager(tmp_path, 'http://testserver', auth='accounts')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('fixture', 'sha1', 'red')
    forwarded = []

    async def worker(request):
        forwarded.append(request)
        return httpx.Response(200, json={'ok': True})

    original_client = httpx.AsyncClient
    monkeypatch.setattr('pokesim.app.manager.httpx.AsyncClient',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(worker), **kwargs))
    monkeypatch.setattr(manager.supervisor, 'child',
                        lambda aid: SimpleNamespace(url='http://127.0.0.1:12345', token='private-worker-token',
                                                    request=lambda *args, **kwargs: {'ok': True}))
    app = create_app(manager)
    with TestClient(app) as client:
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        yield Library(manager, app, client, forwarded)


@pytest.fixture
def meanwhile(monkeypatch):
    """Queue a change that runs while the next request body streams, after the access middleware
    read who is asking and before the handler acts."""
    from starlette.requests import Request
    stream = Request.stream
    changes = []

    async def streaming(self):
        while changes:
            changes.pop(0)()
        async for chunk in stream(self):
            yield chunk
    monkeypatch.setattr(Request, 'stream', streaming)
    return changes.append


@pytest.fixture
def people(library):
    """An admin, two members, and one adventure for each member."""
    admin = library.user('admin', 'admin')
    library.manager.bind_library_owner(admin['id'])
    alice, bob = library.user('alice'), library.user('bob')
    return SimpleNamespace(admin=admin, alice=alice, bob=bob,
                           red=library.adventure('Red', alice), blue=library.adventure('Blue', bob))


def test_every_library_route_declares_an_action(library):
    declared = set(policy.ROUTE_ACTIONS)
    served = {(method, route.path) for route in library.app.routes if isinstance(route, APIRoute)
              for method in route.methods}
    assert served - declared == set()
    assert declared - served == set()


def test_game_actions_deny_what_they_do_not_know():
    assert policy.game_action('GET', 'api/state') == 'adventure.watch'
    assert policy.game_action('GET', 'api/states') == 'adventure.manage'
    assert policy.game_action('POST', 'api/control', 'press') == 'adventure.play'
    assert policy.game_action('POST', 'api/control', 'format_disk') is None
    assert policy.game_action('POST', 'api/control', None) is None
    assert policy.game_action('POST', 'internal/shutdown') is None
    assert policy.game_action('DELETE', 'api/state') is None


def test_a_fresh_library_asks_for_setup_and_needs_the_logged_code(library):
    client = library.client
    assert client.get('/', follow_redirects=False).headers['location'] == '/setup'
    refused = client.get('/api/v1/adventures')
    assert refused.status_code == 401 and refused.json()['code'] == 'setup_required'
    wrong = client.post('/api/v1/auth/setup', json={'username': 'admin', 'password': PASSWORD, 'code': 'nope'})
    assert wrong.status_code == 401
    code = library.manager.setup_code.issue()
    made = client.post('/api/v1/auth/setup', json={'username': 'admin', 'password': PASSWORD, 'code': code})
    assert made.status_code == 200 and made.json()['role'] == 'admin'
    client.headers['X-PokeSim-CSRF'] = made.json()['csrf_token']
    assert client.get('/api/v1/adventures').status_code == 200
    again = library.browser().post('/api/v1/auth/setup', json={'username': 'second', 'password': PASSWORD, 'code': code})
    assert again.status_code == 409


def test_setup_gives_older_adventures_to_the_first_admin(library):
    older = library.manager.registry.create('Before accounts', 'fixture', {}, identifier())
    code = library.manager.setup_code.issue()
    made = library.client.post('/api/v1/auth/setup', json={'username': 'admin', 'password': PASSWORD, 'code': code})
    assert library.manager.registry.adventure(older['id'])['owner_id'] == made.json()['user']['id']


def test_login_refuses_wrong_passwords_and_then_slows_down(library, people):
    client = library.browser()
    for _ in range(5):
        assert client.post('/api/v1/auth/login', json={'username': 'alice', 'password': 'wrong password'}).status_code == 401
    limited = client.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD})
    assert limited.status_code == 429 and 'Retry-After' in limited.headers


def browser_at(library, host, **headers):
    """A browser that connects from `host`, sending `headers` on every request."""
    client = TestClient(library.app, client=(host, 50000), headers=headers)
    client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
    return client


def test_a_trusted_proxy_names_the_client_and_nobody_else_can():
    networks = proxy_networks('198.51.100.5, 198.51.100.64/26')
    assert forwarded_client('198.51.100.5', '203.0.113.9', networks) == '203.0.113.9'
    assert forwarded_client('198.51.100.6', '203.0.113.9', networks) == '198.51.100.6'
    # A client writes what it likes at the left. Only the hop the proxy added counts.
    assert forwarded_client('198.51.100.5', '203.0.113.66, 203.0.113.9', networks) == '203.0.113.9'
    assert forwarded_client('198.51.100.5', '203.0.113.9, 198.51.100.70', networks) == '203.0.113.9'
    assert forwarded_client('198.51.100.5', 'not an address', networks) == '198.51.100.5'
    assert forwarded_client('198.51.100.5', '', networks) == '198.51.100.5'
    # Hops with a port or brackets, and a proxy seen through a dual stack socket, still count.
    assert forwarded_client('198.51.100.5', '203.0.113.9:4711', networks) == '203.0.113.9'
    assert forwarded_client('198.51.100.5', '[2001:db8::9]:443', networks) == '2001:db8::9'
    assert forwarded_client('198.51.100.5', '[2001:db8::9]', networks) == '2001:db8::9'
    assert forwarded_client('::ffff:198.51.100.5', '203.0.113.9', networks) == '203.0.113.9'
    assert forwarded_client('198.51.100.5', '203.0.113.9, ::ffff:198.51.100.70', networks) == '203.0.113.9'
    assert forwarded_client('::ffff:198.51.100.6', '203.0.113.9', networks) == '198.51.100.6'
    with pytest.raises(ValueError, match='every address'):
        proxy_networks('0.0.0.0/0')


def test_a_client_from_the_default_gateway_cannot_pick_its_address(library, people):
    """Docker NATs direct clients to the gateway, which a wide trusted network may contain."""
    import ipaddress
    library.manager.trusted_proxies = proxy_networks('198.51.100.0/24')
    library.manager.gateways = {ipaddress.ip_address('198.51.100.1')}
    for number in range(5):
        # Each guess claims a new address, but all of them count against the gateway.
        guesser = browser_at(library, '198.51.100.1', **{'X-Forwarded-For': f'203.0.113.{number + 1}'})
        guesser.post('/api/v1/auth/login', json={'username': 'bob', 'password': 'wrong password'})
    fresh = browser_at(library, '198.51.100.1', **{'X-Forwarded-For': '203.0.113.99'})
    assert fresh.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 429
    # The proxy itself, elsewhere in the network, still names its clients.
    proxied = browser_at(library, '198.51.100.5', **{'X-Forwarded-For': '203.0.113.50'})
    assert proxied.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    assert library.manager.auth.sessions(people.alice['id'])[0]['ip'] == '203.0.113.50'


def test_failed_logins_behind_the_proxy_lock_out_only_the_client_that_made_them(library, people):
    library.manager.trusted_proxies = proxy_networks('198.51.100.5')
    guesser = browser_at(library, '198.51.100.5', **{'X-Forwarded-For': '203.0.113.9'})
    for _ in range(5):
        assert guesser.post('/api/v1/auth/login', json={'username': 'bob', 'password': 'wrong password'}).status_code == 401
    assert guesser.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 429
    neighbour = browser_at(library, '198.51.100.5', **{'X-Forwarded-For': '203.0.113.10'})
    assert neighbour.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    assert library.manager.auth.sessions(people.alice['id'])[0]['ip'] == '203.0.113.10'
    # A peer that is not the proxy cannot pick its own address.
    spoofer = browser_at(library, '198.51.100.6', **{'X-Forwarded-For': '203.0.113.11'})
    assert spoofer.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    assert library.manager.auth.sessions(people.alice['id'])[0]['ip'] == '198.51.100.6'


def test_guesses_from_everywhere_slow_an_account_by_a_minute_at_most(library, people, monkeypatch):
    # Held still, since two dozen password checks on a slow runner can outlast the minute.
    now = time.time()
    monkeypatch.setattr('pokesim.app.auth.time', SimpleNamespace(time=lambda: now))
    own = browser_at(library, '198.51.100.20')
    first = own.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD})
    assert first.status_code == 200
    own.headers['X-PokeSim-CSRF'] = first.json()['csrf_token']
    for number in range(12):
        stranger = browser_at(library, f'203.0.113.{number + 1}')
        assert stranger.post('/api/v1/auth/login', json={'username': 'alice', 'password': 'wrong'}).status_code in {401, 429}
    waiting = browser_at(library, '203.0.113.100').post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD})
    assert waiting.status_code == 429 and int(waiting.headers['Retry-After']) <= USER_LOCKOUT + 1
    # Another browser at the address Alice has a session from still waits, as does one with a
    # forged cookie.
    for cookie in (None, own.cookies.get('pokesim_known') + 'x'):
        other = browser_at(library, '198.51.100.20')
        if cookie:
            other.cookies.set('pokesim_known', cookie, path='/api/v1/auth/login')
        assert other.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 429
    # The browser Alice logged in from before is not made to wait.
    assert own.post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    # Her cookie does not let a browser past the wait on another account.
    for number in range(12):
        browser_at(library, f'203.0.113.{number + 1}').post(
            '/api/v1/auth/login', json={'username': 'bob', 'password': 'wrong'})
    copied = browser_at(library, '198.51.100.20')
    copied.cookies.set('pokesim_known', own.cookies.get('pokesim_known'), path='/api/v1/auth/login')
    assert copied.post('/api/v1/auth/login', json={'username': 'bob', 'password': PASSWORD}).status_code == 429


def test_a_known_browser_stops_counting_when_sessions_end_or_time_runs_out(library, people, monkeypatch):
    from types import SimpleNamespace
    from pokesim.app import auth as auth_module
    auth, uid = library.manager.auth, people.alice['id']
    now = [1_000_000_000.0]
    monkeypatch.setattr(auth_module, 'time', SimpleNamespace(time=lambda: now[0]))
    cookie = auth.known_browser(uid)
    assert auth.browser_knows(cookie, uid)
    now[0] += auth_module.KNOWN_SECONDS + 1
    assert not auth.browser_knows(cookie, uid)
    # A new password, an admin ending her sessions, or every session ending at once forgets it too.
    for forget in (lambda: auth.set_password(uid, 'another password 1'), lambda: auth.end_sessions(uid),
                   auth.end_all_sessions):
        cookie = auth.known_browser(uid)
        assert auth.browser_knows(cookie, uid)
        forget()
        assert not auth.browser_knows(cookie, uid)


def test_stylesheets_and_health_checks_skip_the_account_lookups(library, people, monkeypatch):
    looked_up = []
    original = library.manager.actor
    monkeypatch.setattr(library.manager, 'actor', lambda request: looked_up.append(request.url.path) or original(request))
    client = library.login('alice')
    looked_up.clear()
    assert client.get('/health/live').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert looked_up == []
    assert client.get('/api/v1/adventures').status_code == 200
    assert looked_up == ['/api/v1/adventures']


def test_a_quiet_key_forgets_its_failures(monkeypatch):
    clock = SimpleNamespace(time=lambda: 1000.0)
    monkeypatch.setattr('pokesim.app.auth.time', clock)
    limiter = Limiter()
    for _ in range(20):
        limiter.fail('user:alice', longest=60)
    assert 0 < limiter.wait('user:alice') <= 61
    for _ in range(20):
        limiter.fail('ip:203.0.113.1')
    assert limiter.wait('ip:203.0.113.1') > 61
    clock.time = lambda: 1000.0 + Limiter.LONGEST * 3
    limiter.fail('ip:203.0.113.1')
    assert limiter.kinds['ip']['ip:203.0.113.1'][0] == 1 and limiter.wait('ip:203.0.113.1') == 0


def test_a_flood_of_new_keys_keeps_the_counts_that_matter():
    limiter = Limiter()
    for _ in range(Limiter.FREE - 1):
        limiter.fail('user:alice')
    # One guess each from thousands of made-up addresses, three keys per guess, fills the table.
    for number in range(Limiter.KEEP // 2):
        limiter.fail(f'ip:198.51.{number}', f'pair:198.51.{number} bob', f'user:nobody{number}')
    # Alice's count still stands, so the next guess locks her account.
    limiter.fail('user:alice', longest=60)
    assert limiter.wait('user:alice') > 0
    assert len(limiter.kinds['ip']) <= Limiter.KEEP


def test_the_oldest_key_of_a_kind_goes_first(monkeypatch):
    monkeypatch.setattr(Limiter, 'KEEP', 3)
    limiter = Limiter()
    for key in ('ip:a', 'ip:b', 'ip:c', 'ip:a', 'ip:d'):
        limiter.fail(key)
    assert list(limiter.kinds['ip']) == ['ip:c', 'ip:a', 'ip:d']


def test_logout_ends_the_session(library, people):
    alice = library.login('alice')
    assert alice.get('/api/v1/adventures').status_code == 200
    assert alice.post('/api/v1/auth/logout').status_code == 200
    assert alice.get('/api/v1/adventures').status_code == 401


def test_members_see_only_their_own_and_granted_adventures(library, people):
    alice = library.login('alice')
    shown = {row['id']: row['access'] for row in alice.get('/api/v1/adventures').json()['adventures']}
    assert shown == {people.red: 'owner'}
    assert alice.get(f'/api/v1/adventures/{people.blue}').status_code == 404
    assert alice.post(f'/api/v1/adventures/{people.blue}/stop', json={}).status_code == 404
    library.manager.auth.grant(people.blue, people.alice['id'], 'viewer', people.bob['id'])
    shown = {row['id']: row['access'] for row in alice.get('/api/v1/adventures').json()['adventures']}
    assert shown == {people.red: 'owner', people.blue: 'viewer'}
    assert alice.post(f'/api/v1/adventures/{people.blue}/stop', json={}).status_code == 403
    admin = library.login('admin')
    assert {row['id'] for row in admin.get('/api/v1/adventures').json()['adventures']} == {people.red, people.blue}


def test_watchers_read_the_game_but_only_whoever_holds_control_presses_buttons(library, people):
    library.manager.auth.grant(people.blue, people.alice['id'], 'viewer', people.bob['id'])
    alice, bob = library.login('alice'), library.login('bob')
    assert alice.get(f'/games/{people.blue}/api/state').status_code == 200
    assert alice.post(f'/games/{people.blue}/api/control', json={'action': 'press', 'button': 'a'}).status_code == 403
    assert alice.get(f'/games/{people.blue}/api/states').status_code == 403
    assert bob.post(f'/games/{people.blue}/api/control', json={'action': 'press', 'button': 'a'}).status_code == 409
    assert bob.post(f'/games/{people.blue}/api/lease', json={'action': 'request'}).json()['you_hold']
    assert bob.post(f'/games/{people.blue}/api/control', json={'action': 'press', 'button': 'a'}).status_code == 200
    assert bob.post(f'/games/{people.blue}/api/control', json={'action': 'unknown'}).status_code == 404
    assert alice.get(f'/games/{people.red}/api/state').status_code == 200
    stranger = library.browser()
    assert stranger.get(f'/games/{people.red}/api/state').status_code == 401
    page = stranger.get(f'/games/{people.red}/', follow_redirects=False)
    assert page.status_code in {303, 307} and page.headers['location'].startswith('/login?next=')


def test_a_role_lost_while_the_game_request_streams_counts(library, people, meanwhile):
    auth, bob = library.manager.auth, library.login('bob')
    auth.grant(people.red, people.bob['id'], 'manager', people.alice['id'])
    meanwhile(lambda: auth.grant(people.red, people.bob['id'], 'player', people.alice['id']))
    paused = bob.post(f'/games/{people.red}/api/control', json={'action': 'pause'})
    assert paused.status_code == 403, paused.text
    meanwhile(lambda: auth.grant(people.red, people.bob['id'], 'viewer', people.alice['id']))
    asked = bob.post(f'/games/{people.red}/api/lease', json={'action': 'request'})
    assert asked.status_code == 403, asked.text
    assert not library.manager.leases.holds(people.red, library.manager.actor_for(people.bob))


def test_admin_only_routes_refuse_members(library, people):
    alice = library.login('alice')
    for method, path in [('GET', '/api/v1/users'), ('GET', '/api/v1/backups'), ('POST', '/api/v1/backups'),
                         ('GET', '/api/v1/notifications'), ('POST', '/api/v1/invites'), ('PATCH', '/api/v1/settings')]:
        assert alice.request(method, path, json={}).status_code == 403, path
    assert 'data_dir' not in alice.get('/api/v1/settings').json()
    assert 'data_dir' in library.login('admin').get('/api/v1/settings').json()


def test_a_new_adventure_belongs_to_whoever_made_it(library, people, monkeypatch):
    library.manager.auth.update_user(people.bob['id'], can_create=False)
    bob = library.login('bob')
    refused = bob.post('/api/v1/adventures', json={'name': 'Nope', 'rom_id': 'fixture', 'request_id': identifier()})
    assert refused.status_code == 403
    alice = library.login('alice')
    made = alice.post('/api/v1/adventures', json={'name': 'Mine', 'rom_id': 'fixture', 'request_id': identifier()})
    assert made.status_code == 200, made.text
    assert library.manager.registry.adventure(made.json()['id'])['owner_id'] == people.alice['id']


def test_an_invite_makes_one_member(library, people):
    admin = library.login('admin')
    url = admin.post('/api/v1/invites', json={}).json()['url']
    token = url.rsplit('/', 1)[1]
    guest = library.browser()
    assert guest.get(f'/invite/{token}').status_code == 200
    joined = guest.post('/api/v1/auth/invite', json={'token': token, 'username': 'carol', 'password': PASSWORD})
    assert joined.status_code == 200 and joined.json()['role'] == 'member'
    again = library.browser().post('/api/v1/auth/invite', json={'token': token, 'username': 'dave', 'password': PASSWORD})
    assert again.status_code == 409
    assert library.browser().get(f'/invite/{token}').status_code == 404


def test_a_share_link_opens_one_adventure_view_only(library, people):
    alice = library.login('alice')
    url = alice.post(f'/api/v1/adventures/{people.red}/shares', json={}).json()['url']
    visitor = library.browser()
    opened = visitor.get(urlsplit(url).path, follow_redirects=False)
    assert opened.status_code == 303 and opened.headers['location'] == f'/view/{people.red}/'
    assert visitor.get(f'/view/{people.red}/api/state').status_code == 200
    assert visitor.get(f'/games/{people.red}/api/state').status_code == 401
    assert visitor.get(f'/view/{people.blue}/api/state').status_code in {401, 404}
    assert visitor.get('/api/v1/adventures').status_code == 401
    share_id = alice.get(f'/api/v1/adventures/{people.red}/sharing').json()['shares'][0]['id']
    alice.delete(f'/api/v1/adventures/{people.red}/shares/{share_id}')
    assert visitor.get(f'/view/{people.red}/api/state').status_code == 401
    # A turned-off link sends a browser opening the page to the login, not to a JSON error.
    page = visitor.get(f'/view/{people.red}/', follow_redirects=False)
    assert page.status_code == 303 and page.headers['location'].startswith('/login?')


def test_only_the_owner_manages_sharing(library, people):
    alice, bob = library.login('alice'), library.login('bob')
    assert bob.get(f'/api/v1/adventures/{people.red}/sharing').status_code == 404
    granted = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'viewer'})
    assert granted.status_code == 200
    assert bob.get(f'/api/v1/adventures/{people.red}/sharing').status_code == 403
    playing = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'player'})
    assert playing.status_code == 200
    assert bob.get(f'/api/v1/adventures/{people.red}/sharing').status_code == 403
    owning = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'owner'})
    assert owning.status_code in {409, 422}


def test_sharing_needs_a_real_person(library, people):
    alice = library.login('alice')
    for user_id in ({}, ['x'], 42, 'f' * 32):
        refused = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': user_id, 'role': 'viewer'})
        assert refused.status_code == 409 and refused.json()['detail'] == 'Choose a person to share with', user_id
    library.manager.auth.update_user(people.bob['id'], disabled=True)
    refused = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'viewer'})
    assert refused.status_code == 409
    assert library.manager.auth.grants_for(people.bob['id']) == {}


def test_trades_stay_between_one_owners_adventures(library, people):
    alice = library.login('alice')
    refused = alice.post('/api/v1/interactions/trades', json={'left_id': people.red, 'right_id': people.blue})
    assert refused.status_code == 404
    library.manager.auth.grant(people.blue, people.alice['id'], 'viewer', people.bob['id'])
    refused = alice.post('/api/v1/interactions/trades', json={'left_id': people.red, 'right_id': people.blue})
    assert refused.status_code == 403
    assert alice.get(f'/api/v1/interactions/trade-builder/pokemon?adventure_id={people.blue}').status_code == 403
    status = alice.get('/api/v1/interactions').json()
    assert status['participants'] == [people.red] and status['attention'] is None


def test_the_api_reference_is_for_admins_only(library, people):
    stranger, alice, admin = library.browser(), library.login('alice'), library.login('admin')
    for path in ('/docs', '/openapi.json'):
        assert stranger.get(path).status_code == 404, path
        assert alice.get(path).status_code == 404, path
        assert admin.get(path).status_code == 200, path
    schema = admin.get('/openapi.json').json()
    assert '/api/v1/adventures' in schema['paths'] and '/docs' not in schema['paths']
    page = admin.get('/docs').text
    assert '/api/v1/users/{uid}' in page and 'library.users' in page and '<script' not in page


def test_without_accounts_the_api_reference_stays_off_unless_turned_on(tmp_path, monkeypatch):
    monkeypatch.delenv('API_DOCS', raising=False)
    manager = Manager(tmp_path, 'http://testserver', auth='none')
    monkeypatch.setattr(manager, 'start', lambda: None)
    client = TestClient(create_app(manager))
    assert client.get('/docs').status_code == 404 and client.get('/openapi.json').status_code == 404
    monkeypatch.setenv('API_DOCS', '1')
    assert client.get('/docs').status_code == 200 and client.get('/openapi.json').status_code == 200
    manager.close()


def older_library(root):
    """A Library as 0.6.x left it: tables on schema 1, and nothing that says this PokeSim made it."""
    import sqlite3
    Manager(root).close()
    db = sqlite3.connect(root / 'app.sqlite')
    with db:
        db.execute("DELETE FROM settings WHERE key='created_schema'")
        db.execute('PRAGMA user_version=1')
    db.close()


def test_upgrades_stay_open_and_new_libraries_log_in(tmp_path, monkeypatch):
    for name in ('AUTH', 'POKESIM_ADMIN_USER', 'POKESIM_ADMIN_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    older = tmp_path / 'older'
    older_library(older)
    reopened = Manager(older, auth='auto')
    assert reopened.auth_mode == 'none'
    reopened.close()
    fresh = Manager(tmp_path / 'fresh', auth='auto')
    assert fresh.auth_mode == 'accounts' and fresh.needs_setup
    fresh.close()
    monkeypatch.setenv('AUTH', 'accounts')
    asked = Manager(older, auth='auto')
    assert asked.auth_mode == 'accounts'
    asked.close()


def test_an_upgrade_with_an_admin_in_the_environment_logs_in(tmp_path, monkeypatch):
    """.env.example sets both, and the Library stayed open while the admin was never made."""
    monkeypatch.delenv('AUTH', raising=False)
    older_library(tmp_path)
    monkeypatch.setenv('POKESIM_ADMIN_USER', 'owner')
    monkeypatch.setenv('POKESIM_ADMIN_PASSWORD', PASSWORD)
    upgraded = Manager(tmp_path, auth='auto')
    assert upgraded.auth_mode == 'accounts'
    assert upgraded.bootstrap_admin('owner', PASSWORD)['role'] == 'admin'
    upgraded.close()
    # One of the two alone creates nobody, so it does not lock the Library.
    second = tmp_path / 'second'
    older_library(second)
    monkeypatch.delenv('POKESIM_ADMIN_PASSWORD')
    half = Manager(second, auth='auto')
    assert half.auth_mode == 'none'
    half.close()


def test_a_new_library_that_an_import_made_first_still_logs_in(tmp_path, monkeypatch):
    monkeypatch.delenv('AUTH', raising=False)
    # `pokesim import` into an empty data directory opens the Library first, without accounts.
    with pytest.raises(ValueError, match='pokesim.sqlite'):
        run(SimpleNamespace(command='import', data_dir=tmp_path / 'library', source=tmp_path / 'missing',
                            rom=tmp_path / 'missing.gb', name='Red', stopped=True))
    assert (tmp_path / 'library' / 'app.sqlite').exists()
    server = Manager(tmp_path / 'library', auth='auto')
    assert server.auth_mode == 'accounts' and server.needs_setup
    server.close()


def test_the_environment_can_create_the_first_admin(library):
    user = library.manager.bootstrap_admin('owner', PASSWORD)
    assert user['role'] == 'admin' and not library.manager.needs_setup
    assert library.manager.bootstrap_admin('another', PASSWORD) is None
    library.login('owner')


def test_reset_password_from_the_command_line(library, people):
    alice = library.login('alice')
    result = reset_password(library.manager.root, 'alice')
    # The command runs in its own process. The server notices within SESSION_CACHE_SECONDS.
    library.manager.auth.cache.clear()
    assert alice.get('/api/v1/adventures').status_code == 401
    assert library.browser().post('/api/v1/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 401
    library.login('alice', result['password'])
    with pytest.raises(ValueError):
        reset_password(library.manager.root, 'nobody')
    # The row that holds adventures for the owner of an older Library is nobody to log in as.
    with pytest.raises(ValueError, match='No user is called'):
        reset_password(library.manager.root, '#library-owner')


def test_cookieless_session_requests_cannot_lock_out_new_browsers(library, people):
    """About 1024 of them filled the table for a day, and every new browser got 429 and no CSRF token."""
    flood = TestClient(library.app)
    for _ in range(1100):
        flood.cookies.clear()
        assert flood.get('/api/v1/session').status_code == 200
    # Many addresses at once push out the oldest, not the newcomer.
    for number in range(1100):
        library.manager.anonymous_session(None, f'10.0.{number // 250}.{number % 250}')
    assert len(library.manager.sessions) <= 1024
    newest = max(library.manager.sessions.values(), key=lambda session: session['expires'])
    # Until a login it lasts an hour, not a day.
    assert newest['expires'] <= time.time() + 3600
    library.login('alice')


def test_the_cli_token_acts_as_the_first_admin(library, people):
    token = library.manager.issue_cli_token()
    if os.name != 'nt':  # Windows has no POSIX permission bits.
        assert (library.manager.root / 'cli.token').stat().st_mode & 0o077 == 0
    command = TestClient(library.app)
    assert command.get('/api/v1/users').status_code == 401
    command.headers['X-PokeSim-CLI-Token'] = token
    assert command.get('/api/v1/users').status_code == 200
    command.headers['X-PokeSim-CLI-Token'] = 'x' * len(token)
    assert command.get('/api/v1/users').status_code == 401


def test_deleting_the_first_admin_makes_the_deleting_admin_the_library_owner(library, people):
    second = library.user('second', 'admin')
    assert library.manager.default_owner() == people.admin['id']
    deleting = library.login('second')
    assert deleting.request('DELETE', f'/api/v1/users/{people.admin["id"]}', json={'adventures': {}}).status_code == 200
    assert library.manager.default_owner() == second['id']
    # An adventure the command line imports now belongs to someone who can see it.
    token = library.manager.issue_cli_token()
    command = TestClient(library.app, headers={'X-PokeSim-CLI-Token': token})
    assert command.get('/api/v1/session').json()['user']['id'] == second['id']


def test_startup_rebinds_a_deleted_library_owner_and_its_adventures(library, people):
    from pokesim.app.registry import LIBRARY_OWNER
    manager = library.manager
    second = library.user('second', 'admin')
    # A Library from before this fix: the bound owner is gone and an import went to the placeholder.
    manager.auth.set_setting('library_owner', identifier())
    stranded = manager.registry.create('Imported', 'fixture', {}, identifier(), owner=LIBRARY_OWNER)
    assert manager.default_owner() == LIBRARY_OWNER
    manager.bind_library_owner()
    assert manager.default_owner() == people.admin['id'] != second['id']
    assert manager.registry.adventure(stranded['id'])['owner_id'] == people.admin['id']


@pytest.mark.parametrize('change', [{'disabled': True}, {'role': 'member'}], ids=['disabled', 'demoted'])
def test_turning_off_the_library_owner_hands_it_to_the_admin_who_did(library, people, change):
    from pokesim.app.registry import LIBRARY_OWNER
    manager = library.manager
    second = library.user('second', 'admin')
    library.user('third', 'admin')
    changed = library.login('second').patch(f'/api/v1/users/{people.admin["id"]}', json=change)
    assert changed.status_code == 200, changed.text
    assert manager.default_owner() == second['id']
    # `pokesim backup` and the other commands act as an admin who can still log in.
    token = manager.issue_cli_token()
    command = TestClient(library.app, headers={'X-PokeSim-CLI-Token': token})
    assert command.get('/api/v1/users').status_code == 200
    # Startup gives what is left on the placeholder to that admin, not to the one turned off.
    stranded = manager.registry.create('Imported', 'fixture', {}, identifier(), owner=LIBRARY_OWNER)
    manager.bind_library_owner()
    assert manager.registry.adventure(stranded['id'])['owner_id'] == second['id']


def test_startup_rebinds_a_disabled_library_owner(library, people):
    from pokesim.app.registry import LIBRARY_OWNER
    manager = library.manager
    second = library.user('second', 'admin')
    # A Library from before this fix: the bound owner was disabled and the setting kept them.
    with manager.auth.lock, manager.auth.db:
        manager.auth.db.execute('UPDATE users SET disabled=1 WHERE id=?', (people.admin['id'],))
    stranded = manager.registry.create('Imported', 'fixture', {}, identifier(), owner=LIBRARY_OWNER)
    manager.bind_library_owner()
    assert manager.default_owner() == second['id']
    assert manager.registry.adventure(stranded['id'])['owner_id'] == second['id']


def test_the_first_admin_a_proxy_names_owns_the_older_library_at_once(library):
    """Without the bind, older adventures and ROMs stayed on the placeholder until the next start."""
    manager = library.manager
    older = manager.registry.create('Older', 'fixture', {}, identifier())
    assert manager.needs_setup
    carol = manager.proxy_user('carol', 'admin')
    assert manager.default_owner() == carol['id']
    assert manager.registry.adventure(older['id'])['owner_id'] == carol['id']
    assert manager.registry.owns_rom('fixture', carol['id'])
    # A later admin from the proxy does not take the Library over.
    dave = manager.proxy_user('dave', 'admin')
    assert manager.default_owner() == carol['id'] != dave['id']


def request_from(host, headers):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={key.lower(): value for key, value in headers.items()})


def test_proxy_headers_count_only_from_the_trusted_proxy_with_its_secret():
    proxy = ProxyAuth('Remote-User', 's' * 20, '198.51.100.5/32', groups_header='Remote-Groups', gateways=set())
    sent = {'Remote-User': 'carol', 'Remote-Groups': 'pokesim-admins', ProxyAuth.SECRET_HEADER: 's' * 20}
    assert proxy.identify(request_from('198.51.100.5', sent)) == ('carol', 'admin')
    assert proxy.identify(request_from('198.51.100.6', sent)) is None
    assert proxy.identify(request_from('198.51.100.5', {**sent, ProxyAuth.SECRET_HEADER: 'wrong'})) is None
    assert proxy.identify(request_from('198.51.100.5', {**sent, 'Remote-Groups': 'friends'})) == ('carol', 'member')
    with pytest.raises(ValueError, match='every address'):
        ProxyAuth('Remote-User', 's' * 20, '0.0.0.0/0', gateways=set())
    with pytest.raises(ValueError, match='default gateway'):
        ProxyAuth('Remote-User', 's' * 20, '198.51.100.0/24', gateways={ipaddress.ip_address('198.51.100.1')})
    with pytest.raises(ValueError, match='16 characters'):
        ProxyAuth('Remote-User', 'short', '198.51.100.5/32', gateways=set())


class Provider:
    """A tiny OpenID provider: discovery, keys, and a token endpoint that signs what it is told."""

    issuer = 'https://id.example'

    def __init__(self):
        from joserfc.jwk import RSAKey
        self.key = RSAKey.generate_key(2048, parameters={'kid': 'one', 'use': 'sig'})
        self.claims = {}

    def handle(self, request):
        from joserfc import jwt
        if request.url.path == '/.well-known/openid-configuration':
            return httpx.Response(200, json={'issuer': self.issuer, 'jwks_uri': self.issuer + '/keys',
                                             'authorization_endpoint': self.issuer + '/authorize',
                                             'token_endpoint': self.issuer + '/token',
                                             'id_token_signing_alg_values_supported': ['RS256']})
        if request.url.path == '/keys':
            return httpx.Response(200, json={'keys': [self.key.as_dict(private=False)]})
        if request.url.path == '/token':
            token = jwt.encode({'alg': 'RS256', 'kid': 'one'}, self.claims, self.key)
            return httpx.Response(200, json={'id_token': token})
        return httpx.Response(404)


def test_oidc_logs_in_with_a_checked_id_token(library, people):
    import time
    provider = Provider()
    library.manager.oidc = OIDC(provider.issuer, 'pokesim', 'secret', 'http://testserver/auth/oidc/callback',
                                transport=httpx.MockTransport(provider.handle))
    browser = library.browser()
    start = browser.get('/auth/oidc/login', follow_redirects=False)
    assert start.status_code == 303
    query = parse_qs(urlsplit(start.headers['location']).query)
    assert query['code_challenge_method'] == ['S256']
    state, nonce = query['state'][0], query['nonce'][0]
    now = int(time.time())
    provider.claims = {'iss': provider.issuer, 'sub': 'u-1', 'aud': 'pokesim', 'exp': now + 300, 'iat': now,
                       'nonce': nonce, 'preferred_username': 'erin', 'groups': ['pokesim']}
    done = browser.get(f'/auth/oidc/callback?state={state}&code=abc', follow_redirects=False)
    assert done.status_code == 200, done.text
    session = browser.get('/api/v1/session').json()
    assert session['authenticated'] and session['user']['username'] == 'erin' and session['role'] == 'member'
    replay = library.browser().get(f'/auth/oidc/callback?state={state}&code=abc', follow_redirects=False)
    assert replay.status_code == 401


def test_oidc_refuses_a_token_for_another_login(library, people):
    import time
    provider = Provider()
    library.manager.oidc = OIDC(provider.issuer, 'pokesim', 'secret', 'http://testserver/auth/oidc/callback',
                                transport=httpx.MockTransport(provider.handle))
    browser = library.browser()
    query = parse_qs(urlsplit(browser.get('/auth/oidc/login', follow_redirects=False).headers['location']).query)
    now = int(time.time())
    provider.claims = {'iss': provider.issuer, 'sub': 'u-2', 'aud': 'pokesim', 'exp': now + 300,
                       'nonce': 'someone else', 'groups': ['pokesim']}
    refused = browser.get(f'/auth/oidc/callback?state={query["state"][0]}&code=abc', follow_redirects=False)
    assert refused.status_code == 401
    assert not browser.get('/api/v1/session').json()['authenticated']


def test_accounts_off_keeps_the_open_library(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        session = client.get('/api/v1/session').json()
        assert session['auth'] == 'none' and session['authenticated']
        assert client.get('/api/v1/users').status_code == 200
        assert client.get('/login', follow_redirects=False).status_code == 303
