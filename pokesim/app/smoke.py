"""A live check of a running PokeSim through its real HTTP API.

The admin side uses the command line token, so no admin password is typed or stored. Two
throwaway members come from invites with random passwords held only in memory. Whatever the
check makes, it removes again, also when a check fails or the run stops partway.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import secrets
import time
from types import SimpleNamespace
import uuid

import httpx

# What a refusal may look like. A 404 also hides that the thing exists.
REFUSED = {403, 404}
DOCS = ('/docs', '/openapi.json')


@dataclass
class Report:
    passed: int = 0
    failures: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    mode: str = ''


class Stop(Exception):
    """A step the rest of the run depends on failed. It is already in the report."""


class Smoke:
    def __init__(self, token, connect, rom=None, with_backup=False):
        self.token, self.connect, self.rom, self.with_backup = token, connect, rom, with_backup
        self.report = Report()
        self.clients = []
        self.admin = None
        self.usernames = []
        self.invite_ids = []
        self.adventure = None
        self.cartridge = None

    # Helpers -----------------------------------------------------------------------------------
    def check(self, name, ok, detail=''):
        if ok:
            self.report.passed += 1
        else:
            self.report.failures.append(f'{name}: {detail}' if detail else name)
        return ok

    def expect(self, name, response, statuses):
        statuses = {statuses} if isinstance(statuses, int) else statuses
        wanted = ' or '.join(str(status) for status in sorted(statuses))
        return self.check(name, response.status_code in statuses, f'got {response.status_code}, expected {wanted}')

    def require(self, name, response, status=200):
        if not self.expect(name, response, status):
            raise Stop(name)
        return response.json()

    def browser(self, token=None):
        """A new client with its own cookies and the CSRF token of its session."""
        client = self.connect()
        self.clients.append(client)
        if token:
            client.headers['X-PokeSim-CLI-Token'] = token
        response = client.get('/api/v1/session')
        if response.status_code != 200:
            raise Stop(f'session: got {response.status_code}')
        session = response.json()
        client.headers['X-PokeSim-CSRF'] = session['csrf_token']
        return client, session

    # The run -----------------------------------------------------------------------------------
    def run(self):
        try:
            self.health()
            self.admin, session = self.browser(self.token)
            self.report.mode = session.get('auth', '')
            if self.report.mode == 'none':
                self.open_library(session)
            else:
                self.accounts(session)
        except Stop as stop:
            if not self.report.failures:
                self.report.failures.append(f'stopped early: {stop}')
        except Exception as error:
            self.report.failures.append(f'stopped early: {error}'.replace('\n', ' '))
        finally:
            try:
                self.cleanup()
            finally:
                for client in self.clients:
                    client.close()
        return self.report

    def health(self):
        client = self.connect()
        self.clients.append(client)
        for path in ('/health/live', '/health/ready'):
            response = client.get(path)
            self.expect(path, response, 200)

    def open_library(self, session):
        """AUTH=none: nobody logs in, everyone acts as the admin, and the API reference stays off."""
        self.check('open session is the admin', session.get('role') == 'admin', f"got {session.get('role')}")
        visitor, _ = self.browser()
        self.expect('no login wall on the adventure list', visitor.get('/api/v1/adventures'), 200)
        self.expect('no login wall on the library page', visitor.get('/', follow_redirects=False), 200)
        for path in DOCS:
            self.expect(f'{path} is off without accounts', visitor.get(path), 404)
        self.backups(visitor)
        self.csrf(visitor, '/api/v1/auth/logout', {})

    def accounts(self, session):
        admin = self.admin
        self.check('admin session role', session.get('role') == 'admin' and session.get('authenticated') is True,
                   f"got {session.get('role')}")
        anonymous, _ = self.browser()
        self.expect('anonymous reads of the adventure list need a login', anonymous.get('/api/v1/adventures'), 401)
        for path in DOCS:
            self.expect(f'anonymous {path}', anonymous.get(path), REFUSED)
            self.expect(f'admin {path}', admin.get(path), 200)
        a, b = self.members()
        self.isolation(a, b)
        self.admin_routes(a, b)
        self.csrf(a.client)
        self.backups(admin)
        self.logout(a)
        self.limiter(b)

    def members(self):
        people = []
        for letter in 'AB':
            name, password = f'smoke-{secrets.token_hex(5)}', secrets.token_urlsafe(18)
            self.usernames.append(name)
            made = self.require(f'admin creates invite {letter}', self.admin.post('/api/v1/invites', json={'seconds': 3600}))
            self.invite_ids.append(made['invite']['id'])
            guest, _ = self.browser()
            accepted = self.require(f'member {letter} accepts the invite', guest.post('/api/v1/auth/invite', json={
                'token': made['url'].rsplit('/', 1)[1], 'username': name, 'password': password}))
            client, _ = self.browser()
            login = self.require(f'member {letter} logs in', client.post(
                '/api/v1/auth/login', json={'username': name, 'password': password}))
            client.headers['X-PokeSim-CSRF'] = login['csrf_token']
            current = client.get('/api/v1/session').json()
            self.check(f'member {letter} session role', current.get('role') == 'member'
                       and (current.get('user') or {}).get('username') == name, f"got {current.get('role')}")
            people.append(SimpleNamespace(client=client, id=accepted['user']['id'], name=name, password=password))
        return people

    def isolation(self, a, b):
        """Member A reaches none of member B's adventure, save or inbox. Both see the Library shelf,
        and neither may change it."""
        inbox = a.client.get('/api/v1/inbox')
        self.expect('member A reads their own inbox', inbox, 200)
        other = a.client.get('/api/v1/inbox', params={'user_id': b.id, 'uid': b.id})
        self.check("member A cannot read member B's inbox", other.status_code in REFUSED or other.json() == inbox.json(),
                   f'got {other.status_code}')
        if self.rom is None:
            self.report.skipped.append("member B's adventure and cartridge: no cartridge to add, pass --rom")
            return
        upload = {'content': self.rom, 'headers': {'Content-Type': 'application/octet-stream'}}
        before = self.require('the admin reads the Library shelf', self.admin.get('/api/v1/assets'))['roms']
        self.expect('member B cannot add a cartridge', b.client.post('/api/v1/assets/rom', **upload), REFUSED)
        added = self.require('the admin adds a cartridge', self.admin.post('/api/v1/assets/rom', **upload))
        if added['id'] not in {row['id'] for row in before}:
            if any(row['version'] == added['version'] for row in before):
                # Removal goes by slot, and would take the cartridge that was there first too.
                self.report.skipped.append(f"removing the {added['version']} cartridge it added: that slot had one already")
            else:
                self.cartridge = added['version']
        name = f'Smoke check {secrets.token_hex(3)}'
        made = self.require('member B creates an adventure', b.client.post('/api/v1/adventures', json={
            'name': name, 'rom_id': added['id'], 'request_id': uuid.uuid4().hex}))
        aid = made['id']
        self.adventure = (aid, name)
        # Each change is one the route would turn down anyway, so a broken check changes nothing.
        for verb, method, path, body in [
                ('read', 'GET', f'/api/v1/adventures/{aid}', None),
                ('rename', 'PATCH', f'/api/v1/adventures/{aid}', {'name': name}),
                ('delete', 'DELETE', f'/api/v1/adventures/{aid}', {'confirmation': 'not ' + name}),
                ('read the sharing of', 'GET', f'/api/v1/adventures/{aid}/sharing', None),
                ('list the saves of', 'GET', f'/games/{aid}/api/states', None),
                ('export the save of', 'POST', f'/games/{aid}/api/export-save', {}),
                ('read the trade offers of', 'GET', f'/api/v1/interactions/trade-offers?adventure_id={aid}', None),
                ('read the trading switches of', 'GET', f'/api/v1/interactions/auto-settings?adventure_id={aid}', None),
                ('change the trading switches of', 'PUT', f'/api/v1/interactions/auto-settings?adventure_id={aid}',
                 {'enabled': True})]:
            self.expect(f"member A {verb} member B's adventure", a.client.request(method, path, json=body), REFUSED)
        listed = a.client.get('/api/v1/adventures')
        self.check("member A's list leaves out member B's adventure", listed.status_code == 200
                   and aid not in {row['id'] for row in listed.json()['adventures']}, f'got {listed.status_code}')
        shelf = a.client.get('/api/v1/assets')
        self.check('member A sees the Library cartridge', shelf.status_code == 200
                   and added['id'] in {row['id'] for row in shelf.json()['roms']}, f'got {shelf.status_code}')
        self.expect('member A cannot remove the cartridge',
                    a.client.delete(f"/api/v1/cartridges/{added['version']}"), REFUSED)
        kept = self.admin.get('/api/v1/assets')
        self.check('the Library keeps the cartridge', kept.status_code == 200
                   and added['id'] in {row['id'] for row in kept.json()['roms']}, f'got {kept.status_code}')

    def admin_routes(self, a, b):
        for method, path, body in [
                ('GET', '/api/v1/users', None),
                ('PATCH', f'/api/v1/users/{b.id}', {'display_name': b.name}),
                ('DELETE', f'/api/v1/users/{b.id}', {}),
                ('DELETE', f'/api/v1/users/{b.id}/sessions', None),
                ('GET', '/api/v1/invites', None),
                ('POST', '/api/v1/invites', {'seconds': 1}),
                ('DELETE', f'/api/v1/invites/{self.invite_ids[0]}', None),
                ('GET', '/api/v1/auth/settings', None),
                ('GET', '/api/v1/backups', None),
                *(('GET', path, None) for path in DOCS)]:
            shown = path.replace(b.id, '<B>').replace(self.invite_ids[0], '<invite>')
            self.expect(f'member A {method} {shown}', a.client.request(method, path, json=body), REFUSED)

    def csrf(self, client, path='/api/v1/inbox/read', body=None):
        """Marking the inbox read changes nothing that matters. Without accounts there is no inbox, and
        ending the open session is just as harmless."""
        body = {'all': True} if body is None else body
        refused = client.post(path, json=body, headers={'X-PokeSim-CSRF': ''})
        self.expect('a change without the CSRF token is refused', refused, 403)
        self.expect('the same change with the token goes through', client.post(path, json=body), 200)

    def backups(self, client):
        listed = client.get('/api/v1/backups')
        self.check('backups can be listed', listed.status_code == 200 and isinstance(listed.json().get('backups'), list),
                   f'got {listed.status_code}')
        if self.with_backup:
            self.expect('a backup can be made', client.post('/api/v1/backups', json={}), 200)

    def logout(self, a):
        self.expect('member A logs out', a.client.post('/api/v1/auth/logout'), 200)
        self.expect('after logout the adventure list needs a login', a.client.get('/api/v1/adventures'), 401)
        session = a.client.get('/api/v1/session').json()
        self.check('after logout the session has no user', session.get('authenticated') is False and session.get('role') is None,
                   f"got {session.get('role')}")

    def limiter(self, b):
        """Last, because it slows logins from this address. A right password after the wait clears that again,
        so the next run, or a person behind the same address, starts from nothing."""
        client, _ = self.browser()
        name, password = f'smoke-nobody-{secrets.token_hex(5)}', secrets.token_urlsafe(18)
        responses = [client.post('/api/v1/auth/login', json={'username': name, 'password': password})
                     for _ in range(6)]
        statuses = [response.status_code for response in responses]
        self.check('login limiter gives 401 five times, then 429', statuses == [401] * 5 + [429],
                   'got ' + ' '.join(map(str, statuses)))
        wait = responses[-1].headers.get('Retry-After', '')
        if statuses[-1] == 429 and wait.isdigit():
            time.sleep(min(int(wait), 30))
        self.expect('after the wait a right password logs in', client.post(
            '/api/v1/auth/login', json={'username': b.name, 'password': b.password}), 200)

    # Cleanup -----------------------------------------------------------------------------------
    def cleanup(self):
        if self.admin is None or self.report.mode == 'none':
            return
        admin = self.admin

        def step(name, call, allowed=(200,)):
            try:
                response = call()
            except httpx.HTTPError as error:
                self.report.failures.append(f'cleanup {name}: {error}')
                return None
            if response.status_code not in allowed:
                self.report.failures.append(f'cleanup {name}: got {response.status_code}')
                return None
            return response
        if self.adventure:
            aid, name = self.adventure
            step('the adventure', lambda: admin.request('DELETE', f'/api/v1/adventures/{aid}', json={'confirmation': name}),
                 (200, 404))
        if self.cartridge:
            step('the cartridge', lambda: admin.delete(f'/api/v1/cartridges/{self.cartridge}'), (200, 404))
        if self.usernames:
            users = step('listing users', lambda: admin.get('/api/v1/users'))
            games = step('listing adventures', lambda: admin.get('/api/v1/adventures'))
            owned = games.json()['adventures'] if games is not None else []
            for user in users.json()['users'] if users is not None else []:
                if user['username'] in self.usernames:
                    # An adventure left over from a failed deletion is archived, not lost.
                    plan = {row['id']: 'archive' for row in owned if row.get('owner_id') == user['id']}
                    step(f"user {user['username']}", lambda uid=user['id'], plan=plan: admin.request(
                        'DELETE', f'/api/v1/users/{uid}', json={'adventures': plan}))
        if self.invite_ids:
            pending = step('listing invites', lambda: admin.get('/api/v1/invites'))
            waiting = {row['id'] for row in pending.json()['invites']} if pending is not None else set()
            for iid in self.invite_ids:
                if iid in waiting:
                    step('an invite', lambda iid=iid: admin.delete(f'/api/v1/invites/{iid}'))
        # The command line login made a stored session. It ends here.
        step('the admin session', lambda: admin.post('/api/v1/auth/logout'))


def run(base_url, token, connect=None, rom=None, with_backup=False):
    """Run every check against `base_url` and return the Report."""
    if connect is None:
        def connect():
            return httpx.Client(base_url=base_url.rstrip('/'), trust_env=False, timeout=30)
    return Smoke(token, connect, rom=rom, with_backup=with_backup).run()
