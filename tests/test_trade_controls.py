"""Only trusted trade requests can hold or release an adventure."""
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from pokesim import config
from pokesim.emulator import Emulator
from pokesim.store import Store
from pokesim.web.app import create_app


def test_trade_endpoint_requires_the_configured_token(tmp_path, monkeypatch):
    store = Store(tmp_path)
    emu = Mock()
    emu.trade.return_value = {'phase': 'prepared'}
    monkeypatch.setattr(config, 'TRADE_TOKEN', 'private-test-token')
    with TestClient(create_app(emu, store)) as client:
        body = {'action': 'prepare', 'value': '123'}
        assert client.post('/api/trade', json=body).status_code == 403
        assert client.post('/api/trade', json=body, headers={'Authorization': 'Bearer wrong'}).status_code == 403
        emu.trade.assert_not_called()
        assert client.post('/api/trade', json=body, headers={'Authorization': 'Bearer private-test-token'}).status_code == 200
    store.close()


def test_manual_resume_cannot_bypass_a_durable_trade_hold(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.set('trade_hold', {'id': '123', 'phase': 'prepared'})
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    emu = Mock()
    with TestClient(create_app(emu, store)) as client:
        assert client.post('/api/control', json={'action': 'resume'}).status_code == 409
    emu.command.assert_not_called()
    store.close()


def test_loading_an_already_released_trade_does_not_rewind(tmp_path):
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.store.set('trade_barrier', '123')
    emu._load_state_file = Mock()
    assert emu._trade('load', '123')['phase'] == 'released'
    assert emu._trade('release', '123')['phase'] == 'released'
    emu._load_state_file.assert_not_called()
    with pytest.raises(ValueError, match='not committed'):
        emu._trade('load', '122')
    emu.store.close()


def test_a_trade_hold_prevents_shutdown_autosaves_from_publishing_old_memory(tmp_path):
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.store.set('trade_hold', {'id': '123', 'phase': 'prepared'})
    emu._state_bytes = Mock()
    emu._autosave()
    emu._state_bytes.assert_not_called()
    emu.store.close()
