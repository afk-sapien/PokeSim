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
from urllib.parse import urlsplit
import webbrowser

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.background import BackgroundTask

from ..checkpoints import CheckpointStore
from ..desktop_setup import MAX_ROM, user_directory
from ..platform_io import lock_file
from ..web.security import protect_response, public_origin
from .assets import Assets
from .registry import Registry, identifier, validate_id
from .supervisor import Supervisor

log = logging.getLogger(__name__)
STATIC = Path(__file__).parents[1] / 'web' / 'static'
GAME_READ_PATHS = {'', 'pokedex', 'team', 'journey', 'pc', 'journal', 'trading',
                   'api/pokedex', 'api/pokedex/status', 'api/trading', 'api/interactions',
                   'api/state', 'api/events', 'api/states', 'healthz', 'frame.jpg', 'stream', 'feed.xml'}


def public_game_path(method, path):
    """Allow public routes before HTTP client URL normalization can change them."""
    if method == 'POST':
        return path in {'api/control', 'api/trading/preferences'}
    if method not in {'GET', 'HEAD'}:
        return False
    if path in GAME_READ_PATHS:
        return True
    if any(part in {'', '.', '..'} for part in path.split('/')):
        return False
    return bool(re.fullmatch(r'(?:api/events|events)/[0-9]+|(?:sprites|shots)/[0-9]+\.png'
                             r'|static/[A-Za-z0-9_.-]+|static/fonts/[A-Za-z0-9_.-]+', path))


class Manager:
    def __init__(self, root, public_url='http://127.0.0.1:8000', *, game_data_dir=None,
                 reference_archive=None, child_factory=None):
        self.public_url = public_origin(public_url)
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / 'application.lock').open('a+b')
        try:
            lock_file(self.lock)
            self.registry = Registry(self.root)
        except BaseException:
            self.lock.close()
            raise
        self.assets = Assets(self.registry, game_data_dir, reference_archive)
        self.supervisor = Supervisor(self.registry, self.assets, self.public_url,
                                     **({'child_factory': child_factory} if child_factory else {}))
        from .notifications import NotificationCenter
        self.notifications = NotificationCenter(self.registry, self.supervisor, self.public_url)
        self.maintenance = threading.RLock()
        self.supervisor.admission = self.maintenance
        self.suspended = False
        self.closing = False
        self._closed = False
        self.tasks = set()
        self.sessions = {}
        self.session_lock = threading.Lock()
        from .coordinator import Coordinator
        self.coordinator = Coordinator(self)

    @staticmethod
    def validate_adventure_settings(values):
        allowed = {'starter', 'policy', 'auto_start', 'seed', 'fast_text', 'battle_animations',
                   'autosave_seconds', 'keep_autosaves', 'stream_fps', 'viewer_only', 'league_rewards',
                   'mew_event', 'event_retention_days'}
        if not isinstance(values, dict) or not set(values) <= allowed:
            raise ValueError('Unsupported adventure settings')
        result = {'starter': 'random', 'policy': 'strategic', 'auto_start': False, **values}
        if result['starter'] not in {'random', 'bulbasaur', 'charmander', 'squirtle'}:
            raise ValueError('Choose a listed starter')
        if result['policy'] not in {'strategic', 'guided_random', 'smart_random'}:
            raise ValueError('Unknown adventure policy')
        for name in ('auto_start', 'fast_text', 'battle_animations', 'viewer_only', 'league_rewards', 'mew_event'):
            if name in result and type(result[name]) is not bool:
                raise ValueError(f'{name} must be a boolean')
        # Every notable event keeps a full save state beside its screenshot, which is about
        # 40 MB an hour, so an adventure needs a way to bound its own journal. Zero keeps all.
        for name, low, high in [('autosave_seconds', 1, 86400), ('keep_autosaves', 1, 10000),
                                ('stream_fps', 1, 60), ('event_retention_days', 0, 36500)]:
            if name in result and (type(result[name]) is not int or not low <= result[name] <= high):
                raise ValueError(f'{name} must be between {low} and {high}')
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
                return self.supervisor.start(aid)
        except Exception as error:
            row = self.registry.adventure(aid)
            if row['desired_state'] == 'running':
                self.registry.update(aid, state='failed', error=str(error))
            raise

    def check_available(self):
        if self.suspended or self.closing:
            raise ValueError('PokeSim is saving, backing up, or shutting down')

    def start(self):
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

    def close(self):
        if self._closed:
            return
        self.closing = True
        self.coordinator.close()
        errors = self.supervisor.close()
        if errors:
            log.error('Shutdown requires attention: %s', ', '.join(errors))
        self.registry.close()
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

    def browser_session(self, request):
        session_id = request.cookies.get('pokesim_session', '')
        with self.session_lock:
            session = self.sessions.get(session_id)
            if session and session['expires'] > time.time():
                return session
        return None


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


GAME_ASSET = re.compile(r'/games/[A-Za-z0-9_-]+/(static|sprites|shots)/')


def cache_policy(path, query, content_type):
    """How long a browser may reuse a response without asking again.

    Pages reference their stylesheets and scripts with a ?v= stamp that changes with
    the file, so those never need a round trip. Everything live stays uncached.
    """
    game = GAME_ASSET.match(path)
    kind = game[1] if game else ('static' if path.startswith('/static/') else None)
    if kind == 'static':
        if 'v=' in query:
            return 'public, max-age=31536000, immutable'
        if path.endswith('.woff2'):
            return 'public, max-age=604800'
        return 'no-cache'
    if kind == 'sprites' and content_type.startswith('image/png'):
        return 'private, max-age=86400'
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

    @app.exception_handler(RuntimeError)
    async def unavailable(request, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.middleware('http')
    async def access(request, call_next):
        expected = urlsplit(manager.public_url)
        if request.headers.get('host') != expected.netloc:
            return JSONResponse({'detail': 'Use the configured PokeSim address'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != f'{expected.scheme}://{expected.netloc}':
            return JSONResponse({'detail': 'Requests must come from this PokeSim application'}, status_code=403)
        changing = request.method not in {'GET', 'HEAD', 'OPTIONS'}
        if request.headers.get('sec-fetch-site') == 'cross-site' and (changing or request.url.path == '/api/v1/session'):
            return JSONResponse({'detail': 'Requests must come from this PokeSim application'}, status_code=403)
        if changing:
            session = manager.browser_session(request)
            csrf = request.headers.get('x-pokesim-csrf', '')
            if session is None or not csrf.isascii() or not hmac.compare_digest(csrf, session['csrf_token']):
                return JSONResponse({'detail': 'Reload this page before making changes'}, status_code=403)
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
    @app.get('/trading', response_class=HTMLResponse)
    @app.get('/notifications', response_class=HTMLResponse)
    @app.get('/settings', response_class=HTMLResponse)
    def home(request: Request):
        from ..web.library import render_library
        return render_library(request.url.path.strip('/') or 'library')

    @app.get('/health/live')
    def live():
        return {'ok': not manager.closing, 'application_id': manager.registry.setting('application_id')}

    @app.get('/health/ready')
    def ready():
        return {'ok': not manager.closing, 'adventures': len(manager.registry.adventures())}

    @app.get('/api/v1/session')
    def session(request: Request):
        current = manager.browser_session(request)
        if current is not None:
            return {'csrf_token': current['csrf_token'], 'role': current['role']}
        session_id = secrets.token_urlsafe(32)
        current = {'csrf_token': secrets.token_urlsafe(32), 'role': 'owner', 'expires': time.time() + 86400}
        with manager.session_lock:
            manager.sessions = {key: value for key, value in manager.sessions.items() if value['expires'] > time.time()}
            if len(manager.sessions) >= 1024:
                raise HTTPException(429, 'Too many active browser sessions')
            manager.sessions[session_id] = current
        response = JSONResponse({'csrf_token': current['csrf_token'], 'role': current['role']})
        response.set_cookie('pokesim_session', session_id, httponly=True, samesite='strict',
                            secure=manager.public_url.startswith('https:'), max_age=86400)
        return response

    @app.get('/api/v1/adventures')
    def adventures():
        return {'adventures': manager.registry.adventures()}

    @app.get('/api/v1/adventures/{aid}')
    def adventure(aid: str):
        return manager.registry.adventure(aid)

    @app.get('/api/v1/adventures/{aid}/trade-inventory')
    def trade_inventory(aid: str):
        manager.registry.adventure(aid)
        return manager.coordinator.inventory(aid)

    @app.get('/api/v1/assets')
    def assets():
        return {'roms': manager.registry.roms()}

    @app.post('/api/v1/assets/rom')
    async def add_rom(request: Request):
        manager.check_available()
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_ROM:
                raise HTTPException(413, 'ROM files may be no larger than 1 MB')
        return await asyncio.to_thread(manager.assets.install_rom, bytes(raw))

    @app.post('/api/v1/adventures')
    async def create(request: Request):
        manager.check_available()
        data = await json_body(request)
        settings = manager.validate_adventure_settings({
            'starter': data.get('starter', 'random'),
            'league_rewards': data.get('league_rewards', True),
            'mew_event': data.get('mew_event', True),
        })
        return manager.registry.create(data.get('name', ''), data.get('rom_id', ''), settings,
                                       data.get('request_id', identifier()))

    @app.post('/api/v1/adventures/{aid}/start')
    async def start(aid: str, request: Request):
        manager.check_available()
        adventure = manager.registry.adventure(aid)
        if adventure['archived']:
            raise ValueError('Restore this adventure before starting')
        data = await json_body(request)
        active = [row for row in manager.registry.adventures() if row['state'] in {'running', 'starting', 'recovering'}]
        if aid not in {row['id'] for row in active} and len(active) >= manager.registry.setting('max_running', 2):
            raise ValueError('The running adventure limit has been reached. Stop a game or change Settings.')
        if manager.registry.request_lifecycle(aid, 'start', data.get('request_id', identifier())):
            manager.registry.update(aid, state='starting', error=None)
            manager.background(manager.start_adventure, aid)
        return manager.registry.adventure(aid)

    @app.post('/api/v1/adventures/{aid}/stop')
    async def stop(aid: str, request: Request):
        manager.check_available()
        manager.registry.adventure(aid)
        data = await json_body(request)
        if not manager.registry.request_lifecycle(aid, 'stop', data.get('request_id', identifier())):
            return manager.registry.adventure(aid)
        if manager.coordinator.reserved(aid):
            return manager.registry.update(aid, summary={'message': 'Will stop after the pending trade is resolved'})
        manager.background(manager.start_adventure, aid)
        return manager.registry.adventure(aid)

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
            if 'speed' in changes:
                raise ValueError('Set the pace for all adventures in Library Settings')
            if adventure['state'] == 'running' and set(changes) - {'auto_start'}:
                raise ValueError('Stop the adventure before changing these settings')
            previous = {key: value for key, value in adventure['settings'].items() if key != 'speed'}
            values['settings'] = manager.validate_adventure_settings({**previous, **changes})
        return manager.registry.update(aid, **values) if values else adventure

    @app.get('/api/v1/settings')
    def settings():
        return {'max_running': manager.registry.setting('max_running', 2),
                'speed': manager.registry.setting('speed', 1), 'data_dir': str(manager.root)}

    @app.patch('/api/v1/settings')
    async def set_settings(request: Request):
        manager.check_available()
        data = await json_body(request)
        if not data or set(data) - {'max_running', 'speed'}:
            raise ValueError('Unsupported application settings')
        if 'max_running' in data:
            maximum = data['max_running']
            if type(maximum) is not int or not 1 <= maximum <= 32:
                raise ValueError('Running adventure limit must be between 1 and 32')
        if 'speed' in data:
            from ..runtime.settings import validate_speed
            validate_speed(data['speed'])
        pending = []
        if 'speed' in data:
            pending = await asyncio.to_thread(manager.supervisor.set_speed, data['speed'])
        if 'max_running' in data:
            manager.registry.set_setting('max_running', data['max_running'])
        return {**settings(), 'pace_pending': pending}

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

    @app.get('/api/v1/interactions')
    def interactions():
        return manager.coordinator.status()

    @app.post('/api/v1/interactions/trades')
    async def trade(request: Request):
        manager.check_available()
        data = await json_body(request)
        row = await asyncio.to_thread(manager.coordinator.propose, data)
        manager.background(manager.coordinator.execute, row['id'])
        return row

    @app.post('/api/v1/interactions/{tid}/cancel')
    async def cancel(tid: str):
        return await asyncio.to_thread(manager.coordinator.cancel, tid)

    @app.post('/api/v1/interactions/{tid}/recover')
    async def recover(tid: str):
        manager.registry.transaction(tid)
        manager.background(manager.coordinator.recover_one, tid)
        return manager.registry.transaction(tid)

    @app.get('/api/v1/backups')
    def backups():
        directory = manager.root / 'backups'
        return {'backups': [{'id': path.stem, 'path': str(path), 'created_at': path.stat().st_mtime}
                            for path in sorted(directory.glob('*.zip'), reverse=True)]}

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
            return await asyncio.to_thread(import_archive, manager, path)
        finally:
            path.unlink(missing_ok=True)

    @app.post('/api/v1/shutdown')
    def quit_app():
        return JSONResponse({'ok': True}, background=BackgroundTask(shutdown))

    @app.api_route('/games/{aid}/{path:path}', methods=['GET', 'POST', 'HEAD'])
    async def game(aid: str, path: str, request: Request):
        if not public_game_path(request.method, path):
            raise HTTPException(404)
        adventure = manager.registry.adventure(aid)
        if path == 'trading' and request.method in {'GET', 'HEAD'}:
            from ..web.pages import render_game_page
            return HTMLResponse(render_game_page('adventure-trading.html', base_path=f'/games/{aid}',
                adventure_id=aid, adventure_name=adventure['name']))
        if path == 'api/interactions' and request.method in {'GET', 'HEAD'}:
            return JSONResponse(manager.coordinator.adventure_status(aid))
        if path.startswith('static/') and request.method in {'GET', 'HEAD'}:
            asset = path.removeprefix('static/')
            if asset in {'routes.js', 'tokens.css', 'panel.css', 'panel.js', 'panel-trading.css',
                         'adventure-trading.js', 'fonts/pokesim-panel.woff2'}:
                return FileResponse(STATIC / asset)
        sprite = re.fullmatch(r'sprites/([0-9]{1,3})\.png', path)
        if sprite and request.method in {'GET', 'HEAD'}:
            dex = int(sprite[1])
            if not 1 <= dex <= 151:
                raise HTTPException(404)
            image = manager.assets.sprite_path(aid, dex)
            if image is not None:
                return FileResponse(image, media_type='image/png')
        if adventure['state'] not in {'running', 'recovering'}:
            if path in {'', 'pc', 'pokedex', 'journal', 'trading'}:
                from ..web.library import render_library
                return HTMLResponse(render_library('stopped', adventure))
            raise HTTPException(409, 'This adventure is stopped or starting')
        if path in {'frame.jpg', 'stream'}:
            active = next((row for row in manager.registry.transactions(True)
                           if aid in row['plan']['participants'] and row['decision'] is None), None)
            if active:
                side = 'left' if active['plan']['participants'][0] == aid else 'right'
                preview_path = (manager.root / 'interactions' / active['id'] / 'attempts'
                                / active['plan']['attempt_id'] / 'outputs' / (side + '.jpg'))
                if preview_path.is_file():
                    if path == 'frame.jpg':
                        return FileResponse(preview_path, media_type='image/jpeg')
                    async def provisional_frames():
                        try:
                            while not manager.closing:
                                current = manager.registry.transaction(active['id'])
                                if current['decision'] is not None:
                                    break
                                raw = preview_path.read_bytes()
                                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + raw + b'\r\n'
                                await asyncio.sleep(0.1)
                        except (OSError, asyncio.CancelledError):
                            return
                    return StreamingResponse(provisional_frames(), media_type='multipart/x-mixed-replace',
                                             headers={'Content-Type': 'multipart/x-mixed-replace' + chr(59) + ' boundary=frame'})
        child = manager.supervisor.child(aid)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, 'Game request is too large')
        body = bytes(body)
        if request.method == 'POST' and manager.coordinator.reserved(aid):
            raise HTTPException(409, 'A trade holds this adventure')
        if app.state.children is None:
            app.state.children = httpx.AsyncClient(
                trust_env=False, timeout=httpx.Timeout(20, read=30),
                limits=httpx.Limits(max_connections=None, max_keepalive_connections=32))
        client = app.state.children
        target = httpx.URL(child.url).copy_with(path='/' + path, query=request.scope['query_string'])
        headers = {'Authorization': 'Bearer ' + child.token}
        if request.headers.get('content-type'):
            headers['Content-Type'] = request.headers['content-type']
        try:
            response = await client.send(client.build_request(request.method, target, content=body, headers=headers), stream=True)
        except httpx.HTTPError as error:
            raise HTTPException(503, 'The adventure is reconnecting') from error
        async def stream():
            # Decode here rather than forwarding raw bytes: `content-encoding` is not one of
            # the headers that survive below, so a compressed child response would otherwise
            # reach the browser as undeclared gzip.
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
        safe_headers = {key: value for key, value in response.headers.items()
                        if key.lower() in {'content-type', 'cache-control', 'location'}}
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
               'restore, desktop, legacy. Each takes its own --help, for example '
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
        try:
            manager = Manager(root, public_url, game_data_dir=args.game_data_dir,
                              reference_archive=args.reference_archive)
        except BlockingIOError:
            identity = json.loads((root / 'manager.json').read_text())
            if args.desktop and not args.no_browser:
                webbrowser.open(identity['url'])
            return
        identity = {'url': public_url, 'application_id': manager.registry.setting('application_id')}
        CheckpointStore.atomic_write(manager.root / 'manager.json', json.dumps(identity).encode())
        server = None
        app = create_app(manager, shutdown=lambda: setattr(server, 'should_exit', True))
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=actual_port,
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
