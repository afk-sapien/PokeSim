"""Accounts: setup, login, invites, who sees and controls which adventure, share links and sign-in providers."""
import ipaddress
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import httpx
import pytest

from pokesim.app import policy
from pokesim.app.cli import reset_password
from pokesim.app.manager import Manager, create_app
from pokesim.app.providers import OIDC, ProxyAuth
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
                        lambda aid: SimpleNamespace(url='http://127.0.0.1:12345', token='private-worker-token'))
    app = create_app(manager)
    with TestClient(app) as client:
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        yield Library(manager, app, client, forwarded)


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
    assert policy.game_action('GET', 'api/states') == 'adventure.own'
    assert policy.game_action('POST', 'api/control', 'press') == 'adventure.own'
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


def test_watchers_read_the_game_but_only_the_owner_presses_buttons(library, people):
    library.manager.auth.grant(people.blue, people.alice['id'], 'viewer', people.bob['id'])
    alice, bob = library.login('alice'), library.login('bob')
    assert alice.get(f'/games/{people.blue}/api/state').status_code == 200
    assert alice.post(f'/games/{people.blue}/api/control', json={'action': 'press', 'button': 'a'}).status_code == 403
    assert alice.get(f'/games/{people.blue}/api/states').status_code == 403
    assert bob.post(f'/games/{people.blue}/api/control', json={'action': 'press', 'button': 'a'}).status_code == 200
    assert bob.post(f'/games/{people.blue}/api/control', json={'action': 'unknown'}).status_code == 404
    assert alice.get(f'/games/{people.red}/api/state').status_code == 200
    stranger = library.browser()
    assert stranger.get(f'/games/{people.red}/api/state').status_code == 401
    page = stranger.get(f'/games/{people.red}/', follow_redirects=False)
    assert page.status_code in {303, 307} and page.headers['location'].startswith('/login?next=')


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


def test_only_the_owner_manages_sharing(library, people):
    alice, bob = library.login('alice'), library.login('bob')
    assert bob.get(f'/api/v1/adventures/{people.red}/sharing').status_code == 404
    granted = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'viewer'})
    assert granted.status_code == 200
    assert bob.get(f'/api/v1/adventures/{people.red}/sharing').status_code == 403
    playing = alice.post(f'/api/v1/adventures/{people.red}/grants', json={'user_id': people.bob['id'], 'role': 'player'})
    assert playing.status_code == 409


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


def test_upgrades_stay_open_and_new_libraries_log_in(tmp_path, monkeypatch):
    monkeypatch.delenv('AUTH', raising=False)
    older = tmp_path / 'older'
    Manager(older).close()
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


def test_the_cli_token_acts_as_the_first_admin(library, people):
    token = library.manager.issue_cli_token()
    assert (library.manager.root / 'cli.token').stat().st_mode & 0o077 == 0
    command = TestClient(library.app)
    assert command.get('/api/v1/users').status_code == 401
    command.headers['X-PokeSim-CLI-Token'] = token
    assert command.get('/api/v1/users').status_code == 200
    command.headers['X-PokeSim-CLI-Token'] = 'x' * len(token)
    assert command.get('/api/v1/users').status_code == 401


def request_from(host, headers):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={key.lower(): value for key, value in headers.items()})


def test_proxy_headers_count_only_from_the_trusted_proxy_with_its_secret():
    proxy = ProxyAuth('Remote-User', 's' * 20, '172.20.0.5/32', groups_header='Remote-Groups', gateways=set())
    sent = {'Remote-User': 'carol', 'Remote-Groups': 'pokesim-admins', ProxyAuth.SECRET_HEADER: 's' * 20}
    assert proxy.identify(request_from('172.20.0.5', sent)) == ('carol', 'admin')
    assert proxy.identify(request_from('172.20.0.6', sent)) is None
    assert proxy.identify(request_from('172.20.0.5', {**sent, ProxyAuth.SECRET_HEADER: 'wrong'})) is None
    assert proxy.identify(request_from('172.20.0.5', {**sent, 'Remote-Groups': 'friends'})) == ('carol', 'member')
    with pytest.raises(ValueError, match='every address'):
        ProxyAuth('Remote-User', 's' * 20, '0.0.0.0/0', gateways=set())
    with pytest.raises(ValueError, match='default gateway'):
        ProxyAuth('Remote-User', 's' * 20, '172.20.0.0/16', gateways={ipaddress.ip_address('172.20.0.1')})
    with pytest.raises(ValueError, match='16 characters'):
        ProxyAuth('Remote-User', 'short', '172.20.0.5/32', gateways=set())


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
