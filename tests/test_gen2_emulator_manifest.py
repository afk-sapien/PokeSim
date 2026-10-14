"""Gen II autosave manifests describe the locked cartridge clock, and a failed start never leaks the emulator."""
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.gen2 import core
from pokesim.store import Store
from pokesim_core.emulator_state import checkpoint_metadata, retag_checkpoint
from pokesim_core.errors import CoreCapabilityError

LOCK = {'base': 1_700_000_000.0, 'offset': 0.0, 'frames': 12, 'follow_frames': True}


def manifest_emulator(pb):
    from pokesim.gen2.emulator import Emulator
    emu = Emulator.__new__(Emulator)
    emu.pb, emu.rom_sha1, emu.frame, emu.history = pb, 'rom', 7, {}
    emu.store = SimpleNamespace(get=lambda key, default=None: default)
    emu.policy = SimpleNamespace(state_dict=dict, menu=None, backing_out=False)
    emu.play_clock = emu.legendary_recovery = SimpleNamespace(state_dict=dict)
    return emu


def test_a_gen2_manifest_carries_the_clock_lock_and_no_legacy_tag(monkeypatch):
    """Gen II always saves with the clock locked to game time, which PyBoy 2.7.0 cannot reproduce."""
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'clock_elapsed', lambda pb: 42.0)
    pb = Mock()
    pb.clock_lock_state.return_value = LOCK
    manifest = manifest_emulator(pb)._manifest()
    assert 'pyboy_version' not in manifest
    assert manifest['emulator'] == checkpoint_metadata(rtc_clock=LOCK)['emulator']
    assert manifest['rtc_clock'] == LOCK and manifest['generation'] == 2


def test_a_traded_gen2_manifest_stays_untagged(monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'clock_elapsed', lambda pb: 42.0)
    pb = Mock()
    pb.clock_lock_state.return_value = LOCK
    assert 'pyboy_version' not in retag_checkpoint(manifest_emulator(pb)._manifest())


@pytest.fixture
def loader(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'read_snapshot', lambda *args: None)
    monkeypatch.setattr(module, 'open_state', lambda path: io.BytesIO(b'state'))
    emu = module.Emulator.__new__(module.Emulator)
    emu.store, emu.pb, emu.rom_sha1, emu.data = Store(tmp_path), Mock(), 'rom', None
    emu._sync_clock = Mock()
    emu.policy, emu.play_clock, emu.audio, emu._reset_watch, emu._publish_frame = Mock(), Mock(), Mock(), Mock(), Mock()
    emu.statistics = SimpleNamespace(previous=None)
    emu.history = {}
    yield emu
    emu.store.close()


@pytest.mark.parametrize('provenance', [
    pytest.param(lambda: checkpoint_metadata(), id='older-save-with-pyboy-tag'),
    pytest.param(lambda: checkpoint_metadata(rtc_clock=LOCK), id='new-save-without-tag'),
])
def test_gen2_autosaves_load_with_and_without_the_legacy_tag(loader, provenance):
    metadata = {**provenance(), 'generation': 2, 'rom_sha1': 'rom', 'frame': 99,
                'policy_state': {}, 'run_memory': {}}
    if 'pyboy_version' not in metadata:
        metadata['rtc_clock'] = LOCK
    path = loader.store.write_checkpoint(b'state', metadata)
    loader._load_state_file(path)
    assert loader.frame == 99
    loader.pb.load_state.assert_called_once()


@pytest.fixture
def starting(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr('pokesim.rewards.initialize', lambda *args: None)
    emu = module.Emulator.__new__(module.Emulator)
    emu.store, emu.pb, emu.snapshot = Store(tmp_path), Mock(), None
    emu.thread = Mock()
    emu._sync_clock = Mock()
    emu._clear_stale_hold = Mock()
    yield emu
    emu.store.close()


@pytest.mark.parametrize('error', [CoreCapabilityError('no clock'), RuntimeError('backend'), KeyError('field')])
def test_a_failed_restore_stops_the_emulator_and_reraises(starting, error):
    emu = starting
    emu.store.autosaves = lambda: [emu.store.states / 'auto-1.state']
    emu._load_state_file = Mock(side_effect=error)
    with pytest.raises(type(error)) as raised:
        emu.start()
    assert raised.value is error
    emu.pb.stop.assert_called_once_with(save=False)
    emu.thread.start.assert_not_called()


def test_a_failed_fresh_clock_sync_stops_the_emulator(starting):
    emu = starting
    emu.store.autosaves = lambda: []
    emu._sync_clock.side_effect = CoreCapabilityError('no clock')
    with pytest.raises(CoreCapabilityError):
        emu.start()
    emu.pb.stop.assert_called_once_with(save=False)


def test_no_restorable_autosave_still_stops_once_with_the_compatibility_error(starting):
    emu = starting
    emu.store.autosaves = lambda: [emu.store.states / 'auto-1.state']
    emu._load_state_file = Mock(side_effect=ValueError('refused'))
    with pytest.raises(ValueError, match='No compatible Gen II autosave'):
        emu.start()
    emu.pb.stop.assert_called_once_with(save=False)


def test_a_successful_start_keeps_the_emulator_running(starting):
    emu = starting
    emu.store.autosaves = lambda: []
    emu.start()
    emu.pb.stop.assert_not_called()
    emu.thread.start.assert_called_once()


@pytest.fixture(params=['gold', 'silver', 'crystal'])
def cartridge(request):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    return (Path(directory) / (request.param + '.gbc')).read_bytes()


def test_real_gen2_autosave_manifest_has_the_lock_and_no_legacy_tag(cartridge):
    pb = core.boot(io.BytesIO(cartridge), sound=False)
    try:
        core.follow_game_time(pb)
        emu = manifest_emulator(pb)
        emu._state_bytes()
        manifest = emu._manifest()
        assert manifest['emulator']['backend'] == 'pyboy-rs'
        assert manifest['rtc_clock'] is not None and manifest['rtc_clock']['follow_frames']
        assert 'pyboy_version' not in manifest
    finally:
        pb.stop(save=False)
