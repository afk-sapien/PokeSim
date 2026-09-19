"""Lifecycle failures must reach the launcher after resources are closed."""
from unittest.mock import Mock

import pytest

from pokesim import __main__ as server, config
from pokesim.emulator import Emulator
from pokesim.web import app as web
from pokesim.runtime import Runtime


@pytest.fixture
def server_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'NTFY_URL', '')
    monkeypatch.setattr(config, 'validate', Mock())
    monkeypatch.setattr('pokesim.game_data.load', Mock())
    emu = Mock(spec=Emulator)
    emu.fatal_error = None
    emu.stopping = False
    emu.thread = Mock()
    emu.thread.ident = 123
    emu.thread.is_alive.return_value = True
    emu.pb = Mock()
    monkeypatch.setattr('pokesim.emulator.Emulator', Mock(return_value=emu))
    monkeypatch.setattr(web, 'create_app', Mock())
    monkeypatch.setattr(server.uvicorn, 'Server', Mock())
    return emu


def test_server_exit_reports_final_save_failure(server_runtime):
    def stop():
        server_runtime.fatal_error = 'The final save failed.'
        server_runtime.thread.is_alive.return_value = False
    server_runtime.stop.side_effect = stop
    with pytest.raises(SystemExit) as error:
        server.legacy_main()
    assert error.value.code != 0
    server_runtime.stop.assert_called_once()


def test_server_exit_succeeds_after_final_save(server_runtime):
    server_runtime.stop.side_effect = lambda: setattr(server_runtime.thread.is_alive, 'return_value', False)
    server.legacy_main()
    server_runtime.stop.assert_called_once()


def test_start_failure_closes_unstarted_emulator_and_releases_lock(server_runtime, tmp_path):
    server_runtime.thread.is_alive.return_value = False
    server_runtime.thread.ident = None
    server_runtime.start.side_effect = ValueError('Incompatible checkpoint')
    failed = Runtime(tmp_path)
    with pytest.raises(ValueError, match='Incompatible'):
        with failed:
            pytest.fail('Startup should fail')
    server_runtime.pb.stop.assert_called_once_with(save=False)
    assert failed.lock is None and failed.store is None
    server_runtime.start.side_effect = None
    with Runtime(tmp_path):
        pass


def test_runtime_lock_blocks_another_emulator_process(server_runtime, tmp_path):
    import subprocess
    import sys
    script = '''
import sys
from pathlib import Path
from pokesim.platform_io import lock_file
with (Path(sys.argv[1]) / 'adventure.lock').open('a+b') as stream:
    try:
        lock_file(stream)
    except BlockingIOError:
        sys.exit(7)
'''
    server_runtime.stop.side_effect = lambda: setattr(server_runtime.thread.is_alive, 'return_value', False)
    with Runtime(tmp_path):
        assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 7
        with pytest.raises(RuntimeError, match='already open'):
            with Runtime(tmp_path):
                pytest.fail('A second emulator must not start')
        server_runtime.start.assert_called_once()
    assert subprocess.run([sys.executable, '-c', script, str(tmp_path)]).returncode == 0


def test_stop_timeout_retains_database_and_lock_until_worker_exits(server_runtime, tmp_path):
    runtime = Runtime(tmp_path)
    runtime.__enter__()
    store = runtime.store
    server_runtime.stop.side_effect = RuntimeError('Worker did not stop')

    def finish_worker():
        assert runtime.lock is not None and not runtime.lock.closed
        store.set('still-open', True)
        server_runtime.thread.is_alive.return_value = False
    server_runtime.thread.join.side_effect = finish_worker
    with pytest.raises(RuntimeError, match='did not stop'):
        runtime.close()
    assert runtime.store is None and runtime.lock is None
    runtime.close()


def test_failed_final_save_closes_store_and_releases_lock(server_runtime, tmp_path):
    def stop():
        server_runtime.fatal_error = 'The final save failed.'
        server_runtime.thread.is_alive.return_value = False
    server_runtime.stop.side_effect = stop
    runtime = Runtime(tmp_path)
    with pytest.raises(RuntimeError, match='final save failed'):
        with runtime:
            pass
    assert runtime.store is None and runtime.lock is None


def test_earlier_error_is_not_hidden_by_shutdown_failure(server_runtime, tmp_path):
    server_runtime.stop.side_effect = RuntimeError('Shutdown also failed')
    server_runtime.thread.join.side_effect = lambda: setattr(server_runtime.thread.is_alive, 'return_value', False)
    runtime = Runtime(tmp_path)
    with pytest.raises(ValueError, match='Original error'):
        with runtime:
            raise ValueError('Original error')
    assert runtime.store is None and runtime.lock is None
