"""Lifecycle failures must reach the launcher after resources are closed."""
from unittest.mock import Mock

import pytest

from pokesim import __main__ as server, config
from pokesim.emulator import Emulator
from pokesim.web import app as web


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
        server.main()
    assert error.value.code != 0
    server_runtime.stop.assert_called_once()


def test_server_exit_succeeds_after_final_save(server_runtime):
    server_runtime.stop.side_effect = lambda: setattr(server_runtime.thread.is_alive, 'return_value', False)
    server.main()
    server_runtime.stop.assert_called_once()
