"""The common desktop and container application entry point."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.routing import Match, Mount

from ..capability import CoreBackendCapabilityError
from ..checkpoints import CheckpointStore
from ..desktop_setup import MAX_ROM, user_directory
from ..platform_io import lock_file
from ..web.pages import LEASE_META, SPRITE_META, SPRITE_VERSION
from ..web.security import ROLE_HEADER, VIEWER_HEADER, protect_response, public_origin, viewer_allows
from .assets import Assets
from .auth import AuthStore, SetupCode
from . import policy, trade_settings
from .policy import Actor, can
from .registry import LIBRARY_OWNER, Registry, identifier, validate_id
from .supervisor import AdventureRunning, Supervisor

log = logging.getLogger(__name__)
STATIC = Path(__file__).parents[1] / 'web' / 'static'
CLI_HEADER = 'x-pokesim-cli-token'
SESSION_COOKIE = 'pokesim_session'
SHARE_COOKIE = 'pokesim_share'
# An open screen stream checks this often that its viewer may still watch.
STREAM_RECHECK_SECONDS = 5
GAME_READ_PATHS = {'', 'pokedex', 'team', 'journey', 'pc', 'journal', 'journal/stats', 'stats', 'stats/pokemon', 'stats/items', 'trading',
                   'api/pokedex', 'api/pokedex/status', 'api/trading', 'api/interactions',
                   'api/audio', 'api/lease', 'api/state', 'api/events', 'api/progress', 'api/statistics', 'api/statistics/activity', 'api/states', 'healthz', 'frame.jpg', 'stream', 'feed.xml', 'item-artwork'}

# Pages a person opens. A stopped adventure answers these with its status page, not raw JSON.
GAME_PAGES = {'', 'pokedex', 'team', 'journey', 'pc', 'journal', 'journal/stats', 'stats', 'stats/pokemon',
              'stats/items', 'trading'}


class CapReached(Exception):
    """A start would put more adventures running than a cap allows."""


def public_game_path(method, path):
    """Allow public routes before HTTP client URL normalization can change them."""
    if method == 'POST':
        return path in {'api/control', 'api/lease', 'api/trading/preferences', 'api/export-save'}
    if method not in {'GET', 'HEAD'}:
        return False
    if path in GAME_READ_PATHS:
        return True
    if any(part in {'', '.', '..'} for part in path.split('/')):
        return False
    return bool(re.fullmatch(r'(?:api/events|events)/[0-9]+|(?:sprites|sprites/shiny|shots|item-artwork)/[0-9]+\.png'
                             r'|static/[A-Za-z0-9_.-]+|static/fonts/[A-Za-z0-9_.-]+', path))


class Manager:
    def __init__(self, root, public_url='http://127.0.0.1:8000', *, game_data_dir=None,
                 reference_archive=None, child_factory=None, auth='none'):
        self.public_url = public_origin(public_url)
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / 'application.lock').open('a+b')
        try:
            lock_file(self.lock)
            fresh = not (self.root / 'app.sqlite').exists()
            self.registry = Registry(self.root)
            self.auth = AuthStore(self.root)
            self.auth_mode = self.resolve_auth(auth, fresh)
            self.oidc = self.proxy = None
            if self.auth_mode == 'accounts':
                from .providers import OIDC, ProxyAuth
                self.oidc = OIDC.from_env(self.public_url)
                self.proxy = ProxyAuth.from_env()
                # Kept in app.sqlite, which backups carry, so a restored copy asks for setup
                # again instead of opening without a login.
                self.registry.set_setting('accounts', True)
        except BaseException:
            for name in ('auth', 'registry'):
                if hasattr(self, name):
                    getattr(self, name).close()
            self.lock.close()
            raise
        self.setup_code = SetupCode()
        self.cli_token = None
        if self.auth_mode == 'accounts' and self.auth.setup_done():
            self.bind_library_owner()
        self.assets = Assets(self.registry, game_data_dir, reference_archive)
        self.supervisor = Supervisor(self.registry, self.assets, self.public_url,
                                     **({'child_factory': child_factory} if child_factory else {}))
        from .notifications import NotificationCenter
        self.notifications = NotificationCenter(self.registry, self.supervisor, self.public_url)
        self.maintenance = threading.RLock()
        self.cap_lock = threading.Lock()
        self.supervisor.admission = self.maintenance
        self.suspended = False
        self.closing = False
        self._closed = False
        self.tasks = set()
        self.sessions = {}
        self.session_lock = threading.Lock()
        from .coordinator import Coordinator
        self.coordinator = Coordinator(self)
        from .trade_builder import TradeBuilder
        self.builder = TradeBuilder(self)
        from .offers import TradeOffers
        self.offers = TradeOffers(self)
        from .watchdog import Watchdog
        self.watchdog = Watchdog(self)
        from .lease import Leases
        self.leases = Leases(self)

    @staticmethod
    def validate_adventure_settings(values):
        allowed = {'trainer_name', 'rival_name', 'speed', 'starter', 'policy', 'auto_start', 'seed', 'fast_text', 'battle_animations',
                   'autosave_seconds', 'keep_autosaves', 'stream_fps', 'viewer_only', 'league_rewards',
                   'mew_event', 'celebi_event', 'extra_store_items', 'fair_wild_dvs', 'legendary_return_steps', 'event_return_steps', 'mew_return_steps',
                   'fossil_preference', 'dojo_preference', 'event_retention_days', 'palette', 'randomizer'}
        if not isinstance(values, dict) or not set(values) <= allowed:
            raise ValueError('Unsupported adventure settings')
        result = {'starter': 'random', 'policy': 'strategic', 'auto_start': False, **values}
        from ..nicknames import validate_trainer_name
        for name in ('trainer_name', 'rival_name'):
            if name in result:
                result[name] = validate_trainer_name(result[name])
        if 'palette' in result:
            from ..palettes import validate_palette
            validate_palette(result['palette'])
        if 'speed' in result:
            from ..runtime.settings import validate_speed
            validate_speed(result['speed'])
        from ..cartridges import validate_starter
        validate_starter(result['starter'])
        if result['policy'] not in {'strategic', 'guided_random', 'smart_random'}:
            raise ValueError('Unknown adventure policy')
        for name in ('auto_start', 'fast_text', 'battle_animations', 'viewer_only', 'league_rewards', 'mew_event', 'celebi_event',
                     'extra_store_items', 'fair_wild_dvs'):
            if name in result and type(result[name]) is not bool:
                raise ValueError(f'{name} must be a boolean')
        # Off is stored as absent, so releases that predate the setting still open the adventure.
        if result.get('fair_wild_dvs') is False:
            del result['fair_wild_dvs']
        if 'randomizer' in result:
            from ..randomized import validate
            result['randomizer'] = validate(result['randomizer'])
            if not result['randomizer']:
                del result['randomizer']
        # Every notable event keeps a full save state beside its screenshot, which is about
        # 40 MB an hour, so an adventure needs a way to bound its own journal. Zero keeps all.
        for name, low, high in [('autosave_seconds', 1, 86400), ('keep_autosaves', 1, 10000),
                                ('event_return_steps', 0, 1000000000), ('mew_return_steps', 0, 1000000000),
                                ('stream_fps', 1, 60), ('legendary_return_steps', 0, 1000000000), ('event_retention_days', 0, 36500)]:
            if name in result and (type(result[name]) is not int or not low <= result[name] <= high):
                raise ValueError(f'{name} must be between {low} and {high}')
        for name, choices in {'fossil_preference': {'auto', 'helix', 'dome', 'amber'},
                              'dojo_preference': {'auto', 'hitmonlee', 'hitmonchan'}}.items():
            if name in result and (not isinstance(result[name], str) or result[name] not in choices):
                raise ValueError(f'Unknown {name}')
        if result.get('seed') is not None and type(result['seed']) is not int:
            raise ValueError('Seed must be an integer')
        return result

    def start_adventure(self, aid):
        try:
            self.check_available()
            with self.maintenance, self.supervisor._lock(aid):
                row = self.registry.adventure(aid)
                if row['desired_state'] == 'stopped':
                    if self.coordinator.reserved(aid):
                        return row
                    return self.supervisor.stop(aid, preserve_desired=True)
                self.supervisor.setup_retries.pop(aid, None)
                return self.supervisor.start(aid)
        except Exception as error:
            row = self.registry.adventure(aid)
            if row['desired_state'] == 'running':
                self.registry.update(aid, state='failed', error=str(error))
            raise

    def check_available(self):
        if self.suspended or self.closing:
            raise ValueError('PokeSim is saving, backing up, or shutting down')

    def running_caps(self):
        """The server-wide cap and the per-member cap on running adventures. None means no cap."""
        caps = self.registry.setting('running_caps', {})
        return {'server': caps.get('server'), 'member': caps.get('member')}

    @staticmethod
    def suggested_member_cap():
        """2 on a Pi or another arm64 machine with 4 GB of RAM or less, otherwise 4."""
        import platform
        import psutil
        small = platform.machine().lower() in {'aarch64', 'arm64', 'armv7l'} and psutil.virtual_memory().total <= 4 * 1024 ** 3
        return 2 if small else 4

    def check_running_cap(self, aid):
        """Refuse a start over a cap. Adventures already running are never stopped."""
        caps = self.running_caps()
        if self.registry.adventure(aid)['desired_state'] == 'running':
            return
        running = [row for row in self.registry.adventures()
                   if row['id'] != aid and not row['archived'] and row['desired_state'] == 'running']
        if caps['server'] is not None and len(running) >= caps['server']:
            raise CapReached(f'{len(running)} of {caps["server"]} adventures are running on this server. '
                             'Stop one before starting another')
        if caps['member'] is None or self.auth_mode != 'accounts':
            return
        owner = self.registry.adventure(aid).get('owner_id')
        user = self.auth.user(owner) if owner else None
        if user is None or user['role'] == 'admin':
            return
        mine = sum(row.get('owner_id') == owner for row in running)
        if mine >= caps['member']:
            raise CapReached(f'{user["display_name"]} has {mine} of {caps["member"]} adventures running. '
                             'Stop one before starting another')

    def start(self):
        self.announce_setup()
        self.watchdog.install()
        from .deletion import recover_deletions
        recover_deletions(self)
        from ..checkpoints import compress_event_states
        threading.Thread(target=compress_event_states, args=(self.root / 'adventures', self.maintenance),
                         kwargs={'stop': lambda: self.closing}, name='compress-event-states', daemon=True).start()
        self.coordinator.recover()
        for adventure in self.registry.adventures():
            if self.closing:
                return
            if (not adventure['archived'] and adventure['state'] != 'recovering'
                    and (adventure['desired_state'] == 'running' or adventure['settings'].get('auto_start'))):
                try:
                    self.registry.update(adventure['id'], desired_state='running')
                    self.supervisor.start(adventure['id'])
                except Exception as error:
                    self.registry.update(adventure['id'], state='failed', error=str(error))
        self.supervisor.run_monitor()
        self.coordinator.start_scheduler()
        self.watchdog.run()
        self.offers.run()
        if self.auth_mode == 'accounts':
            self.leases.run()
            threading.Thread(target=self.resume_orphans, name='resume-manual', daemon=True).start()

    def resume_orphans(self):
        """Leases do not survive a restart, so a worker still in manual mode goes back to the autopilot."""
        for aid in list(self.supervisor.children):
            if self.closing:
                return
            try:
                child = self.supervisor.child(aid)
                if child.request('GET', '/api/summary', timeout=5).get('manual_mode') and not self.leases.holder(aid):
                    child.request('POST', '/api/control', {'action': 'resume'}, timeout=5)
            except Exception:
                log.info('Could not check adventure %s for manual mode', aid, exc_info=True)

    def close(self):
        if self._closed:
            return
        self.closing = True
        self.watchdog.close()
        self.leases.close()
        self.offers.close()
        self.coordinator.close()
        errors = self.supervisor.close()
        if errors:
            log.error('Shutdown requires attention: %s', ', '.join(errors))
        self.registry.close()
        self.auth.close()
        self.lock.close()
        self._closed = True

    def background(self, function, *args):
        async def run():
            try:
                await asyncio.to_thread(function, *args)
            except Exception:
                log.exception('Background application operation failed')
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    # Accounts ---------------------------------------------------------------------------
    def resolve_auth(self, requested, fresh):
        """none or accounts. Upgrades with nothing configured stay open, and new libraries log in."""
        if requested == 'auto':
            requested = os.environ.get('AUTH', '').strip().lower() or 'auto'
        if requested in {'none', 'accounts'}:
            return requested
        if requested != 'auto':
            raise ValueError('AUTH must be none or accounts')
        configured = os.environ.get('OIDC_ISSUER') or os.environ.get('AUTH_PROXY_HEADER')
        if fresh or configured or self.auth.setup_done() or self.registry.setting('accounts'):
            return 'accounts'
        return 'none'

    @property
    def needs_setup(self):
        return self.auth_mode == 'accounts' and not self.auth.setup_done()

    def announce_setup(self):
        """Log a fresh one-time setup code while the Library has no admin."""
        if self.needs_setup:
            log.warning('PokeSim needs its first admin. Open %s/setup and enter this one-time code: %s',
                        self.public_url, self.setup_code.issue())

    def bootstrap_admin(self, username, password):
        """Create the first admin from POKESIM_ADMIN_USER and POKESIM_ADMIN_PASSWORD, so a
        server that nobody opens in a browser first does not wait on the setup page."""
        if not self.needs_setup or not username or not password:
            return None
        with self.auth.lock:
            user = self.auth.create_user(username, password, role='admin')
        self.bind_library_owner(user['id'])
        self.auth.audit('setup', user_id=user['id'], target='environment')
        log.info('Created the first admin %s from the environment', user['username'])
        return user

    def default_owner(self):
        return self.auth.library_owner()

    def bind_library_owner(self, uid=None):
        """Give adventures from before setup, and adventures of missing users, to the first admin."""
        if uid is not None and self.auth.setting('library_owner') is None:
            self.auth.set_setting('library_owner', uid)
        owner = self.auth.library_owner()
        if owner == LIBRARY_OWNER:
            return []
        moved = self.registry.rebind_owners(owner, {user['id'] for user in self.auth.users()})
        if moved:
            log.info('Gave %d adventures from before setup to the first admin', len(moved))
        return moved

    def issue_cli_token(self):
        """A token for `pokesim` commands on this machine. The file is readable only by its owner."""
        token = secrets.token_urlsafe(32)
        path = self.root / 'cli.token'
        path.unlink(missing_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='ascii') as output:
            output.write(token)
        self.cli_token = token
        return token

    def cli_request(self, request):
        sent = request.headers.get(CLI_HEADER, '')
        return bool(self.cli_token and sent.isascii() and hmac.compare_digest(sent, self.cli_token))

    def open_user(self):
        """The user every request acts as when accounts are off."""
        return {'id': self.auth.library_owner(), 'username': 'owner', 'display_name': 'Library owner',
                'role': 'admin', 'can_create': True, 'disabled': False, 'placeholder': True}

    def proxy_user(self, name, role):
        """The user a trusted proxy names. It gets its own identity, never a local account's."""
        with self.auth.lock:
            user = self.auth.identity_user('proxy', 'header', name)
            if user is None:
                user = self.auth.create_user(self.auth.free_username(name), role=role, display_name=name)
                self.auth.link_identity(user['id'], 'proxy', 'header', name)
                self.auth.audit('user.create', user_id=user['id'], target='proxy')
            if user['role'] != role:
                try:
                    user = self.auth.update_user(user['id'], role=role)
                except ValueError:
                    log.warning('The proxy names %s as a member, but they are the last admin', name)
        return user

    def actor(self, request):
        """Who is behind this request. Under AUTH=none everyone is the admin, as before accounts."""
        if self.auth_mode == 'none':
            return Actor(self.open_user())
        user = None
        if self.proxy:
            named = self.proxy.identify(request)
            if named:
                user = self.proxy_user(*named)
        if user is None:
            session = self.auth.session(request.cookies.get(SESSION_COOKIE))
            user = session['user'] if session else None
        if user is None and self.cli_request(request):
            user = self.auth.user(self.auth.library_owner())
        if user is not None and user['disabled']:
            user = None
        share = self.auth.share(request.cookies.get(SHARE_COOKIE))
        return self.actor_for(user, share['adventure_id'] if share else None)

    def actor_for(self, user, share=None):
        grants = self.auth.grants_for(user['id']) if user and user['role'] != 'admin' else {}
        return Actor(user, grants, share)

    def browser_session(self, request, actor=None):
        """The session that holds this browser's CSRF token: a stored login or an anonymous one."""
        session_id = request.cookies.get(SESSION_COOKIE, '')
        if self.auth_mode == 'accounts':
            stored = self.auth.session(session_id)
            if stored is not None:
                # A proxy login wins over a stale session cookie of someone else.
                if actor is None or actor.id == stored['user_id']:
                    return stored
                return None
        with self.session_lock:
            session = self.sessions.get(session_id)
            if session and session['expires'] > time.time():
                return session
        return None

    def anonymous_session(self, role):
        session_id = secrets.token_urlsafe(32)
        current = {'csrf_token': secrets.token_urlsafe(32), 'role': role, 'expires': time.time() + 86400}
        with self.session_lock:
            self.sessions = {key: value for key, value in self.sessions.items() if value['expires'] > time.time()}
            if len(self.sessions) >= 1024:
                raise HTTPException(429, 'Too many active browser sessions')
            self.sessions[session_id] = current
        return session_id, current

    def end_anonymous_session(self, request):
        with self.session_lock:
            self.sessions.pop(request.cookies.get(SESSION_COOKIE, ''), None)

    def set_session_cookie(self, response, raw, max_age):
        response.set_cookie(SESSION_COOKIE, raw, httponly=True, samesite='strict',
                            secure=self.public_url.startswith('https:'), max_age=max_age)

    def client_address(self, request):
        return request.client.host if request.client else None


async def json_body(request, limit=65536):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, 'Request is too large')
    try:
        value = json.loads(raw or b'{}')
    except ValueError as error:
        raise HTTPException(400, 'Invalid JSON') from error
    if not isinstance(value, dict):
        raise HTTPException(400, 'Expected an object')
    return value


GAME_ASSET = re.compile(r'/(?:games|view)/[A-Za-z0-9_-]+/(static|sprites|shots)/')


def read_preview(path):
    """Read a trade preview whole, or None once the trade has cleaned it up.

    Link workers replace the preview ten times a second and the coordinator removes the
    folder when the trade ends, so the size has to come from the bytes actually read.
    A FileResponse sizes the file before opening it and can promise more than it sends.
    """
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def cache_policy(path, query, content_type):
    """How long a browser may reuse a response without asking again.

    Pages reference their stylesheets and scripts with a ?v= stamp that changes with
    the file, so those never need a round trip. Everything live stays uncached.
    """
    if (re.fullmatch(r'(?:/api/v1/item-artwork/images|/(?:games|view)/[A-Za-z0-9_-]+/item-artwork)/[0-9]+\.png', path)
            and 'v=' in query and content_type.startswith('image/png')):
        return 'private, max-age=86400'
    game = GAME_ASSET.match(path)
    kind = game[1] if game else ('static' if path.startswith('/static/') else None)
    if kind == 'static':
        if 'v=' in query:
            return 'public, max-age=31536000, immutable'
        if path.endswith('.woff2'):
            return 'public, max-age=604800'
        return 'no-cache'
    if kind == 'sprites' and content_type.startswith('image/png'):
        # Pages stamp portraits with Assets.sprite_version, which changes whenever the image
        # behind an address could. The old fixed stamp says nothing, so it is revalidated.
        stamp = parse_qs(query).get('v', [''])[0]
        if stamp and stamp != SPRITE_VERSION:
            return 'public, max-age=31536000, immutable'
        return 'private, no-cache'
    if re.fullmatch(r'/(games|view)/[A-Za-z0-9_-]+/api/pokedex', path):
        # Species reference data: reused only after an ETag check, which costs no rebuild.
        return 'private, no-cache'
    if kind == 'shots':
        # Event numbers can be reused after a rollback, so ask before reusing a shot.
        return 'private, no-cache'
    return 'no-store'


def create_app(manager, shutdown=lambda: None):
    @asynccontextmanager
    async def lifespan(app):
        manager.background(manager.start)
        try:
            yield
        finally:
            manager.closing = True
            manager.supervisor.closed.set()
            manager.assets.cancelled.set()
            await asyncio.to_thread(manager.coordinator.close)
            if manager.tasks:
                await asyncio.gather(*list(manager.tasks), return_exceptions=True)
            await asyncio.to_thread(manager.close)
            if app.state.children is not None:
                await app.state.children.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager
    # One pooled client for every proxied game request. Building a client loads a TLS
    # context, which alone cost 20 to 60 ms a request, and a fresh one reconnects each time.
    app.state.children = None

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({'detail': str(error).strip("'")}, status_code=404)

    @app.exception_handler(CoreBackendCapabilityError)
    async def unsupported(request, error):
        return JSONResponse({'detail': str(error)}, status_code=501)

    from .trade_builder import ViewOnlyError

    @app.exception_handler(ViewOnlyError)
    async def view_only(request, error):
        return JSONResponse({'detail': str(error)}, status_code=403)

    from .offers import Changed, LimitReached, OwnerOnly

    @app.exception_handler(OwnerOnly)
    async def owner_only(request, error):
        return JSONResponse({'detail': str(error)}, status_code=403)

    @app.exception_handler(LimitReached)
    async def too_many_offers(request, error):
        return JSONResponse({'detail': str(error)}, status_code=429)

    @app.exception_handler(Changed)
    async def offer_changed(request, error):
        return JSONResponse({'detail': str(error), 'changed': True, 'offer': error.offer}, status_code=409)

    @app.exception_handler(CapReached)
    async def cap_reached(request, error):
        return JSONResponse({'detail': str(error), 'cap': True}, status_code=409)

    @app.exception_handler(RuntimeError)
    async def unavailable(request, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    # A browser that leaves while sending a body has gone, so there is no one to tell.
    @app.exception_handler(ClientDisconnect)
    async def departed(request, error):
        return Response(status_code=499)

    def route_action(request):
        """The declared action of the route this request reaches, and its path parameters.

        An unmatched path returns (None, {}) and gets FastAPI's own 404 or 405. A matched
        route with no declared action returns ('deny', {}).
        """
        for route in app.router.routes:
            matched, child = route.matches(request.scope)
            if matched != Match.FULL:
                continue
            if isinstance(route, Mount):
                return 'public', {}
            method = request.method
            action = policy.ROUTE_ACTIONS.get((method, route.path))
            if action is None and method == 'HEAD':
                action = policy.ROUTE_ACTIONS.get(('GET', route.path))
            return action or 'deny', child.get('path_params', {})
        return None, {}

    def owner_of(request):
        """Who a new adventure, import or request ID belongs to."""
        return request.state.actor.id or manager.default_owner()

    def check_route(request, actor):
        """A refusal for this request under accounts, or None to let it through."""
        action, params = route_action(request)
        if action in {None, 'public', 'game'}:
            return None
        if action == 'deny':
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        if action == 'page':
            if actor.user is not None:
                return None
            if manager.needs_setup:
                return RedirectResponse('/setup', status_code=303)
            return RedirectResponse('/login?' + urlencode({'next': request.url.path}), status_code=303)
        if actor.user is None:
            code = 'setup_required' if manager.needs_setup else 'login_required'
            return JSONResponse({'detail': 'Log in to PokeSim first', 'code': code}, status_code=401)
        if action.startswith('library.'):
            if can(actor, action):
                return None
            return JSONResponse({'detail': 'Only an admin can do this'}, status_code=403)
        try:
            adventure = manager.registry.adventure(params.get('aid', ''))
        except (KeyError, ValueError):
            return JSONResponse({'detail': 'Adventure not found'}, status_code=404)
        if not can(actor, 'adventure.watch', adventure):
            return JSONResponse({'detail': 'Adventure not found'}, status_code=404)
        if not can(actor, action, adventure):
            return JSONResponse({'detail': 'Only the owner of this adventure can do this'}, status_code=403)
        return None

    @app.middleware('http')
    async def access(request, call_next):
        expected = urlsplit(manager.public_url)
        if request.headers.get('host') != expected.netloc:
            return JSONResponse({'detail': 'Use the configured PokeSim address'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != f'{expected.scheme}://{expected.netloc}':
            return JSONResponse({'detail': 'Requests must come from this PokeSim application'}, status_code=403)
        if request.url.path.startswith('/view/') and request.method not in {'GET', 'HEAD'}:
            return JSONResponse({'detail': 'This is a view-only link'}, status_code=403)
        changing = request.method not in {'GET', 'HEAD', 'OPTIONS'}
        if request.headers.get('sec-fetch-site') == 'cross-site' and (changing or request.url.path == '/api/v1/session'):
            return JSONResponse({'detail': 'Requests must come from this PokeSim application'}, status_code=403)
        actor = await run_in_threadpool(manager.actor, request)
        request.state.actor = actor
        if changing:
            session = await run_in_threadpool(manager.browser_session, request, actor)
            csrf = request.headers.get('x-pokesim-csrf', '')
            if session is None or not csrf.isascii() or not hmac.compare_digest(csrf, session['csrf_token']):
                return JSONResponse({'detail': 'Reload this page before making changes'}, status_code=403)
        if manager.auth_mode == 'accounts':
            refused = await run_in_threadpool(check_route, request, actor)
            if refused is not None:
                protect_response(refused)
                refused.headers['Cache-Control'] = 'no-store'
                return refused
        response = await call_next(request)
        protect_response(response)
        response.headers['Cache-Control'] = cache_policy(
            request.url.path, request.url.query, response.headers.get('content-type', ''))
        return response

    # Compress text on the way out. Frames and portraits are already compressed, and
    # the live stream must reach the browser frame by frame.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6,
                       exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, 'multipart/x-mixed-replace'))

    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.get('/', response_class=HTMLResponse)
    @app.get('/notifications', response_class=HTMLResponse)
    @app.get('/settings', response_class=HTMLResponse)
    def home(request: Request):
        from ..web.library import render_library
        return render_library(request.url.path.strip('/') or 'library')

    @app.get('/trade')
    @app.get('/trading')
    def retired_trade_page():
        # Trading lives inside each game now. Old library links land on the library.
        return RedirectResponse('/', status_code=308)

    @app.get('/health/live')
    def live():
        return {'ok': not manager.closing, 'application_id': manager.registry.setting('application_id')}

    @app.get('/health/ready')
    def ready():
        return {'ok': not manager.closing, 'adventures': len(manager.registry.adventures())}

    @app.get('/api/v1/session')
    def session(request: Request):
        actor = request.state.actor
        if manager.auth_mode == 'none':
            current = manager.browser_session(request)
            extra = {'auth': 'none', 'authenticated': True, 'user': None,
                     'setup_recommended': True}
            if current is not None:
                return {'csrf_token': current['csrf_token'], 'role': current['role'], **extra}
            session_id, current = manager.anonymous_session('admin')
            response = JSONResponse({'csrf_token': current['csrf_token'], 'role': current['role'], **extra})
            manager.set_session_cookie(response, session_id, 86400)
            return response
        from .accounts import session_payload
        current = manager.browser_session(request, actor)
        if actor.user is not None and (current is None or 'user_id' not in current):
            # A proxy or command line login gets a stored session to hold its CSRF token.
            raw, current = manager.auth.create_session(actor.id, manager.client_address(request),
                                                       request.headers.get('user-agent'))
            response = JSONResponse(session_payload(manager, actor, current))
            manager.set_session_cookie(response, raw, 14 * 86400)
            return response
        if current is not None:
            return session_payload(manager, actor, current)
        session_id, current = manager.anonymous_session(None)
        response = JSONResponse(session_payload(manager, actor, current))
        manager.set_session_cookie(response, session_id, 86400)
        return response

    from .accounts import install as install_accounts
    install_accounts(app, manager)

    def listed(row, actor):
        return {**row, 'resources': manager.supervisor.resources(row['id']), 'access': policy.adventure_role(actor, row)}

    @app.get('/api/v1/adventures')
    def adventures(request: Request):
        actor = request.state.actor
        rows = policy.visible_adventures(actor, manager.registry.adventures())
        attention = manager.watchdog.public()
        if not actor.admin:
            # Library problems are for admins. A member sees those of adventures they can watch.
            shown = {row['id'] for row in rows}
            attention = {**attention, 'problems': [problem for problem in attention['problems']
                                                   if problem['adventure_id'] in shown]}
        return {'adventures': [listed(row, actor) for row in rows], 'attention': attention}

    @app.get('/api/v1/adventures/{aid}')
    def adventure(aid: str, request: Request):
        return listed(manager.registry.adventure(aid), request.state.actor)

    @app.get('/api/v1/assets')
    def assets():
        return {'roms': manager.registry.roms(), 'cartridges': manager.assets.cartridge_slots()}

    async def read_cartridge(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_ROM:
                raise HTTPException(413, 'The cartridge file is too large. Game Boy ROMs are at most 2 MB, and a ZIP may be at most 4 MB.')
        return bytes(raw)

    async def add_cartridge(request, slot=None):
        manager.check_available()
        raw = await read_cartridge(request)
        result = await asyncio.to_thread(manager.assets.add_cartridge, raw, slot)
        manager.background(manager.assets.install_portraits_quietly, result.pop('raw'))
        return result

    @app.post('/api/v1/assets/rom')
    async def add_rom(request: Request):
        # Kept for scripts and older pages: the cartridge row, as before, plus where it went.
        result = await add_cartridge(request)
        return {**result['rom'], 'title': result['title'], 'message': result['message']}

    @app.get('/api/v1/cartridges')
    def cartridges():
        from ..cartridges import supported_names
        return {'slots': manager.assets.cartridge_slots(), 'supported': supported_names()}

    @app.post('/api/v1/cartridges')
    async def upload_cartridge(request: Request, slot: str | None = None):
        result = await add_cartridge(request, slot or None)
        return {**result, 'slots': manager.assets.cartridge_slots()}

    @app.delete('/api/v1/cartridges/{version}')
    def remove_cartridge(version: str):
        manager.check_available()
        result = manager.assets.remove_cartridge(version)
        return {**result, 'slots': manager.assets.cartridge_slots()}

    @app.post('/api/v1/adventures')
    async def create(request: Request):
        manager.check_available()
        data = await json_body(request)
        settings = manager.validate_adventure_settings({
            'trainer_name': data.get('trainer_name', ''),
            'rival_name': data.get('rival_name', ''),
            'starter': data.get('starter', 'random'),
            'speed': data.get('speed', 1),
            'league_rewards': data.get('league_rewards', True),
            'mew_event': data.get('mew_event', True),
            'celebi_event': data.get('celebi_event', True),
            'extra_store_items': data.get('extra_store_items', True),
            **({'fair_wild_dvs': data['fair_wild_dvs']} if 'fair_wild_dvs' in data else {}),
            **({'randomizer': data['randomizer']} if data.get('randomizer') else {}),
            'legendary_return_steps': data.get('legendary_return_steps', 1000000),
            'event_return_steps': data.get('event_return_steps', 100000),
            'mew_return_steps': data.get('mew_return_steps', 1000000),
            'fossil_preference': data.get('fossil_preference', 'auto'),
            'dojo_preference': data.get('dojo_preference', 'auto'),
        })
        return manager.registry.create(data.get('name', ''), data.get('rom_id', ''), settings,
                                       data.get('request_id', identifier()), owner=owner_of(request))

    @app.post('/api/v1/adventures/{aid}/start')
    async def start(aid: str, request: Request):
        manager.check_available()
        adventure = manager.registry.adventure(aid)
        if adventure['archived']:
            raise ValueError('Restore this adventure before starting')
        data = await json_body(request)

        def admit():
            # One start at a time passes the cap check, so two starts cannot both take the last place.
            with manager.cap_lock:
                manager.check_running_cap(aid)
                return manager.registry.request_lifecycle(aid, 'start', data.get('request_id', identifier()),
                                                          owner=owner_of(request))
        if await run_in_threadpool(admit):
            manager.registry.update(aid, state='starting', error=None)
            manager.background(manager.start_adventure, aid)
        return manager.registry.adventure(aid)

    @app.post('/api/v1/adventures/{aid}/stop')
    async def stop(aid: str, request: Request):
        manager.check_available()
        manager.registry.adventure(aid)
        data = await json_body(request)
        if not manager.registry.request_lifecycle(aid, 'stop', data.get('request_id', identifier()), owner=owner_of(request)):
            return manager.registry.adventure(aid)
        if manager.coordinator.reserved(aid):
            return manager.registry.update(aid, summary={'message': 'Will stop after the pending trade is resolved'})
        manager.background(manager.start_adventure, aid)
        return manager.registry.adventure(aid)

    @app.delete('/api/v1/adventures/{aid}')
    async def delete(aid: str, request: Request):
        from .deletion import delete_adventure
        data = await json_body(request)
        result = await asyncio.to_thread(delete_adventure, manager, aid, data.get('confirmation'))
        manager.auth.forget_adventure(aid)
        return result

    @app.post('/api/v1/adventures/{aid}/archive')
    async def archive(aid: str):
        manager.check_available()
        adventure = manager.registry.adventure(aid)
        if adventure['state'] not in {'stopped', 'failed'} or manager.coordinator.reserved(aid):
            raise ValueError('Stop this adventure and resolve its trades before archiving')
        return manager.registry.update(aid, archived=True, desired_state='stopped')

    @app.patch('/api/v1/adventures/{aid}')
    async def edit(aid: str, request: Request):
        manager.check_available()
        data = await json_body(request)
        if set(data) - {'name', 'settings', 'archived'}:
            raise ValueError('Unsupported adventure changes')
        adventure = manager.registry.adventure(aid)
        if manager.coordinator.reserved(aid):
            raise ValueError('Settings are frozen until the trade is resolved')
        values = {}
        if 'name' in data:
            name = str(data['name']).strip()
            if not 1 <= len(name) <= 120:
                raise ValueError('Choose a name of 1 to 120 characters')
            values['name'] = name
        if 'archived' in data:
            if type(data['archived']) is not bool or adventure['state'] not in {'stopped', 'failed'}:
                raise ValueError('Archive state can only change while stopped')
            values['archived'] = data['archived']
        if 'settings' in data:
            changes = data['settings']
            if not isinstance(changes, dict):
                raise ValueError('Settings must be an object')
            if {'trainer_name', 'rival_name'} & set(changes):
                raise ValueError('Trainer and rival names are chosen when creating an adventure')
            # The seed shapes the whole world, so changing it mid-adventure would contradict the save.
            if 'randomizer' in changes:
                from ..randomized import validate
                if validate(changes['randomizer']) != adventure['settings'].get('randomizer', ''):
                    raise ValueError('The randomizer is chosen when creating an adventure')
                changes = {key: value for key, value in changes.items() if key != 'randomizer'}
            if adventure['state'] == 'running' and set(changes) - {'auto_start', 'speed', 'palette', 'fair_wild_dvs'}:
                raise ValueError('Stop the adventure before changing these settings')
            previous = adventure['settings']
            values['settings'] = manager.validate_adventure_settings({**previous, **changes})
            from ..cartridges import validate_generation_settings
            validate_generation_settings(values['settings'], adventure['version'])
        result = manager.registry.update(aid, **values) if values else adventure
        if 'speed' in data.get('settings', {}):
            result['pace_pending'] = await asyncio.to_thread(manager.supervisor.push_speed, aid)
        if 'palette' in data.get('settings', {}):
            result['palette_pending'] = await asyncio.to_thread(manager.supervisor.push_palette, aid)
        if 'fair_wild_dvs' in data.get('settings', {}):
            result['fair_wild_dvs_pending'] = await asyncio.to_thread(manager.supervisor.push_fair_wild_dvs, aid)
        return result

    @app.get('/api/v1/settings')
    def settings(request: Request):
        from ..nicknames import nickname_defaults, nickname_catalog
        parts = {**nickname_defaults(), **manager.registry.setting('nickname_parts', {})}
        # Where the library lives on disk is for the person who runs the server.
        place = {'data_dir': str(manager.root)} if request.state.actor.admin else {}
        return {**place, **parts, 'nickname_catalog': nickname_catalog(parts)}

    @app.patch('/api/v1/settings')
    async def set_settings(request: Request):
        manager.check_available()
        from ..nicknames import validate_parts, nickname_defaults
        changes = validate_parts(await json_body(request))
        parts = validate_parts({**nickname_defaults(), **manager.registry.setting('nickname_parts', {}), **changes})
        manager.registry.set_setting('nickname_parts', parts)
        pending = await asyncio.to_thread(manager.supervisor.update_nicknames)
        return {**settings(request), 'pending': pending}

    @app.get('/api/v1/portraits')
    def portraits():
        return manager.assets.portraits.status()

    @app.post('/api/v1/portraits/community')
    async def install_portraits():
        manager.check_available()
        if manager.assets.portraits.begin():
            manager.background(manager.assets.portraits.install)
        return portraits()

    @app.post('/api/v1/portraits/default')
    def restore_portraits():
        manager.check_available()
        manager.assets.portraits.restore()
        return portraits()

    @app.get('/api/v1/portraits/preview/{dex}.png')
    def portrait_preview(dex: int):
        path = manager.assets.portraits.path(dex, preview=True)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type='image/png')

    @app.get('/api/v1/item-artwork')
    def item_artwork():
        return manager.assets.item_artwork.status()

    @app.post('/api/v1/item-artwork/install')
    async def install_item_artwork():
        manager.check_available()
        if manager.assets.item_artwork.begin():
            manager.background(manager.assets.item_artwork.install)
        return item_artwork()

    @app.post('/api/v1/item-artwork/default')
    def hide_item_artwork():
        manager.check_available()
        manager.assets.item_artwork.restore()
        return item_artwork()

    @app.get('/api/v1/item-artwork/images/{item}.png')
    def item_image(item: int):
        path = manager.assets.item_artwork.path(item)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type='image/png')

    @app.get('/api/v1/watchdog')
    def watchdog():
        return manager.watchdog.public()

    @app.patch('/api/v1/watchdog')
    async def set_watchdog(request: Request):
        manager.check_available()
        data = await json_body(request)
        if not isinstance(data, dict) or set(data) != {'enabled'}:
            raise HTTPException(422, 'Send {"enabled": true} or {"enabled": false}')
        try:
            return await asyncio.to_thread(manager.watchdog.set_enabled, data['enabled'])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/v1/running-caps')
    def running_caps(request: Request):
        running = [row for row in manager.registry.adventures()
                   if not row['archived'] and row['desired_state'] == 'running']
        mine = sum(row.get('owner_id') == request.state.actor.id for row in running)
        return {**manager.running_caps(), 'running': len(running), 'mine': mine,
                'suggested_member': manager.suggested_member_cap(),
                'can_change': can(request.state.actor, 'library.settings')}

    @app.put('/api/v1/running-caps')
    async def set_running_caps(request: Request):
        data = await json_body(request)
        if not isinstance(data, dict) or not data or set(data) - {'server', 'member'}:
            raise HTTPException(422, 'Send server, member or both')
        for value in data.values():
            if value is not None and (type(value) is not int or not 1 <= value <= 1000):
                raise HTTPException(422, 'A cap is a whole number from 1 to 1000, or null for no cap')
        manager.registry.set_setting('running_caps', {**manager.running_caps(), **data})
        manager.auth.audit('caps.update', user_id=request.state.actor.id, target=json.dumps(data, sort_keys=True))
        return running_caps(request)

    @app.get('/api/v1/notifications')
    def notifications():
        return manager.notifications.public()

    @app.patch('/api/v1/notifications')
    async def set_notifications(request: Request):
        manager.check_available()
        data = await json_body(request)
        pending = await asyncio.to_thread(manager.notifications.update, data)
        return {**manager.notifications.public(), 'pending': pending}

    @app.post('/api/v1/notifications/test')
    async def test_notification(request: Request):
        data = await json_body(request)
        return await asyncio.to_thread(manager.notifications.test, data)

    @app.post('/api/v1/notifications/integrations')
    async def add_notification_integration(request: Request):
        manager.check_available()
        data = await json_body(request)
        pending = await asyncio.to_thread(manager.notifications.save_integration, data)
        return {**manager.notifications.public(), 'pending': pending}

    @app.patch('/api/v1/notifications/integrations/{integration_id}')
    async def edit_notification_integration(integration_id: str, request: Request):
        manager.check_available()
        data = await json_body(request)
        pending = await asyncio.to_thread(manager.notifications.save_integration, data, integration_id)
        return {**manager.notifications.public(), 'pending': pending}

    @app.delete('/api/v1/notifications/integrations/{integration_id}')
    async def remove_notification_integration(integration_id: str):
        manager.check_available()
        pending = await asyncio.to_thread(manager.notifications.delete_integration, integration_id)
        return {**manager.notifications.public(), 'pending': pending}

    @app.post('/api/v1/notifications/integrations/{integration_id}/test')
    async def test_notification_integration(integration_id: str, request: Request):
        data = await json_body(request)
        return await asyncio.to_thread(manager.notifications.test, data, integration_id)

    def require(request, action, *aids):
        """Refuse unless this person may do `action` on every adventure named. Trades with
        someone else's adventure go through trade offers."""
        actor = request.state.actor
        if actor.admin:
            return
        for aid in aids:
            try:
                row = manager.registry.adventure(validate_id(aid))
            except (KeyError, ValueError, TypeError):
                raise HTTPException(404, 'Adventure not found') from None
            if not can(actor, 'adventure.watch', row):
                raise HTTPException(404, 'Adventure not found')
            if not can(actor, action, row):
                raise HTTPException(403, 'You cannot trade for this adventure. Send its owner an offer instead'
                                    if action == 'adventure.own' else 'You cannot trade for this adventure')

    def owned_ids(request):
        """The adventures this person owns, or None for an admin, who sees every one."""
        actor = request.state.actor
        if actor.admin:
            return None
        return {row['id'] for row in manager.registry.adventures() if can(actor, 'adventure.own', row)}

    def trade_participants(tid):
        try:
            return manager.registry.transaction(validate_id(tid))['plan']['participants']
        except (KeyError, ValueError):
            raise HTTPException(404, 'Trade not found') from None

    @app.get('/api/v1/interactions')
    def interactions(request: Request):
        status = manager.coordinator.status()
        owned = owned_ids(request)
        if owned is None:
            return status
        mine = lambda row: bool({row['left_id'], row['right_id']} & owned)  # noqa: E731
        return {**status, 'participants': [aid for aid in status['participants'] if aid in owned],
                **{key: [row for row in status[key] if mine(row)] for key in ('active', 'history', 'recent_failures', 'queued')},
                'attention': None, 'message': None}

    @app.post('/api/v1/interactions/trades')
    async def trade(request: Request):
        manager.check_available()
        data = await json_body(request)
        require(request, 'adventure.own', data.get('left_id'), data.get('right_id'))
        row = await asyncio.to_thread(manager.coordinator.propose, data)
        manager.background(manager.coordinator.execute, row['id'])
        return row

    # Trade builder: the owner picks a Pokémon in two of their adventures and trades them.
    @app.get('/api/v1/interactions/trade-builder/targets')
    async def trade_builder_targets(request: Request, from_id: str, from_key: str | None = None):
        await run_in_threadpool(require, request, 'adventure.own', from_id)
        owned = await run_in_threadpool(owned_ids, request)
        limit = {} if owned is None else {'visible': owned}
        return await asyncio.to_thread(manager.builder.targets, validate_id(from_id), from_key, **limit)

    @app.get('/api/v1/interactions/trade-builder/limits')
    async def trade_builder_limits(request: Request, from_id: str, from_key: str, to_id: str):
        await run_in_threadpool(require, request, 'adventure.own', from_id, to_id)
        return await asyncio.to_thread(manager.builder.limits, validate_id(from_id), from_key, validate_id(to_id))

    @app.get('/api/v1/interactions/trade-builder/pokemon')
    async def trade_builder_pokemon(request: Request, adventure_id: str):
        await run_in_threadpool(require, request, 'adventure.own', adventure_id)
        return await asyncio.to_thread(manager.builder.pokemon, validate_id(adventure_id))

    @app.post('/api/v1/interactions/trade-builder')
    async def create_built_trade(request: Request):
        manager.check_available()
        data = await json_body(request)
        await run_in_threadpool(require, request, 'adventure.own', data.get('from_id'), data.get('to_id'))
        trade = await asyncio.to_thread(manager.builder.create, data)
        manager.background(manager.coordinator.drain_manual)
        return trade

    @app.post('/api/v1/interactions/trade-builder/{mid}/cancel')
    async def cancel_built_trade(mid: str, request: Request):
        def cancel():
            queued = manager.coordinator.manual_status(validate_id(mid))
            require(request, 'adventure.own', queued['left_id'], queued['right_id'])
            return manager.builder.cancel(mid)
        return await asyncio.to_thread(cancel)

    # Trade offers: one adventure asks another, often someone else's, for a trade. Accepting queues a manual trade.
    def open_to_offers(request, aid):
        """Refuse unless this person manages the adventure or its owner takes offers for it."""
        actor = request.state.actor
        try:
            row = manager.registry.adventure(validate_id(aid))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(404, 'Adventure not found') from None
        if actor.admin or can(actor, 'adventure.manage', row):
            return row
        if not row['archived'] and trade_settings.get(manager.registry, row['id'])['open_to_offers']:
            return row
        if can(actor, 'adventure.watch', row):
            raise HTTPException(403, 'This adventure does not take trade offers')
        raise HTTPException(404, 'Adventure not found')

    def offer_targets(request, from_id, from_key):
        actor = request.state.actor
        sender = manager.registry.adventure(from_id)
        games = [row for row in manager.registry.adventures() if not row['archived']]
        visible = None if actor.admin else {
            row['id'] for row in games if can(actor, 'adventure.manage', row)
            or trade_settings.get(manager.registry, row['id'])['open_to_offers']}
        result = manager.offers.targets(from_id, from_key, **({} if visible is None else {'visible': visible}))
        rows = {row['id']: row for row in games}
        names = {}
        for target in result['adventures']:
            game = rows.get(target['id']) or {}
            # Trading between two of your own adventures goes through the trade builder, without an offer.
            target['offer'] = not (can(actor, 'adventure.own', sender) and can(actor, 'adventure.own', game))
            target['owner_name'] = manager.offers._owner_name(game, names)
        return result

    def offer_side(request, oid, side):
        offer = manager.registry.trade_offer(validate_id(oid))
        require(request, 'adventure.manage', offer[side])
        return offer

    @app.get('/api/v1/interactions/trade-offers')
    async def trade_offers(request: Request, adventure_id: str):
        await run_in_threadpool(require, request, 'adventure.manage', adventure_id)
        return await asyncio.to_thread(manager.offers.for_adventure, validate_id(adventure_id))

    @app.get('/api/v1/interactions/trade-offers/targets')
    async def trade_offer_targets(request: Request, from_id: str, from_key: str | None = None):
        await run_in_threadpool(require, request, 'adventure.manage', from_id)
        return await asyncio.to_thread(offer_targets, request, validate_id(from_id), from_key)

    @app.get('/api/v1/interactions/trade-offers/limits')
    async def trade_offer_limits(request: Request, from_id: str, from_key: str, to_id: str):
        await run_in_threadpool(require, request, 'adventure.manage', from_id)
        await run_in_threadpool(open_to_offers, request, to_id)
        return await asyncio.to_thread(manager.offers.limits, validate_id(from_id), from_key, validate_id(to_id))

    @app.get('/api/v1/interactions/trade-offers/pokemon')
    async def trade_offer_pokemon(request: Request, adventure_id: str):
        await run_in_threadpool(open_to_offers, request, adventure_id)
        return await asyncio.to_thread(manager.offers.pokemon, validate_id(adventure_id))

    @app.post('/api/v1/interactions/trade-offers')
    async def create_trade_offer(request: Request):
        manager.check_available()
        data = await json_body(request)
        await run_in_threadpool(require, request, 'adventure.manage', data.get('from_id'))
        await run_in_threadpool(open_to_offers, request, data.get('to_id'))
        offer = await asyncio.to_thread(manager.offers.create, data, request.state.actor)
        if offer['status'] == 'accepted':
            manager.background(manager.coordinator.drain_manual)
        return offer

    @app.get('/api/v1/interactions/trade-offers/{oid}')
    async def trade_offer(oid: str, request: Request):
        def read():
            offer = manager.registry.trade_offer(validate_id(oid))
            try:
                require(request, 'adventure.manage', offer['from_id'])
            except HTTPException:
                require(request, 'adventure.manage', offer['to_id'])
            return manager.offers.status(oid)
        return await asyncio.to_thread(read)

    @app.post('/api/v1/interactions/trade-offers/{oid}/accept')
    async def accept_trade_offer(oid: str, request: Request):
        manager.check_available()
        data = await json_body(request)
        if set(data) - {'to_key', 'confirm'} or not isinstance(data.get('confirm', False), bool):
            raise HTTPException(400, 'Send to_key and confirm only')
        await run_in_threadpool(offer_side, request, oid, 'to_id')
        offer = await asyncio.to_thread(manager.offers.accept, oid, request.state.actor, data.get('to_key'),
                                        data.get('confirm', False))
        if offer['status'] == 'accepted':
            manager.background(manager.coordinator.drain_manual)
        return offer

    @app.post('/api/v1/interactions/trade-offers/{oid}/decline')
    async def decline_trade_offer(oid: str, request: Request):
        await run_in_threadpool(offer_side, request, oid, 'to_id')
        return await asyncio.to_thread(manager.offers.decline, oid)

    @app.post('/api/v1/interactions/trade-offers/{oid}/cancel')
    async def cancel_trade_offer(oid: str, request: Request):
        await run_in_threadpool(offer_side, request, oid, 'from_id')
        return await asyncio.to_thread(manager.offers.withdraw, oid)

    # Automatic trading settings: on or off, per adventure.
    @app.get('/api/v1/interactions/auto-settings')
    async def auto_settings(request: Request, adventure_id: str):
        await run_in_threadpool(require, request, 'adventure.watch', adventure_id)

        def read():
            aid = validate_id(adventure_id)
            # Only the owner changes these switches. The page hides them from everyone else.
            return {**auto_settings_public(aid), 'can_change': can(request.state.actor, 'adventure.own', manager.registry.adventure(aid))}
        return await asyncio.to_thread(read)

    @app.put('/api/v1/interactions/auto-settings')
    async def set_auto_settings(adventure_id: str, request: Request):
        manager.check_available()
        await run_in_threadpool(require, request, 'adventure.own', adventure_id)
        aid = validate_id(adventure_id)
        data = await json_body(request)
        if not data or set(data) - set(trade_settings.SWITCHES):
            raise HTTPException(400, 'Send enabled, open_to_offers or across_owners')

        def write():
            if manager.builder.viewer_only(aid):
                raise HTTPException(403, 'This adventure is view-only')
            manager.registry.adventure(aid)
            try:
                trade_settings.update(manager.registry, aid, **data)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            return auto_settings_public(aid)
        return await asyncio.to_thread(write)

    def auto_settings_public(aid):
        manager.registry.adventure(aid)
        return {'adventure_id': aid, **trade_settings.get(manager.registry, aid),
                'viewer_only': manager.builder.viewer_only(aid)}

    @app.post('/api/v1/interactions/{tid}/cancel')
    async def cancel(tid: str, request: Request):
        if not request.state.actor.admin:
            await run_in_threadpool(lambda: require(request, 'adventure.own', *trade_participants(tid)))
        return await asyncio.to_thread(manager.coordinator.cancel, tid)

    @app.post('/api/v1/interactions/{tid}/recover')
    async def recover(tid: str, request: Request):
        if not request.state.actor.admin:
            await run_in_threadpool(lambda: require(request, 'adventure.own', *trade_participants(tid)))
        manager.registry.transaction(tid)
        manager.background(manager.coordinator.recover_one, tid)
        return manager.registry.transaction(tid)

    @app.get('/api/v1/backups')
    def backups():
        directory = manager.root / 'backups'
        rows = []
        for path in directory.glob('*.zip'):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            rows.append({'id': path.stem, 'path': str(path), 'created_at': stat.st_mtime,
                         'size_bytes': stat.st_size})
        return {'backups': sorted(rows, key=lambda row: (row['created_at'], row['id']), reverse=True)}

    @app.delete('/api/v1/backups/{bid}')
    def delete_backup(bid: str):
        validate_id(bid)
        (manager.root / 'backups' / (bid + '.zip')).unlink(missing_ok=True)
        return {'deleted': bid}

    @app.post('/api/v1/backups')
    async def backup():
        from .backup import create_backup
        return await asyncio.to_thread(create_backup, manager)

    @app.get('/api/v1/backups/{bid}/download')
    def download_backup(bid: str):
        validate_id(bid)
        path = manager.root / 'backups' / (bid + '.zip')
        if not path.is_file():
            raise HTTPException(404, 'Backup not found')
        return FileResponse(path, filename='pokesim-' + bid + '.zip')

    def backup_path(bid):
        validate_id(bid)
        path = manager.root / 'backups' / (bid + '.zip')
        if not path.is_file():
            raise HTTPException(404, 'Backup not found')
        return path

    @app.get('/api/v1/backups/{bid}/inspect')
    def inspect_saved_backup(bid: str):
        from .backup import inspect_backup
        return inspect_backup(manager, backup_path(bid))

    @app.post('/api/v1/backups/upload')
    async def upload_backup(request: Request):
        from .backup import inspect_backup
        manager.check_available()
        directory = manager.root / 'backups'
        directory.mkdir(exist_ok=True)
        bid = identifier()
        pending = directory / (bid + '.pending')
        try:
            total = 0
            with pending.open('xb') as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > 2 * 1024**3:
                        raise HTTPException(413, 'Backup upload exceeds 2 GB')
                    output.write(chunk)
            result = await asyncio.to_thread(inspect_backup, manager, pending)
            os.utime(pending, (time.time(), result['created_at']))
            pending.replace(directory / (bid + '.zip'))
            return {'id': bid, **result}
        finally:
            pending.unlink(missing_ok=True)

    @app.post('/api/v1/backups/{bid}/load')
    async def load_saved_backup(bid: str, request: Request):
        from .backup import load_backup_adventure
        values = await json_body(request)
        return await asyncio.to_thread(load_backup_adventure, manager, backup_path(bid),
                                       values.get('adventure_id'), values.get('name'), values.get('request_id'),
                                       owner=owner_of(request))

    @app.post('/api/v1/imports')
    async def import_data(request: Request):
        from .migration import import_archive
        manager.check_available()
        imports = manager.root / 'imports'
        imports.mkdir(exist_ok=True)
        path = imports / (identifier() + '.zip')
        try:
            total = 0
            with path.open('xb') as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > 512 * 1024**2:
                        raise HTTPException(413, 'Import archive exceeds 512 MB')
                    output.write(chunk)
            return await asyncio.to_thread(import_archive, manager, path, owner=owner_of(request))
        finally:
            path.unlink(missing_ok=True)

    @app.post('/api/v1/shutdown')
    def quit_app():
        return JSONResponse({'ok': True}, background=BackgroundTask(shutdown))

    # A view link: the same game pages, watched without controls. Expose only /view/ to share.
    @app.api_route('/view/{aid}/{path:path}', methods=['GET', 'HEAD'])
    async def view(aid: str, path: str, request: Request):
        if not viewer_allows(request.method, path):
            raise HTTPException(403, 'This is a view-only link')
        return await game(aid, path, request, viewer=True)

    @app.api_route('/games/{aid}/{path:path}', methods=['GET', 'POST', 'HEAD'])
    async def games(aid: str, path: str, request: Request):
        return await game(aid, path, request)

    def game_access(aid, path, request, viewer, body):
        """Whether this person may make this game request, and the adventure role the worker sees.

        A watcher gets the view-only game. A player or manager gets the game with only the
        controls their role allows. A share link counts only under /view/, which is also the
        only path its cookie is sent to. Control presses also need the control lease.
        """
        actor = request.state.actor
        if not viewer:
            actor = policy.Actor(actor.user, actor.grants)
        if actor.user is None and actor.share is None:
            if path in GAME_PAGES and request.method == 'GET':
                target = '/setup' if manager.needs_setup else '/login?' + urlencode({'next': request.url.path})
                return RedirectResponse(target, status_code=303)
            raise HTTPException(401, 'Log in to PokeSim first')
        try:
            adventure = manager.registry.adventure(aid)
        except (KeyError, ValueError):
            raise HTTPException(404, 'Adventure not found') from None
        if not can(actor, 'adventure.watch', adventure):
            raise HTTPException(404, 'Adventure not found')
        control = None
        if request.method == 'POST' and path == 'api/control':
            try:
                control = json.loads(body or b'{}').get('action')
            except (ValueError, AttributeError):
                raise HTTPException(400, 'Invalid JSON') from None
        action = policy.game_action(request.method, path, control)
        if action is None:
            raise HTTPException(404)
        if not can(actor, action, adventure):
            raise HTTPException(403, 'Your role on this adventure does not allow this')
        if control in policy.LEASE_ACTIONS and not manager.leases.holds(aid, actor):
            raise HTTPException(409, 'Ask for control first. Someone else may hold it.')
        if control == 'press':
            manager.leases.touch(aid, actor)
        if control == 'resume' and not (manager.leases.holds(aid, actor) or can(actor, 'adventure.manage', adventure)):
            raise HTTPException(403, 'Only the person in control or a manager can resume the autopilot')
        if control in {'resume', 'pause'}:
            # The autopilot takes over again, or the manager stopped it, so nobody holds control.
            manager.leases.end(aid, control, apply=False)
        return 'viewer' if viewer else policy.adventure_role(actor, adventure)

    def lease_route(aid, request, body):
        """The control lease of one adventure: GET reads it, POST acts on it."""
        from .lease import END_CHOICES, LeaseRefused
        actor = request.state.actor
        if request.url.path.startswith('/games/'):
            actor = policy.Actor(actor.user, actor.grants)
        adventure = manager.registry.adventure(aid)
        if request.method != 'POST':
            return manager.leases.status(aid, actor, adventure)
        try:
            data = json.loads(body or b'{}')
        except ValueError:
            raise HTTPException(400, 'Invalid JSON') from None
        if not isinstance(data, dict) or set(data) - {'action', 'user_id', 'end'}:
            raise HTTPException(400, 'Unsupported lease request')
        if data.get('action') == 'setting':
            if not can(actor, 'adventure.own', adventure):
                raise HTTPException(403, 'Only the owner chooses what happens when control ends')
            if data.get('end') not in END_CHOICES:
                raise HTTPException(400, 'Choose resume or pause')
            manager.registry.set_setting('lease_end:' + aid, data['end'])
            return manager.leases.status(aid, actor, adventure)
        try:
            return manager.leases.act(aid, actor, adventure, data.get('action'), data.get('user_id'))
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except LeaseRefused as error:
            raise HTTPException(409, str(error)) from None

    def still_allowed(request, aid):
        """Re-run the watch check for an open stream: a revoked grant, link or session closes it."""
        if manager.auth_mode != 'accounts':
            return True
        actor = manager.actor(request)
        if not request.url.path.startswith('/view/'):
            actor = policy.Actor(actor.user, actor.grants)
        try:
            return can(actor, 'adventure.watch', manager.registry.adventure(aid))
        except KeyError:
            return False

    async def game(aid, path, request, viewer=False):
        if not public_game_path(request.method, path):
            raise HTTPException(404)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, 'Game request is too large')
        body = bytes(body)
        role = 'viewer' if viewer else 'owner'
        if manager.auth_mode == 'accounts':
            access = await run_in_threadpool(game_access, aid, path, request, viewer, body)
            if isinstance(access, Response):
                return access
            role = access
            viewer = role == 'viewer'
        if path == 'api/lease':
            return await run_in_threadpool(lease_route, aid, request, body)
        # Everything below that reads the registry, the coordinator or the disk runs in a worker
        # thread. This handler shares one event loop with every page of every adventure, so a
        # blocking call here (a registry lock held across a commit, a slow trade history) would
        # stall the whole library, not just this request. Starlette's request pool, not the
        # default executor: background trades hold default-executor threads for minutes.
        adventure = await run_in_threadpool(manager.registry.adventure, aid)
        if path == 'trading' and request.method in {'GET', 'HEAD'}:
            from ..web.pages import render_game_page
            return HTMLResponse(render_game_page('adventure-trading.html', base_path=f"/{'view' if viewer else 'games'}/{aid}",
                adventure_id=aid, adventure_name=adventure['name'], viewer=role in {'viewer', 'player'},
                sprite_version=await run_in_threadpool(manager.assets.sprite_version, aid)))
        if path == 'api/interactions' and request.method in {'GET', 'HEAD'}:
            return JSONResponse(await run_in_threadpool(manager.coordinator.adventure_status, aid,
                                                        role not in {'manager', 'owner'}))
        # Item artwork is a library setting, served here too so a view link never needs /api/v1/.
        if path == 'item-artwork':
            status = await run_in_threadpool(manager.assets.item_artwork.status)
            return JSONResponse({'active': status['active'], 'revision': status['revision']})
        item = re.fullmatch(r'item-artwork/([0-9]{1,3})\.png', path)
        if item:
            image = await run_in_threadpool(manager.assets.item_artwork.path, int(item[1]),
                                            version=adventure['version'])
            if image is None:
                raise HTTPException(404)
            return FileResponse(image, media_type='image/png')
        if path.startswith('static/') and request.method in {'GET', 'HEAD'}:
            asset = path.removeprefix('static/')
            if asset in {'routes.js', 'tokens.css', 'panel.css', 'panel.js', 'panel-trading.css',
                         'adventure-trading.js', 'trade-progress.js', 'trade-ui.js', 'trade-tabs.js',
                         'fonts/pokesim-panel.woff2', 'mon-grid.js',
                         'mon-grid.css', 'types.js', 'types.css'}:
                return FileResponse(STATIC / asset)
        sprite = re.fullmatch(r'sprites/(shiny/)?([0-9]{1,3})\.png', path)
        if sprite and request.method in {'GET', 'HEAD'}:
            dex = int(sprite[2])
            if not 1 <= dex <= 251:
                raise HTTPException(404)
            image = await run_in_threadpool(manager.assets.sprite_path, aid, dex, bool(sprite[1]))
            if image is None and sprite[1]:
                # No shiny artwork (Generation I, or a cartridge that could not be read): the
                # normal portrait stands in.
                image = await run_in_threadpool(manager.assets.sprite_path, aid, dex)
                path = f'sprites/{dex}.png'
            if image is not None:
                return FileResponse(image, media_type='image/png')
        stopped_view = None
        if (adventure['state'] in {'stopped', 'failed'} and not adventure['archived']
                and request.method in {'GET', 'HEAD'}):
            # A stopped adventure is shown read only from its newest save.
            try:
                stopped_view = await run_in_threadpool(manager.supervisor.viewer, aid)
            except AdventureRunning:
                # The registry still says stopped while a start brings the worker up. The page
                # asks again once the adventure reports running.
                log.info('Adventure %s is starting, so it has no stopped view', aid)
                retry = {'Retry-After': '2'}
                if path in GAME_PAGES:
                    return HTMLResponse('<!doctype html><title>PokeSim</title><p>This adventure is starting. Reload in a moment.</p>',
                                        status_code=503, headers=retry)
                raise HTTPException(503, 'This adventure is starting', headers=retry)
            except (RuntimeError, OSError, KeyError):
                log.info('Adventure %s has no stopped view', aid, exc_info=True)
        if stopped_view is None and adventure['state'] not in {'running', 'recovering'}:
            if path in GAME_PAGES and viewer:
                return HTMLResponse('<!doctype html><title>PokeSim</title><p>This adventure is not running right now.</p>', status_code=409)
            if path in GAME_PAGES:
                from ..web.library import render_library
                return HTMLResponse(render_library('stopped', adventure))
            raise HTTPException(409, 'This adventure is stopped or starting')
        if path in {'frame.jpg', 'stream'}:
            active = next((row for row in await run_in_threadpool(manager.registry.transactions, True)
                           if aid in row['plan']['participants'] and row['decision'] is None), None)
            if active:
                side = 'left' if active['plan']['participants'][0] == aid else 'right'
                preview_path = (manager.root / 'interactions' / active['id'] / 'attempts'
                                / active['plan']['attempt_id'] / 'outputs' / (side + '.jpg'))
                if path == 'frame.jpg':
                    raw = await run_in_threadpool(read_preview, preview_path)
                    if raw is not None:
                        return Response(raw, media_type='image/jpeg')
                elif await run_in_threadpool(preview_path.is_file):
                    async def provisional_frames():
                        checked = time.monotonic()
                        try:
                            while not manager.closing:
                                if time.monotonic() - checked >= STREAM_RECHECK_SECONDS:
                                    if not await run_in_threadpool(still_allowed, request, aid):
                                        break
                                    checked = time.monotonic()
                                current = await run_in_threadpool(manager.registry.transaction, active['id'])
                                if current['decision'] is not None:
                                    break
                                raw = await run_in_threadpool(preview_path.read_bytes)
                                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + raw + b'\r\n'
                                await asyncio.sleep(0.1)
                        except (OSError, asyncio.CancelledError):
                            return
                    return StreamingResponse(provisional_frames(), media_type='multipart/x-mixed-replace',
                                             headers={'Content-Type': 'multipart/x-mixed-replace' + chr(59) + ' boundary=frame'})
        child = stopped_view or manager.supervisor.child(aid)
        if request.method == 'POST' and await run_in_threadpool(manager.coordinator.reserved, aid):
            raise HTTPException(409, 'A trade holds this adventure')
        if app.state.children is None:
            app.state.children = httpx.AsyncClient(
                trust_env=False, timeout=httpx.Timeout(20, read=30),
                limits=httpx.Limits(max_connections=None, max_keepalive_connections=32))
        client = app.state.children
        target = httpx.URL(child.url).copy_with(path='/' + path, query=request.scope['query_string'])
        headers = {'Authorization': 'Bearer ' + child.token, **({VIEWER_HEADER: '1'} if viewer else {}),
                   **({ROLE_HEADER: role} if role in {'player', 'manager'} else {})}
        if request.headers.get('content-type'):
            headers['Content-Type'] = request.headers['content-type']
        if path == 'api/pokedex' and request.headers.get('if-none-match'):
            # The species reference only changes with the cartridge, so browsers revalidate it.
            headers['If-None-Match'] = request.headers['if-none-match']
        try:
            response = await client.send(client.build_request(request.method, target, content=body, headers=headers), stream=True)
        except httpx.HTTPError as error:
            raise HTTPException(503, 'The adventure is reconnecting') from error
        if (path in GAME_PAGES and request.method == 'GET' and response.status_code == 200
                and response.headers.get('content-type', '').startswith('text/html')):
            # The adventure renders its pages without knowing which portraits the library
            # serves for it, so the library stamps them here. Pages are a few kilobytes.
            try:
                page = await response.aread()
            finally:
                await response.aclose()
            stamp = await run_in_threadpool(manager.assets.sprite_version, aid)
            meta = SPRITE_META % stamp
            if manager.leases.enforced:
                # The page asks the library who holds control only when there is a lease to ask about.
                meta += LEASE_META
            page = page.replace((SPRITE_META % SPRITE_VERSION).encode(), meta.encode(), 1)
            return Response(page, status_code=200, media_type=response.headers['content-type'])
        async def stream():
            # Decode here rather than forwarding raw bytes: `content-encoding` is not one of
            # the headers that survive below, so a compressed child response would otherwise
            # reach the browser as undeclared gzip.
            checked = time.monotonic()
            try:
                async for chunk in response.aiter_bytes():
                    if path == 'stream' and time.monotonic() - checked >= STREAM_RECHECK_SECONDS:
                        if not await run_in_threadpool(still_allowed, request, aid):
                            return
                        checked = time.monotonic()
                    yield chunk
            finally:
                await response.aclose()
        safe_headers = {key: value for key, value in response.headers.items()
                        if key.lower() in {'content-type', 'cache-control', 'location', 'content-disposition', 'etag',
                                           'x-audio-state', 'x-audio-sequence', 'x-audio-rate', 'x-audio-speed',
                                           'x-audio-mode', 'x-audio-dropped'}}
        return StreamingResponse(stream(), status_code=response.status_code, headers=safe_headers)

    return app


def configure_logging(root):
    """Windowed bundles have no console streams, including during Uvicorn setup."""
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = (root / 'manager-output.log').open('a', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = (root / 'manager-errors.log').open('a', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.basicConfig(level=logging.INFO, format=formatter._fmt)
    handler = RotatingFileHandler(root / 'manager.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    return handler


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='pokesim',
        description='Run one PokeSim application with multiple adventures',
        epilog='Commands: adventures (list, create, start, stop), import, import-pair, backup, '
               'restore, admin, desktop, legacy. Each takes its own --help, for example '
               '"pokesim adventures create --help". Running pokesim with no command serves the library.')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--public-url')
    parser.add_argument('--game-data-dir', type=Path)
    parser.add_argument('--reference-archive', type=Path)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    root = args.data_dir or (user_directory() / 'library' if args.desktop else Path(os.environ.get('POKESIM_APP_DIR', 'pokesim-app')))
    host = args.host or ('127.0.0.1' if args.desktop else os.environ.get('HOST', '127.0.0.1'))
    port = args.port if args.port is not None else (0 if args.desktop else int(os.environ.get('PORT', '8000')))
    configure_logging(root)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    import uvicorn
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Accepted sockets inherit this. Without it every response on a reused
        # connection waits out a 40 ms delayed acknowledgement before its body is sent.
        listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        listener.bind((host, port))
        listener.listen(128)
        actual_port = listener.getsockname()[1]
        browser_host = '127.0.0.1' if host in {'0.0.0.0', '::'} else host
        public_url = args.public_url or os.environ.get('PUBLIC_URL') or f'http://{browser_host}:{actual_port}'
        # The desktop app serves one person on their own machine, so it opens without a login
        # unless AUTH asks for one. A server decides from its library (see resolve_auth).
        auth = 'none' if args.desktop and not os.environ.get('AUTH') else 'auto'
        try:
            manager = Manager(root, public_url, game_data_dir=args.game_data_dir,
                              reference_archive=args.reference_archive, auth=auth)
        except BlockingIOError:
            identity = json.loads((root / 'manager.json').read_text(encoding='utf-8'))
            if args.desktop and not args.no_browser:
                webbrowser.open(identity['url'])
            return
        identity = {'url': public_url, 'application_id': manager.registry.setting('application_id')}
        CheckpointStore.atomic_write(manager.root / 'manager.json', json.dumps(identity).encode())
        manager.bootstrap_admin(os.environ.get('POKESIM_ADMIN_USER', '').strip(), os.environ.get('POKESIM_ADMIN_PASSWORD', ''))
        manager.issue_cli_token()
        server = None
        app = create_app(manager, shutdown=lambda: setattr(server, 'should_exit', True))
        # Forwarded addresses are read only from proxies that AUTH_TRUSTED_PROXIES names
        # (see client_address), never from whoever connects.
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=actual_port, proxy_headers=False,
                                             loop='asyncio', log_level='warning', timeout_graceful_shutdown=60))
        if args.desktop and not args.no_browser:
            def open_browser():
                for _ in range(200):
                    if server.started:
                        webbrowser.open(public_url)
                        return
                    time.sleep(0.05)
            threading.Thread(target=open_browser, daemon=True).start()
        log.info('PokeSim library: %s', public_url)
        try:
            server.run(sockets=[listener])
        finally:
            manager.close()


if __name__ == '__main__':
    main()
