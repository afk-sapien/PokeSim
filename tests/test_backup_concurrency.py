import threading
from pathlib import Path

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
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: 0)
    (tmp_path / 'fixture.gb').write_bytes(b'fake')
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


def test_a_stopped_view_asked_for_during_a_backup_never_wedges_it(tmp_path, monkeypatch):
    """A page asks for the stopped view of an adventure a backup has just stopped.

    The backup holds the registry's lock until it has started the worker again, which takes the
    adventure's lock. A view that took the adventure's lock and then waited for the registry left the
    two waiting on each other, and every start, stop, backup and monitor pass waited behind them.
    """
    import pokesim.app.backup as backup
    from pokesim.app.supervisor import AdventureRunning
    copying = threading.Event()
    asking = threading.Event()
    outcomes = {}

    class QuietChild(FakeChild):
        def request(self, method, path, body=None, **kwargs):
            return {}

    manager = Manager(tmp_path, child_factory=QuietChild)
    manager.registry.add_rom('rom', 'sha1', 'red')
    aid = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())['id']
    manager.registry.request_lifecycle(aid, 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', lambda report: tmp_path)
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: 0)
    (tmp_path / 'fixture.gb').write_bytes(b'fake')
    original_copy = backup.shutil.copytree

    def copytree(source, destination, *args, **kwargs):
        if source.name == 'adventures':
            copying.set()
            # The copy goes on once the view has asked the registry for the adventure.
            assert asking.wait(5)
        return original_copy(source, destination, *args, **kwargs)

    read = manager.registry.adventure

    def adventure(key):
        if threading.current_thread().name == 'view-request':
            asking.set()
        return read(key)

    monkeypatch.setattr(backup.shutil, 'copytree', copytree)
    monkeypatch.setattr(manager.registry, 'adventure', adventure)

    def run(name, call):
        try:
            outcomes[name] = call()
        except BaseException as error:
            outcomes[name] = error

    saving = threading.Thread(target=run, args=('backup', lambda: create_backup(manager)), daemon=True)
    viewing = threading.Thread(target=run, args=('view', lambda: manager.supervisor.viewer(aid)),
                               name='view-request', daemon=True)
    try:
        manager.supervisor.start(aid)
        saving.start()
        assert copying.wait(5)
        # The backup has stopped the worker, so the page finds the adventure stopped and asks for its view.
        viewing.start()
        saving.join(5)
        viewing.join(5)
        assert not saving.is_alive() and not viewing.is_alive(), 'the backup and the view wait on each other'
        assert isinstance(outcomes['backup'], dict), outcomes['backup']
        # The worker is back before the view reads the registry, so the page asks again once it runs.
        assert isinstance(outcomes['view'], AdventureRunning), outcomes['view']
        assert manager.registry.adventure(aid)['state'] == 'running'
    finally:
        # A wedged pair keeps the registry's lock for good, and closing the registry would wait for it.
        if not saving.is_alive() and not viewing.is_alive():
            manager.close()


@pytest.mark.parametrize('auth,state,expected', [
    ('none', {'paused': True, 'manual_mode': False}, 'pause'),
    ('none', {'paused': True, 'manual_mode': True}, 'take_control'),
    ('none', {'paused': False, 'manual_mode': False}, None),
    ('accounts', {'paused': True, 'manual_mode': False}, 'pause'),
    # With accounts a backup ends playing by hand, so the autopilot plays again afterwards.
    ('accounts', {'paused': True, 'manual_mode': True}, None),
    ('accounts', {'paused': False, 'manual_mode': False}, None),
])
def test_backup_restores_previous_playback_mode(tmp_path, monkeypatch, auth, state, expected):
    controls = []

    class PlaybackChild(FakeChild):
        def request(self, method, path, body=None, **kwargs):
            if path == '/api/summary':
                return state
            if path == '/api/control':
                controls.append(body['action'])
            return {}

    manager = Manager(tmp_path, child_factory=PlaybackChild, auth=auth)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())
    manager.registry.request_lifecycle(row['id'], 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', lambda report: tmp_path)
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: 0)
    (tmp_path / 'fixture.gb').write_bytes(b'fake')
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


def test_a_backup_stays_suspended_until_its_workers_are_back(tmp_path, monkeypatch):
    """No lease or trade may land on a worker that is still starting after a backup."""
    seen = []

    class QuietChild(FakeChild):
        def request(self, method, path, body=None, **kwargs):
            return {}
    manager = Manager(tmp_path, child_factory=QuietChild)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())
    manager.registry.request_lifecycle(row['id'], 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', lambda report: tmp_path)
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: 0)
    (tmp_path / 'fixture.gb').write_bytes(b'fake')
    try:
        manager.supervisor.start(row['id'])
        start = manager.supervisor.start

        def watched(aid, *args, **kwargs):
            seen.append(manager.suspended)
            return start(aid, *args, **kwargs)
        monkeypatch.setattr(manager.supervisor, 'start', watched)
        create_backup(manager)
        assert seen == [True] and manager.suspended is False
    finally:
        manager.close()


def test_backup_and_import_stage_inside_the_library_not_tmp(tmp_path, monkeypatch):
    """The container mounts /tmp as a 256 MB tmpfs, so staging a library there fails in RAM.

    Every backup and import copies the whole library before it writes anything, which is
    far larger than 256 MB on any adventure that has been running for a while.
    """
    import tempfile

    from pokesim.app import backup as backup_module
    from pokesim.app import migration as migration_module

    manager = Manager(tmp_path, child_factory=FakeChild)
    staged = []
    original = tempfile.TemporaryDirectory

    def record(*args, **kwargs):
        staged.append(kwargs.get('dir'))
        return original(*args, **kwargs)

    monkeypatch.setattr(backup_module.tempfile, 'TemporaryDirectory', record)
    monkeypatch.setattr(migration_module.tempfile, 'TemporaryDirectory', record)
    create_backup(manager)
    assert staged, 'create_backup did not stage anything'
    for directory in staged:
        assert directory is not None, 'staging fell back to /tmp'
        assert tmp_path in Path(directory).resolve().parents or Path(directory).resolve() == tmp_path

    with pytest.raises(Exception):
        migration_module.import_archive(manager, tmp_path / 'missing.zip')
    assert all(entry is not None for entry in staged)
