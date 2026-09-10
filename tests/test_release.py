import json
import time
from importlib.metadata import version
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.store import Store
from pokesim.web.app import create_app
from test_events import snap


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path)
    yield instance
    instance.close()


@pytest.fixture
def api(store, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    emu = Mock()
    emu.health.return_value = {'ok': True}
    emu.status.return_value = {'version': 'test', 'viewer_only': False}
    with TestClient(create_app(emu, store)) as client:
        yield client, emu


@pytest.mark.parametrize('value', [None, 'bad', 'nan', 'inf', -1, 0.01, 17])
def test_invalid_speed_never_reaches_worker(api, value):
    client, emu = api
    assert client.post('/api/control', json={'action': 'speed', 'value': value}).status_code == 400
    emu.command.assert_not_called()


@pytest.mark.parametrize('value', [0, 0.5, 1, 16])
def test_valid_speed_reaches_worker(api, value):
    client, emu = api
    assert client.post('/api/control', json={'action': 'speed', 'value': value}).status_code == 200
    emu.command.assert_called_once_with('speed', value)


def test_viewer_mode_blocks_every_control(api, monkeypatch):
    client, emu = api
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    for action in ['press', 'pause', 'resume', 'take_control', 'save', 'restart', 'speed',
                   'load_state', 'adventure_pace', 'exploration']:
        assert client.post('/api/control', json={'action': action, 'value': 'a'}).status_code == 403
    assert client.get('/api/states').status_code == 403
    assert client.get('/').status_code == 200
    assert client.get('/feed.xml').status_code == 200
    emu.command.assert_not_called()
    emu.press.assert_not_called()


def test_health_reports_worker_failure(api):
    client, emu = api
    assert client.get('/healthz').status_code == 200
    emu.health.return_value = {'ok': False, 'error': 'stopped'}
    assert client.get('/healthz').status_code == 503


def test_invalid_button_save_path_and_limit(api):
    client, emu = api
    assert client.post('/api/control', json={'action': 'press', 'value': 'invalid'}).status_code == 400
    for path in ['../outside.state', 'missing.state', None]:
        assert client.post('/api/control', json={'action': 'load_state', 'value': path}).status_code == 400
    for endpoint in ['/api/events', '/feed.xml']:
        assert client.get(endpoint + '?limit=-1').status_code == 422
    emu.command.assert_not_called()


def metadata():
    return {'policy_state': {'goal': 'heal'}, 'run_memory': {}, 'rom_sha1': 'known-rom',
            'pyboy_version': version('pyboy'), 'policy': config.POLICY, 'frame': 900}


def test_checkpoint_pairs_state_and_memory_and_detects_corruption(store):
    checkpoint = store.write_checkpoint(b'game state', metadata())
    assert store.checkpoint_metadata(checkpoint)['policy_state'] == {'goal': 'heal'}
    checkpoint.write_bytes(b'partial')
    with pytest.raises(ValueError, match='checksum'):
        store.checkpoint_metadata(checkpoint)


def test_incomplete_new_checkpoint_is_not_treated_as_legacy(store):
    path = store.autosave_path()
    path.write_bytes(b'interrupted before manifest')
    with pytest.raises(FileNotFoundError):
        store.checkpoint_metadata(path)
    legacy = store.states / 'auto-123.state'
    legacy.write_bytes(b'old save')
    assert store.checkpoint_metadata(legacy) is None


def test_failed_atomic_write_leaves_previous_file_intact(store, monkeypatch):
    path = store.states / 'file.state'
    path.write_bytes(b'previous')
    def fail(source, destination):
        raise OSError('disk error')
    monkeypatch.setattr('pokesim.store.os.replace', fail)
    with pytest.raises(OSError):
        store.atomic_write(path, b'new')
    assert path.read_bytes() == b'previous'
    assert not list(store.states.glob('.pending-*'))


def test_checkpoint_rotation_removes_matching_manifests(store):
    paths = [store.write_checkpoint(str(i).encode(), metadata()) for i in range(3)]
    store.prune_autosaves(2)
    assert not paths[0].exists()
    assert not paths[0].with_suffix('.json').exists()
    assert store.autosaves() == paths[1:]


def restore_emulator(store):
    emu = Emulator.__new__(Emulator)
    emu.store = store
    emu.pb = Mock()
    emu.policy = Mock()
    emu.rom_sha1 = 'known-rom'
    emu.frame = 0
    emu.input_epoch = 0
    emu._boot = Mock(return_value=Mock())
    return emu


def test_restore_recovers_previous_pair_instead_of_latest_sqlite_memory(store, monkeypatch):
    older = store.write_checkpoint(b'valid', metadata())
    newer = store.write_checkpoint(b'broken', metadata())
    newer.write_bytes(b'truncated')
    store.set('policy_state', {'goal': 'unrelated future'})
    emu = restore_emulator(store)
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *args: snap(frame=900))
    emu._restore_first_valid([newer, older])
    emu.policy.load_state_dict.assert_called_once_with({'goal': 'heal'})
    assert emu.frame == 900
    assert newer.read_bytes() == b'truncated'


@pytest.mark.parametrize('field,value', [('rom_sha1', 'different'), ('pyboy_version', '0.0'), ('policy', 'other')])
def test_incompatible_checkpoint_is_rejected_before_loading(store, field, value):
    meta = dict(metadata(), **{field: value})
    path = store.write_checkpoint(b'valid', meta)
    emu = restore_emulator(store)
    with pytest.raises(ValueError, match='different'):
        emu._load_state_file(path)
    emu.pb.load_state.assert_not_called()


def test_all_broken_saves_fail_without_starting_a_new_game(store):
    path = store.autosave_path()
    path.write_bytes(b'partial')
    emu = restore_emulator(store)
    with pytest.raises(RuntimeError, match='Restore a backup'):
        emu._restore_first_valid([path])
    assert path.read_bytes() == b'partial'


def test_event_retention_removes_only_expired_event_attachments(store):
    from pokesim.events import Event
    event = Event('map', 'test', notable=True)
    old_id = store.add_event(event, snap(), b'image', b'state')
    recent_id = store.add_event(event, snap(), b'image', b'state')
    store.db.execute('UPDATE events SET ts = ? WHERE id = ?', (time.time() - 3 * 86400, old_id))
    store.db.commit()
    checkpoint = store.write_checkpoint(b'keep', metadata())
    assert store.prune_events(0) == 0
    assert store.prune_events(1) == 1
    assert store.event(old_id) is None
    assert not (store.shots / f'{old_id}.png').exists()
    assert not (store.states / f'event-{old_id}.state').exists()
    assert store.event(recent_id) is not None
    assert checkpoint.exists()


def test_paused_worker_is_healthy_but_stalled_worker_is_not():
    emu = Emulator.__new__(Emulator)
    emu.thread = Mock()
    emu.thread.is_alive.return_value = True
    emu.fatal_error = None
    emu.stopping = False
    emu.paused = True
    emu.last_activity = time.monotonic()
    assert emu.health()['ok']
    emu.last_activity -= 40
    assert not emu.health()['ok']
    emu.last_activity = time.monotonic()
    emu.thread.is_alive.return_value = False
    assert not emu.health()['ok']


@pytest.mark.parametrize('name,value', [('SPEED', float('nan')), ('STREAM_FPS', 0),
                                      ('KEEP_AUTOSAVES', 0), ('PORT', 70000), ('POLICY', 'missing')])
def test_invalid_configuration_is_actionable(monkeypatch, name, value):
    monkeypatch.setattr(config, name, value)
    with pytest.raises(ValueError, match=name):
        config.validate()


def test_repeated_worker_errors_stop_without_overwriting_good_saves(monkeypatch):
    import queue
    emu = Emulator.__new__(Emulator)
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.input_epoch = 0
    emu.paused = False
    emu.manual_mode = False
    emu.pb = Mock()
    emu.policy = Mock()
    emu.frame = 0
    emu._autosave = Mock()
    monkeypatch.setattr('pokesim.emulator.time.sleep', lambda _: None)
    def broken(*args):
        raise RuntimeError('worker error')
    monkeypatch.setattr('pokesim.emulator.read_snapshot', broken)
    emu._run()
    assert emu.fatal_error
    emu._autosave.assert_not_called()
    emu.pb.stop.assert_called_once_with(save=False)


def test_stop_interrupts_long_tick_without_advancing_game():
    emu = Emulator.__new__(Emulator)
    emu.stopping = True
    emu.pb = Mock()
    emu._tick(10000)
    emu.pb.tick.assert_not_called()
