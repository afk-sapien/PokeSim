"""Launch a private local adventure with guided browser setup."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
from urllib.request import ProxyHandler, build_opener
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
import uvicorn

from .checkpoints import CheckpointStore
from .desktop_setup import MAX_ROM, ROM_NAMES, ensure_game_data, install_rom, read_settings, user_directory
from .platform_io import lock_file

STATIC = Path(__file__).parent / 'web' / 'static'
log = logging.getLogger('pokesim.desktop')


class Adventure:
    def __init__(self, root, url, reference_archive=None):
        self.root = root
        self.url = url
        self.reference_archive = reference_archive
        self.thread = None
        self.cancelled = threading.Event()
        self.guard = threading.Lock()
        self.game = None
        self.state = 'setup'
        self.message = 'Choose your game to begin.'
        self.error = None

    def report(self, message):
        with self.guard:
            self.message = message

    def status(self):
        with self.guard:
            return dict(state=self.state, message=self.message, error=self.error,
                        has_rom=(self.root / 'rom.gb').is_file(), data_dir=str(self.root),
                        running=bool(self.thread and self.thread.is_alive()))

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self.cancelled.clear()
            self.state = 'starting'
            self.message = 'Getting your adventure ready…'
            self.error = None
            self.thread = threading.Thread(target=self.run, name='desktop-adventure')
            self.thread.start()

    def run(self):
        runtime = None
        emu = None
        failure = None
        try:
            settings = read_settings(self.root)
            raw = (self.root / 'rom.gb').read_bytes()
            if len(raw) > MAX_ROM or hashlib.sha1(raw).hexdigest() not in ROM_NAMES:
                raise ValueError('The stored ROM is not a clean Red or Blue ROM. Restore rom.gb from your backup.')
            ensure_game_data(self.root / 'game-data', self.report, self.cancelled, self.reference_archive)
            if self.cancelled.is_set():
                return
            self.report('Opening your adventure…')
            from .runtime import SimulationRuntime, SimulationSettings
            runtime = SimulationRuntime(SimulationSettings(
                rom_path=str((self.root / 'rom.gb').resolve()),
                data_dir=str((self.root / 'adventure').resolve()),
                game_data_dir=str((self.root / 'game-data').resolve()),
                public_url=self.url, starter=settings['starter']))
            runtime.start()
            emu = runtime.emulator
            game = runtime.create_app()
            with self.guard:
                self.game = game
                self.state = 'ready'
                self.message = 'Your adventure is running.'
            while not self.cancelled.wait(0.25):
                if not emu.thread.is_alive():
                    raise RuntimeError(emu.fatal_error or 'The adventure stopped unexpectedly. See desktop.log.')
        except Exception as error:
            log.exception('Desktop adventure failed')
            failure = str(error)
        finally:
            with self.guard:
                self.game = None
                self.state = 'stopping'
                self.message = 'Saving your adventure…'
            if runtime is not None:
                try:
                    runtime.close()
                    if emu is not None and emu.fatal_error:
                        failure = emu.fatal_error
                except Exception as error:
                    log.exception('Could not stop the emulator')
                    failure = str(error)
                    if emu is not None:
                        emu.thread.join()
                    runtime.close()
            with self.guard:
                self.error = failure
                self.state = 'error' if failure else 'stopped'
                self.message = 'The adventure needs attention.' if failure else 'Your adventure is saved.'

    def stop(self):
        self.cancelled.set()
        if self.thread:
            self.thread.join(timeout=60)
            if self.thread.is_alive():
                raise RuntimeError('PokeSim is still finishing setup or saving. Wait a moment and try again.')


class GameGateway:
    def __init__(self, adventure):
        self.adventure = adventure

    async def __call__(self, scope, receive, send):
        game = self.adventure.game
        if game is None:
            await RedirectResponse('/desktop')(scope, receive, send)
            return
        if scope['type'] == 'http' and scope['path'] == '/' and scope['method'] == 'GET':
            page = (STATIC / 'index.html').read_text(encoding='utf-8')
            page = page.replace('</nav>', '<a href="/desktop">Desktop</a></nav>', 1)
            await HTMLResponse(page)(scope, receive, send)
            return
        await game(scope, receive, send)


def create_desktop_app(adventure, token, shutdown=lambda: None):
    @asynccontextmanager
    async def lifespan(app):
        if (adventure.root / 'rom.gb').is_file():
            adventure.start()
        try:
            yield
        finally:
            await asyncio.to_thread(adventure.stop)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    mutations = asyncio.Lock()

    @app.middleware('http')
    async def local_requests(request, call_next):
        # Reject rebinding and cross-origin writes to both setup and game APIs.
        expected_host = adventure.url.removeprefix('http://')
        if request.headers.get('host') != expected_host:
            return JSONResponse({'detail': 'Use the local address opened by PokeSim.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin is not None and origin != adventure.url:
            return JSONResponse({'detail': 'Only the local PokeSim page can access this launcher.'}, status_code=403)
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.url.path.startswith('/desktop'):
            if not hmac.compare_digest(request.headers.get('x-pokesim-token', ''), token):
                return JSONResponse({'detail': 'Reload the PokeSim setup page and try again.'}, status_code=403)
        response = await call_next(request)
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path.startswith('/desktop'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/desktop', response_class=HTMLResponse)
    def desktop():
        return (STATIC / 'desktop.html').read_text(encoding='utf-8').replace('__TOKEN__', token)

    @app.get('/desktop/status')
    def status():
        return adventure.status()

    @app.get('/desktop/identity')
    def identity():
        return {'token': token}

    @app.post('/desktop/rom')
    async def rom(request: Request, starter: str = 'random'):
        async with mutations:
            if adventure.status()['running']:
                raise HTTPException(409, 'Wait for the current adventure to finish.')
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_ROM:
                    raise HTTPException(413, 'Choose the .gb game file, no larger than 1 MB.')
            try:
                await asyncio.to_thread(install_rom, adventure.root, bytes(raw), starter)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            except OSError as error:
                log.exception('Could not save the selected ROM')
                raise HTTPException(500, 'Could not save your game file. Check free space and data folder permissions, then try again.') from error
            adventure.start()
            return {'ok': True}

    @app.post('/desktop/start')
    async def start():
        async with mutations:
            if not (adventure.root / 'rom.gb').is_file():
                raise HTTPException(400, 'Choose your ROM first.')
            adventure.start()
            return {'ok': True}

    @app.post('/desktop/quit')
    async def quit_desktop():
        async with mutations:
            try:
                await asyncio.to_thread(adventure.stop)
            except RuntimeError as error:
                raise HTTPException(409, str(error)) from error
            state = adventure.status()
            return JSONResponse({'ok': True, 'error': state['error']}, background=BackgroundTask(shutdown))

    app.mount('/desktop/assets', StaticFiles(directory=STATIC), name='desktop-assets')
    app.mount('/', GameGateway(adventure))
    return app


def existing_url(root):
    """Only reopen a verified local launcher, never an arbitrary saved URL."""
    try:
        data = json.loads((root / 'instance.json').read_text(encoding='utf-8'))
        port = data['port']
        if type(port) is not int or not 1 <= port <= 65535:
            return None
        url = f'http://127.0.0.1:{port}'
        opener = build_opener(ProxyHandler({}))
        with opener.open(url + '/desktop/identity', timeout=2) as response:
            identity = json.load(response)
        if hmac.compare_digest(identity['token'], data['token']):
            return url + '/desktop?launch=1'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def legacy_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=user_directory(), help='Use a separate folder for this adventure')
    parser.add_argument('--no-browser', action='store_true', help='Print the address without opening a browser')
    parser.add_argument('--reference-archive', type=Path, help='Use the pinned reference ZIP for offline first-run setup')
    parser.add_argument('--check-runtime', action='store_true', help='Check dependencies with a demo ROM, then exit')
    args = parser.parse_args(argv)
    if args.check_runtime:
        from .desktop_check import check_runtime
        check_runtime(args.reference_archive)
        return
    root = args.data_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / 'desktop.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    # Windowed bundles have no standard streams. Libraries may still print.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(root / 'desktop-errors.log', 'a', encoding='utf-8')
    with (root / 'desktop.lock').open('a+b') as lock:
        try:
            lock_file(lock)
        except BlockingIOError:
            url = existing_url(root)
            if url:
                print(f'PokeSim is already running: {url}', flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                return
            raise SystemExit(f'PokeSim is already starting or stopping. Try again shortly. Data folder: {root}')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            token = secrets.token_hex(32)
            adventure = Adventure(root, url, args.reference_archive)
            server = None

            def shutdown():
                server.should_exit = True

            app = create_desktop_app(adventure, token, shutdown)
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                                   loop='asyncio', http='h11', ws='none',
                                                   log_config=None, access_log=False,
                                                   timeout_graceful_shutdown=10))
            CheckpointStore.atomic_write(root / 'instance.json', json.dumps({'port': port, 'token': token}).encode())
            browser_done = threading.Event()

            def open_when_ready():
                while not browser_done.wait(0.1):
                    if server.started:
                        print(f'PokeSim: {url}/desktop?launch=1', flush=True)
                        if not args.no_browser:
                            try:
                                webbrowser.open(url + '/desktop?launch=1')
                            except Exception:
                                log.exception('Could not open the browser. Open %s/desktop manually.', url)
                        return

            threading.Thread(target=open_when_ready, daemon=True).start()
            try:
                server.run(sockets=[listener])
            finally:
                browser_done.set()
                adventure.stop()
                (root / 'instance.json').unlink(missing_ok=True)
                logging.getLogger().removeHandler(handler)
                handler.close()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--check-runtime' in args:
        return legacy_main(args)
    from .__main__ import main as application_main
    if args and args[0] in {'--worker', 'worker', '--link-session'}:
        return application_main(args)
    return application_main(['--desktop', *args])


if __name__ == '__main__':
    main()
