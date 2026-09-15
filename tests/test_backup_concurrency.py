import threading

import pytest

from pokesim.app.backup import create_backup
from pokesim.app.manager import Manager
from pokesim.app.registry import identifier
from test_managed_supervisor import FakeChild


def test_queued_start_waits_until_backup_finishes_copying(tmp_path, monkeypatch):
    import pokesim.app.backup as backup
    copying = threading.Event()
    release_copy = threading.Event()
    starting = threading.Event()
    started = threading.Event()
    errors = []

    class ObservedChild(FakeChild):
        def start(self):
            super().start()
            started.set()

    manager = Manager(tmp_path, child_factory=ObservedChild)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())
    manager.registry.request_lifecycle(row['id'], 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', lambda report: tmp_path)
    original_copy = backup.shutil.copytree

    def copytree(source, destination, *args, **kwargs):
        if source.name == 'adventures':
            copying.set()
            assert release_copy.wait(5)
        return original_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, 'copytree', copytree)

    def run_backup():
        try:
            create_backup(manager)
        except BaseException as error:
            errors.append(error)

    def run_start():
        starting.set()
        try:
            manager.supervisor.start(row['id'])
        except BaseException as error:
            errors.append(error)

    saving = threading.Thread(target=run_backup)
    spawning = threading.Thread(target=run_start)
    try:
        saving.start()
        assert copying.wait(5)
        spawning.start()
        assert starting.wait(5)
        assert not started.wait(0.2)
        release_copy.set()
        saving.join(5)
        spawning.join(5)
        assert not saving.is_alive() and not spawning.is_alive()
        assert not errors
        assert started.is_set()
    finally:
        release_copy.set()
        saving.join(5)
        if spawning.ident is not None:
            spawning.join(5)
        manager.close()


@pytest.mark.parametrize('state,expected', [
    ({'paused': True, 'manual_mode': False}, 'pause'),
    ({'paused': True, 'manual_mode': True}, 'take_control'),
    ({'paused': False, 'manual_mode': False}, None),
])
def test_backup_restores_previous_playback_mode(tmp_path, monkeypatch, state, expected):
    controls = []

    class PlaybackChild(FakeChild):
        def request(self, method, path, body=None, **kwargs):
            if path == '/api/state':
                return state
            if path == '/api/control':
                controls.append(body['action'])
            return {}

    manager = Manager(tmp_path, child_factory=PlaybackChild)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())
    manager.registry.request_lifecycle(row['id'], 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', lambda report: tmp_path)
    try:
        manager.supervisor.start(row['id'])
        original = manager.supervisor.child(row['id'])
        result = create_backup(manager)
        assert result['id']
        assert original.stops == 1
        assert manager.supervisor.child(row['id']) is not original
        assert controls == ([expected] if expected else [])
        assert manager.registry.adventure(row['id'])['desired_state'] == 'running'
    finally:
        manager.close()
