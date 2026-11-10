"""The monitor checks workers side by side, and a start downloads data without the admission lock."""
from types import SimpleNamespace
import threading
import time

import pytest

from pokesim.app import supervisor as supervisor_module
from pokesim.app.backup import create_backup
from pokesim.app.manager import Manager
from pokesim.app.registry import Registry, identifier
from pokesim.app.supervisor import Supervisor
from test_managed_supervisor import FakeChild


class Gate:
    """A data download that waits until the test lets it finish."""
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def prepare(self, report, *args):
        self.calls += 1
        if self.calls == 1:
            report('Downloading game data')
            self.entered.set()
            assert self.release.wait(10)
        return None


@pytest.fixture
def gate():
    gate = Gate()
    yield gate
    gate.release.set()


@pytest.fixture
def supervisor(tmp_path, gate):
    registry = Registry(tmp_path)
    registry.add_rom('digest', 'sha1', 'red')
    rom = tmp_path / 'rom.gb'
    rom.write_bytes(b'fake')
    assets = SimpleNamespace(rom_path=lambda rid: rom, game_data_dir=tmp_path,
                             prepare=gate.prepare, install_portraits=lambda raw: 0,
                             cancelled=threading.Event())
    supervisor = Supervisor(registry, assets, 'http://127.0.0.1:8000', FakeChild)
    yield supervisor
    gate.release.set()
    supervisor.close()
    registry.close()


def adventure(registry):
    row = registry.create('Red', 'digest', {'starter': 'random'}, identifier())
    registry.request_lifecycle(row['id'], 'start', identifier())
    return row['id']


def started(supervisor, gate):
    """Start an adventure past its data download."""
    aid = adventure(supervisor.registry)
    gate.calls = max(gate.calls, 1)
    supervisor.start(aid)
    return aid, supervisor.child(aid)


def answering(child, location='Pallet Town'):
    """Make the fake worker answer like a live game whose frame count keeps going up."""
    frames = iter(range(100, 100000, 60))

    def request(method, path, data=None, timeout=None):
        if path == '/api/summary':
            frame = next(frames)
            return {'speed': 1, 'frame': frame, 'performance': {'frames': frame},
                    'game': {'map_name': child.location, 'playtime': frame // 60}}
        return {'ok': True}

    child.location = location
    child.request = request
    child.pace = SimpleNamespace(observe=lambda value: None)


def in_thread(target, *args):
    outcome = {}

    def run():
        try:
            outcome['result'] = target(*args)
        except BaseException as error:
            outcome['error'] = error
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def test_a_stuck_check_does_not_hold_up_another_workers_check(supervisor, gate, monkeypatch):
    monkeypatch.setattr(supervisor_module, 'CHECK_SECONDS', 0.3)
    (stuck_id, stuck), (live_id, live) = started(supervisor, gate), started(supervisor, gate)
    answering(live, 'Viridian City')
    hung, asked = threading.Event(), []

    def hangs(method, path, data=None, timeout=None):
        asked.append(path)
        assert hung.wait(10)
        return {}
    stuck.request = hangs
    try:
        began = time.perf_counter()
        supervisor.check_all(list(supervisor.children.items()))
        assert time.perf_counter() - began < 3
        assert supervisor.registry.adventure(live_id)['summary']['activity'] == 'Viridian City'
        assert not supervisor.checks[stuck_id].done()
        # The next pass leaves the stuck check alone and checks the live worker again.
        live.location = 'Route 2'
        supervisor.check_all(list(supervisor.children.items()))
        assert asked == ['/healthz']
        assert supervisor.registry.adventure(live_id)['summary']['activity'] == 'Route 2'
    finally:
        hung.set()
    supervisor.checks[stuck_id].result(timeout=5)


def test_the_summary_is_written_only_when_what_the_library_shows_changes(supervisor, gate, monkeypatch):
    aid, child = started(supervisor, gate)
    answering(child)
    writes = []
    update = supervisor.registry.update

    def counted(adventure_id, **values):
        if 'summary' in values:
            writes.append(values['summary'])
        return update(adventure_id, **values)
    monkeypatch.setattr(supervisor.registry, 'update', counted)
    for _ in range(3):
        supervisor.check(aid, child)
    assert len(writes) == 1 and writes[0]['activity'] == 'Pallet Town'
    assert 'frame' not in writes[0] and 'playtime' not in writes[0]
    child.location = 'Route 1'
    supervisor.check(aid, child)
    supervisor.check(aid, child)
    assert len(writes) == 2
    assert [row['message'] for row in writes[1]['recent_activity']] == ['Route 1', 'Pallet Town']
    # The monitor still saw every frame, it only kept them out of the registry.
    assert child.watch[1]['frame'] == 100 + 60 * 4


def test_a_starts_download_leaves_the_admission_lock_free(supervisor, gate):
    aid = adventure(supervisor.registry)
    thread, outcome = in_thread(supervisor.start, aid)
    try:
        assert gate.entered.wait(5)
        assert supervisor.admission.acquire(timeout=1), 'the download held the admission lock'
        supervisor.admission.release()
        assert supervisor._lock(aid).acquire(timeout=1), "the download held the adventure's lock"
        supervisor._lock(aid).release()
        assert supervisor.registry.adventure(aid)['summary']['setup'] == 'Downloading game data'
        # A second start while the first downloads joins it rather than starting a second worker.
        assert supervisor.start(aid)['state'] == 'starting'
    finally:
        gate.release.set()
        thread.join(5)
    assert 'error' not in outcome and outcome['result']['state'] == 'running'
    assert supervisor.children[aid].starts == 1


def test_a_stop_during_the_download_wins_and_the_worker_never_boots(supervisor, gate):
    aid = adventure(supervisor.registry)
    thread, outcome = in_thread(supervisor.start, aid)
    try:
        assert gate.entered.wait(5)
        child = supervisor.children[aid]
        assert supervisor.stop(aid)['state'] == 'stopped'
    finally:
        gate.release.set()
        thread.join(5)
    assert 'error' not in outcome and outcome['result']['state'] == 'stopped'
    assert child.starts == 0 and aid not in supervisor.children
    assert supervisor.registry.adventure(aid)['desired_state'] == 'stopped'


def test_a_backup_runs_while_a_start_downloads(tmp_path, gate, monkeypatch):
    class QuietChild(FakeChild):
        def request(self, method, path, body=None, **kwargs):
            return {}

    manager = Manager(tmp_path, child_factory=QuietChild)
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {'starter': 'random'}, identifier())
    manager.registry.request_lifecycle(row['id'], 'start', identifier())
    monkeypatch.setattr(manager.assets, 'rom_path', lambda rid: tmp_path / 'fixture.gb')
    monkeypatch.setattr(manager.assets, 'prepare', gate.prepare)
    monkeypatch.setattr(manager.assets, 'install_portraits', lambda raw: 0)
    (tmp_path / 'fixture.gb').write_bytes(b'fake')
    starting, started_outcome = in_thread(manager.start_adventure, row['id'])
    try:
        assert gate.entered.wait(5)
        first = manager.supervisor.children[row['id']]
        saving, saved = in_thread(create_backup, manager)
        saving.join(10)
        assert not saving.is_alive(), 'the backup waited behind the download'
        assert 'error' not in saved and saved['result']['id']
        # The backup stopped the downloading worker and started the adventure again itself.
        assert manager.supervisor.child(row['id']) is not first
    finally:
        gate.release.set()
        starting.join(5)
        try:
            assert 'error' not in started_outcome
            assert first.starts == 0
            assert manager.registry.adventure(row['id'])['state'] == 'running'
            assert manager.supervisor.child(row['id']).starts == 1
        finally:
            manager.close()
