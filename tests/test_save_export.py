"""Exports use a private clone and reject unsafe or unverified results."""
from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from pokesim import config, save_export
from pokesim.app.manager import public_game_path
from pokesim.web.app import create_app
from test_events import snap


@pytest.mark.parametrize('battle,kind,held', [(1, 'battle', None), (0, 'dialogue', None),
                                            (0, 'overworld', {'id': 'trade'})])
def test_capture_rejects_unsafe_state_without_sending_inputs(monkeypatch, battle, kind, held):
    emu = SimpleNamespace(store=SimpleNamespace(get=lambda _: held), pb=Mock(), frame=60,
                          _state_bytes=Mock())
    monkeypatch.setattr(save_export, 'read_snapshot', lambda *_: replace(snap(), in_battle=battle))
    monkeypatch.setattr(save_export, 'Screen', lambda _: SimpleNamespace(kind=lambda _: kind))
    with pytest.raises(ValueError):
        save_export.capture(emu)
    emu._state_bytes.assert_not_called()
    assert emu.pb.method_calls == []


def test_unsupported_rom_is_rejected_before_starting_an_emulator(tmp_path, monkeypatch):
    rom = tmp_path / 'unsupported.gb'
    rom.write_bytes(b'unsupported')
    boot = Mock()
    monkeypatch.setattr(save_export, 'CoreEmulator', boot)
    with pytest.raises(ValueError, match='supported English'):
        save_export.export(rom, b'checkpoint')
    boot.assert_not_called()


@pytest.fixture
def export_client(tmp_path, monkeypatch):
    shots = tmp_path / 'shots'
    shots.mkdir()
    emu = SimpleNamespace(rom=tmp_path / 'red.gb', call=lambda function, **_: function())
    store = SimpleNamespace(shots=shots)
    monkeypatch.setattr(save_export, 'capture', lambda _: b'current checkpoint')
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    return TestClient(create_app(emu, store, adventure_name='Red / test'))


def test_export_download_has_private_cache_and_safe_filename(export_client, monkeypatch):
    def export(rom, state):
        assert state == b'current checkpoint'
        return bytes(32768)
    monkeypatch.setattr(save_export, 'export', export)
    response = export_client.post('/api/export-save')
    assert response.status_code == 200
    assert len(response.content) == 32768
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'].endswith('filename="Red-test.sav"')
    assert public_game_path('POST', 'api/export-save')
    assert not public_game_path('GET', 'api/export-save')


def test_export_failure_never_returns_save_bytes(export_client, monkeypatch):
    def export(*_):
        raise ValueError('The exported save did not restore the same progress.')
    monkeypatch.setattr(save_export, 'export', export)
    response = export_client.post('/api/export-save')
    assert response.status_code == 409
    assert 'did not restore' in response.json()['detail']
    assert 'content-disposition' not in response.headers


def test_view_only_cannot_export(export_client, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    capture = Mock()
    monkeypatch.setattr(save_export, 'capture', capture)
    assert export_client.post('/api/export-save').status_code == 403
    capture.assert_not_called()


@pytest.mark.skipif(not os.environ.get('POKESIM_EXPORT_ROM'), reason='Requires a private cartridge and checkpoint')
def test_real_cartridge_export_restarts_with_current_collection():
    from pokesim.checkpoints import open_state
    rom = Path(os.environ['POKESIM_EXPORT_ROM'])
    checkpoint = Path(os.environ['POKESIM_EXPORT_CHECKPOINT'])
    before = checkpoint.read_bytes()
    with open_state(checkpoint) as stream:
        result = save_export.export(rom, stream.read())
    assert len(result) == 32768
    assert checkpoint.read_bytes() == before


@pytest.mark.parametrize('origin', ['pokesim', 'core'])
def test_missing_core_capability_is_not_reported_as_busy(tmp_path, monkeypatch, origin):
    from pokesim.gen2 import save as gen2_save
    if origin == 'core':
        from pokesim_core.errors import CoreCapabilityError
    else:
        from pokesim.gen2.core import CoreCapabilityError
    message = 'Core does not provide cartridge clock import or export.'

    def unavailable(*_):
        raise CoreCapabilityError(message)
    monkeypatch.setattr(gen2_save, 'capture', lambda _: b'checkpoint')
    monkeypatch.setattr(gen2_save, 'export', unavailable)
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    shots = tmp_path / 'shots'
    shots.mkdir()
    emu = SimpleNamespace(rom=tmp_path / 'g.gbc', data=SimpleNamespace(game="gold"), generation=2, call=lambda function, **_: function())
    client = TestClient(create_app(emu, SimpleNamespace(shots=shots), adventure_name='Gold'))
    response = client.post('/api/export-save')
    assert response.status_code == 501
    assert message in response.json()['detail']
    assert 'busy' not in response.json()['detail']


def test_core_capability_error_is_a_runtime_error_but_not_busy():
    """Core 0.2 raises a RuntimeError subclass. It must not fall into the busy 503 branch."""
    from pokesim.capability import CAPABILITY_ERRORS
    from pokesim_core.errors import CoreCapabilityError as CoreError
    assert issubclass(CoreError, RuntimeError) and not issubclass(CoreError, NotImplementedError)
    assert CoreError in CAPABILITY_ERRORS and len(CAPABILITY_ERRORS) == 2
