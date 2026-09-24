import io
import json
import queue
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import AdventureLock
from pokesim.runtime.worker import Bootstrap, WorkerAuthorization


@pytest.fixture
def settings(tmp_path):
    rom = tmp_path / 'red.gb'
    rom.write_bytes(b'ROM fixture')
    return {'rom_path': str(rom), 'data_dir': str(tmp_path / 'game'),
            'game_data_dir': str(tmp_path / 'reference')}


def test_settings_validate_types_paths_and_remain_immutable(settings):
    parsed = SimulationSettings.from_dict(settings)
    with pytest.raises(FrozenInstanceError):
        parsed.speed = 2
    for update in ({'speed': float('nan')}, {'speed': True}, {'autosave_seconds': 1.5},
                   {'viewer_only': 'false'}, {'rom_path': 'relative.gb'},
                   {'public_url': 'http://user:secret@example.com'}, {'unknown': 'value'}):
        with pytest.raises(ValueError):
            SimulationSettings.from_dict({**settings, **update})
    assert SimulationSettings.from_dict(parsed.to_dict()) == parsed


def test_bootstrap_is_strict_and_does_not_expose_token_in_repr(settings):
    token = 'private-secret' * 4
    value = {'protocol': 1, 'adventure_id': 'red-1', 'generation': 'generation-1',
             'token': token, 'settings': settings}
    bootstrap = Bootstrap.read(io.StringIO(json.dumps(value) + '\n'))
    assert token not in repr(bootstrap)
    assert bootstrap.adventure_name == 'red-1'
    for update in ({'protocol': 2}, {'adventure_id': '../escape'}, {'token': 'short'}, {'extra': True}):
        with pytest.raises(ValueError):
            Bootstrap.read(io.StringIO(json.dumps({**value, **update}) + '\n'))
    with pytest.raises(ValueError):
        Bootstrap.read(io.StringIO(json.dumps(value)))


def test_every_worker_route_requires_private_credential():
    app = FastAPI()

    @app.get('/frame.jpg')
    def frame():
        return {'ok': True}

    with TestClient(WorkerAuthorization(app, 'secret')) as client:
        assert client.get('/frame.jpg').status_code == 401
        assert client.get('/does-not-exist').status_code == 401
        assert client.get('/frame.jpg', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.get('/frame.jpg', headers={'Authorization': 'Bearer secret'}).status_code == 200


def test_adventure_lock_excludes_all_launch_modes_and_releases(tmp_path):
    script = '''
import sys
from pokesim.runtime.simulation import AdventureLock
try:
    with AdventureLock(sys.argv[1]):
        pass
except BlockingIOError:
    sys.exit(9)
'''
    with AdventureLock(tmp_path):
        assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 9
    assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 0


def test_runtime_call_runs_on_emulator_thread_and_reports_exceptions():
    from pokesim.emulator import Emulator
    emu = object.__new__(Emulator)
    emu.commands = queue.Queue()

    def run():
        for _ in range(2):
            name, arg = emu.commands.get(timeout=3)
            emu._handle_command(name, arg)

    emu.thread = threading.Thread(target=run)
    emu.thread.start()
    assert emu.call(lambda: threading.current_thread().ident) == emu.thread.ident

    def fails():
        raise ValueError('Owned operation failed')

    with pytest.raises(ValueError, match='Owned operation failed'):
        emu.call(fails)
    emu.thread.join(timeout=3)
    assert not emu.thread.is_alive()
    with pytest.raises(RuntimeError, match='not running'):
        emu.call(lambda: None)
