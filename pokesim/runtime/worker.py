"""Private child process. Bootstrap once over stdin and report readiness as JSON."""
from __future__ import annotations

import hmac
import json
import logging
import os
import socket
import sys
import threading
from dataclasses import dataclass, field

from .settings import SimulationSettings

PROTOCOL = 1
MAX_BOOTSTRAP = 65536
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bootstrap:
    adventure_id: str
    generation: str
    token: str = field(repr=False)
    settings: SimulationSettings
    adventure_name: str = ''

    @classmethod
    def read(cls, stream):
        line = stream.readline(MAX_BOOTSTRAP + 1)
        if not line or len(line) > MAX_BOOTSTRAP or not line.endswith('\n'):
            raise ValueError('Missing or oversized worker bootstrap')
        try:
            data = json.loads(line)
        except (ValueError, UnicodeError) as error:
            raise ValueError('Invalid worker bootstrap JSON') from error
        allowed = {'protocol', 'adventure_id', 'adventure_name', 'generation', 'token', 'settings'}
        if not isinstance(data, dict) or set(data) - allowed or type(data.get('protocol')) is not int or data.get('protocol') != PROTOCOL:
            raise ValueError('Unsupported worker bootstrap protocol')
        for name in ('adventure_id', 'generation'):
            value = data.get(name)
            if not isinstance(value, str) or not value or len(value) > 128 or any(
                    c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in value):
                raise ValueError(f'Invalid {name}')
        token = data.get('token')
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii():
            raise ValueError('Invalid worker credential')
        name = data.get('adventure_name', data['adventure_id'])
        if not isinstance(name, str) or len(name) > 200:
            raise ValueError('Invalid adventure name')
        return cls(data['adventure_id'], data['generation'], token,
                   SimulationSettings.from_dict(data.get('settings')), name)


class WorkerAuthorization:
    """Authenticate every route, including static assets and streaming responses."""
    def __init__(self, app, token):
        self.app = app
        self.credential = ('Bearer ' + token).encode('ascii')

    async def __call__(self, scope, receive, send):
        if scope['type'] in {'http', 'websocket'}:
            headers = dict(scope.get('headers', []))
            if not hmac.compare_digest(headers.get(b'authorization', b''), self.credential):
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                else:
                    await send({'type': 'http.response.start', 'status': 401,
                                'headers': [(b'content-type', b'application/json')]})
                    await send({'type': 'http.response.body', 'body': b'{"detail":"Worker authorization required"}'})
                return
        await self.app(scope, receive, send)


def serve(bootstrap, parent_stream, ready_stream):
    import uvicorn
    from .simulation import SimulationRuntime
    from ..web.app import create_app

    parent_gone = threading.Event()
    finished = threading.Event()

    def watch_parent():
        try:
            while parent_stream.read(1):
                pass
        finally:
            parent_gone.set()
            # A native emulator can hang during startup or shutdown. The manager
            # also supervises deadlines, but an orphan must eventually exit.
            if not finished.wait(45):
                os._exit(2)

    threading.Thread(target=watch_parent, name='parent-liveness', daemon=True).start()
    runtime = SimulationRuntime(bootstrap.settings)
    server = None
    try:
        if parent_gone.is_set():
            return
        runtime.start()
        if parent_gone.is_set():
            return
        app = create_app(runtime.emulator, runtime.store,
                         base_path=f'/games/{bootstrap.adventure_id}',
                         adventure_id=bootstrap.adventure_id, adventure_name=bootstrap.adventure_name)
        app.state.runtime = runtime
        app.state.bootstrap = bootstrap

        @app.get('/internal/health')
        def health():
            return {'protocol': PROTOCOL, 'adventure_id': bootstrap.adventure_id,
                    'generation': bootstrap.generation, 'pid': os.getpid(),
                    'running': runtime.emulator.thread.is_alive(),
                    'error': runtime.emulator.fatal_error}

        @app.post('/internal/shutdown')
        def shutdown():
            server.should_exit = True
            return {'ok': True}

        from .participant import install
        install(app, runtime)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                WorkerAuthorization(app, bootstrap.token), host='127.0.0.1', port=port,
                loop='asyncio', http='h11', ws='none', log_config=None, access_log=False,
                timeout_graceful_shutdown=5))

            def monitor():
                reported = False
                while not finished.wait(0.05):
                    if parent_gone.is_set() or not runtime.emulator.thread.is_alive():
                        server.should_exit = True
                        return
                    if server.started and not reported:
                        ready_stream.write(json.dumps({
                            'protocol': PROTOCOL, 'event': 'ready',
                            'adventure_id': bootstrap.adventure_id,
                            'generation': bootstrap.generation, 'pid': os.getpid(),
                            'host': '127.0.0.1', 'port': port}) + '\n')
                        ready_stream.flush()
                        reported = True

            threading.Thread(target=monitor, name='worker-monitor', daemon=True).start()
            server.run(sockets=[listener])
        if runtime.emulator.fatal_error:
            raise RuntimeError(runtime.emulator.fatal_error)
    finally:
        try:
            runtime.close()
        finally:
            finished.set()


def restore_worker_streams():
    """Windowed Windows bundles still receive explicit child standard handles."""
    if sys.platform == 'win32' and any(value is None for value in (sys.stdin, sys.stdout, sys.stderr)):
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        for name, identifier, mode, flags in (
                ('stdin', -10, 'r', os.O_RDONLY),
                ('stdout', -11, 'w', os.O_WRONLY),
                ('stderr', -12, 'w', os.O_WRONLY)):
            if getattr(sys, name) is not None:
                continue
            handle = kernel.GetStdHandle(identifier & 0xffffffff)
            if handle in (None, ctypes.c_void_p(-1).value):
                continue
            fd = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
            setattr(sys, name, os.fdopen(fd, mode, encoding='utf-8', buffering=1))


def main():
    restore_worker_streams()
    if sys.stdin is None or sys.stdout is None:
        raise SystemExit('Worker mode requires inherited bootstrap pipes')
    ready_stream = sys.stdout
    # Some native dependencies write directly to fd 1. Reserve a duplicate for
    # the protocol and redirect fd 1 itself before importing those libraries.
    if hasattr(ready_stream, 'fileno'):
        try:
            fd = os.dup(ready_stream.fileno())
            ready_stream = os.fdopen(fd, 'w', encoding='utf-8', buffering=1)
            os.dup2(sys.stderr.fileno(), 1)
        except (OSError, AttributeError):
            pass
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        bootstrap = Bootstrap.read(sys.stdin)
        # Install data paths before imports that eagerly load generated tables.
        bootstrap.settings.install()
        serve(bootstrap, sys.stdin, ready_stream)
    except Exception as error:
        log.exception('Adventure worker failed')
        raise SystemExit(1) from error


if __name__ == '__main__':
    main()
