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
                             prepare=lambda report: tmp_path, install_portraits=lambda raw: 0,
                             cancelled=threading.Event())
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


def test_unlimited_workers_and_latest_desired_state(supervisor):
    first, second, third = [adventure(supervisor) for _ in range(3)]
    supervisor.start(first)
    supervisor.start(second)
    supervisor.start(third)
    assert len(supervisor.children) == 3
    supervisor.stop(third)
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


def test_individual_pace_applies_only_to_its_worker_and_survives_restart(supervisor):
    first, second = adventure(supervisor), adventure(supervisor)
    supervisor.registry.update(first, settings={'speed': 8})
    supervisor.start(first)
    supervisor.start(second)
    assert supervisor.children[first].bootstrap['settings']['speed'] == 8
    received = {}
    for aid in (first, second):
        def request(method, path, data, timeout, aid=aid):
            assert path == '/internal/speed'
            received[aid] = data['speed']
            return data
        supervisor.children[aid].request = request
    supervisor.registry.update(first, settings={'speed': 0})
    assert supervisor.push_speed(first) is False
    assert received == {first: 0}
    assert supervisor.children[second].bootstrap['settings']['speed'] == 1
    supervisor.stop(first)
    supervisor.registry.request_lifecycle(first, 'start', identifier())
    supervisor.start(first)
    assert supervisor.children[first].bootstrap['settings']['speed'] == 0
    supervisor.stop(second)
    third = adventure(supervisor)
    supervisor.start(third)
    assert supervisor.children[third].bootstrap['settings']['speed'] == 1


def test_individual_pace_retries_unavailable_worker(supervisor):
    aid = adventure(supervisor)
    supervisor.start(aid)
    child = supervisor.children[aid]
    def fail(*args, **kwargs):
        raise RuntimeError('Worker reconnecting')
    child.request = fail
    supervisor.registry.update(aid, settings={'speed': 4})
    assert supervisor.push_speed(aid) is True
    calls = []
    def request(method, path, data, timeout):
        calls.append(data['speed'])
        return data
    child.request = request
    supervisor.sync_speed(aid, child, 1)
    assert calls == [4]
    supervisor.sync_speed(aid, child, 4)
    assert calls == [4]


def test_observed_pace_is_live_per_worker_and_resets_when_restarted(supervisor, monkeypatch):
    first, second = adventure(supervisor), adventure(supervisor)
    supervisor.start(first)
    supervisor.start(second)
    monkeypatch.setattr('pokesim.app.resources.time.monotonic', lambda: 20)
    child = supervisor.children[first]
    child.usage = SimpleNamespace(sample=lambda: {'cpu_percent': 50, 'memory_bytes': 100})
    child.pace.observe({'frames': 0, 'sampled_at': 10})
    child.pace.observe({'frames': 1380, 'sampled_at': 20})
    assert supervisor.resources(first)['observed_speed'] == 2.3
    assert supervisor.resources(second)['observed_speed'] is None
    assert 'resources' not in supervisor.registry.adventure(first)
    supervisor.stop(first)
    assert supervisor.resources(first) is None
    supervisor.registry.request_lifecycle(first, 'start', identifier())
    supervisor.start(first)
    assert supervisor.resources(first)['observed_speed'] is None


def test_no_configured_or_fixed_running_limit(supervisor):
    supervisor.registry.set_setting('max_running', 1)
    for _ in range(35):
        supervisor.start(adventure(supervisor))
    assert len(supervisor.children) == 35


def test_nickname_settings_reach_new_workers_and_retry_live_workers(supervisor):
    values = {'nickname_prefixes': ['CHAOS'], 'nickname_suffixes': []}
    supervisor.registry.set_setting('nickname_parts', values)
    aid = adventure(supervisor)
    supervisor.start(aid)
    child = supervisor.children[aid]
    assert child.bootstrap['settings']['nickname_prefixes'] == ['CHAOS']
    calls = []
    child.request = lambda *args, **kwargs: calls.append((args, kwargs))
    assert supervisor.update_nicknames() == []
    assert calls[0][0] == ('POST', '/internal/nicknames', values)
    supervisor.update_nicknames()
    assert len(calls) == 1
    supervisor.registry.set_setting('nickname_parts', {'nickname_prefixes': [], 'nickname_suffixes': []})
    child.request = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('reconnecting'))
    assert supervisor.update_nicknames() == [aid]
    child.request = lambda *args, **kwargs: calls.append((args, kwargs))
    supervisor.sync_nicknames(child)
    assert calls[-1][0][2]['nickname_prefixes'] == []


def test_palette_is_independent_retries_and_survives_worker_restart(supervisor):
    first, second = adventure(supervisor), adventure(supervisor)
    supervisor.start(first)
    supervisor.start(second)
    child = supervisor.children[first]
    supervisor.registry.update(first, settings={'palette': 'blue'})
    def fail(*args, **kwargs):
        raise RuntimeError('Worker reconnecting')
    child.request = fail
    assert supervisor.push_palette(first) is True
    calls = []
    def request(method, path, data, timeout):
        assert path == '/internal/palette'
        calls.append(data['palette'])
        return data
    child.request = request
    supervisor.sync_palette(first, child, 'original')
    supervisor.sync_palette(first, child, 'blue')
    assert calls == ['blue']
    supervisor.registry.update(first, settings={'palette': 'red'})
    assert supervisor.push_palette(first) is False
    assert calls == ['blue', 'red']
    assert supervisor.children[second].bootstrap['settings'].get('palette', 'original') == 'original'
    supervisor.stop(first)
    assert supervisor.push_palette(first) is False
    supervisor.registry.request_lifecycle(first, 'start', identifier())
    supervisor.start(first)
    assert supervisor.children[first].bootstrap['settings']['palette'] == 'red'
    supervisor.sync_palette(first, child, 'blue')
    assert calls == ['blue', 'red']


def test_readiness_timeout_names_the_last_cause_and_the_log_not_forty_lines(tmp_path):
    import sys
    from pokesim.app.supervisor import Child
    script = ("import sys,time\n"
              "[print('noise %d' % i, file=sys.stderr, flush=True) for i in range(60)]\n"
              "print('ROM header checksum is wrong', file=sys.stderr, flush=True)\n"
              "time.sleep(30)\n")
    bootstrap = {'token': 't', 'generation': 1, 'adventure_id': 'a', 'settings': {'data_dir': str(tmp_path)}}
    child = Child(bootstrap, command=[sys.executable, '-c', script])
    with pytest.raises(RuntimeError) as caught:
        child.start(timeout=1.5)
    message = str(caught.value)
    assert 'ROM header checksum is wrong' in message
    assert str(tmp_path / 'logs' / 'worker.log') in message
    assert 'noise 10' not in message and ' | ' not in message and len(message) < 400
