from types import SimpleNamespace
import threading

import pytest

from pokesim.app.registry import Registry, identifier
from pokesim.app.supervisor import Supervisor


class FakeChild:
    def __init__(self, bootstrap):
        self.bootstrap = bootstrap
        self.generation = bootstrap['generation']
        self.url = None
        self.process = SimpleNamespace(poll=lambda: None)
        self.stops = 0
        self.starts = 0

    def start(self):
        self.starts += 1
        self.url = 'http://127.0.0.1:12345'

    def stop(self):
        self.stops += 1
        self.process.poll = lambda: 0


@pytest.fixture
def supervisor(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('digest', 'sha1', 'red')
    rom = tmp_path / 'rom.gb'
    rom.write_bytes(b'fake')
    assets = SimpleNamespace(rom_path=lambda rid: rom, game_data_dir=tmp_path,
                             prepare=lambda report: tmp_path, cancelled=threading.Event())
    supervisor = Supervisor(registry, assets, 'http://127.0.0.1:8000', FakeChild)
    yield supervisor
    supervisor.close()
    registry.close()


def adventure(supervisor):
    row = supervisor.registry.create('Red', 'digest', {'starter': 'random'}, identifier())
    supervisor.registry.request_lifecycle(row['id'], 'start', identifier())
    return row['id']


def test_multiple_red_games_have_separate_workers_and_one_start_each(supervisor):
    first, second = adventure(supervisor), adventure(supervisor)
    supervisor.start(first)
    supervisor.start(first)
    supervisor.start(second)
    assert len(supervisor.children) == 2
    assert supervisor.children[first].starts == 1
    assert supervisor.children[first].generation != supervisor.children[second].generation
    assert supervisor.children[first].bootstrap['settings']['data_dir'] != supervisor.children[second].bootstrap['settings']['data_dir']
    supervisor.stop(first)
    assert second in supervisor.children


def test_resource_limit_and_latest_desired_state(supervisor):
    first, second, third = [adventure(supervisor) for _ in range(3)]
    supervisor.start(first)
    supervisor.start(second)
    with pytest.raises(ValueError, match='limit'):
        supervisor.start(third)
    supervisor.registry.request_lifecycle(third, 'stop', identifier())
    assert supervisor.start(third)['desired_state'] == 'stopped'
    assert third not in supervisor.children


def test_old_duplicate_stop_cannot_override_later_start(supervisor):
    aid = adventure(supervisor)
    stop_id = identifier()
    assert supervisor.registry.request_lifecycle(aid, 'stop', stop_id)
    assert supervisor.registry.request_lifecycle(aid, 'start', identifier())
    assert not supervisor.registry.request_lifecycle(aid, 'stop', stop_id)
    assert supervisor.registry.adventure(aid)['desired_state'] == 'running'


def test_healthy_http_with_stalled_game_state_still_reaches_watchdog(supervisor, monkeypatch):
    aid = adventure(supervisor)
    supervisor.start(aid)
    child = supervisor.child(aid)
    stops = []

    def request(method, path, **kwargs):
        if path == '/api/state':
            raise RuntimeError('Emulator state is stalled')
        return {'ok': True}

    child.request = request
    child.stop = lambda timeout: stops.append(timeout)
    waits = iter([False, False, True])
    moments = iter([0, 0, 61, 61])
    original_closed = supervisor.closed
    supervisor.closed = SimpleNamespace(wait=lambda seconds: next(waits), is_set=lambda: False)
    try:
        with monkeypatch.context() as patch:
            patch.setattr('pokesim.app.supervisor.time.monotonic', lambda: next(moments))
            supervisor._monitor()
        assert stops == [5]
        assert supervisor.registry.adventure(aid)['state'] == 'failed'
    finally:
        supervisor.closed = original_closed
        child.stop = lambda: None
