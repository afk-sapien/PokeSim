"""A worker that exits or goes unhealthy restarts after a wait that doubles, and ten healthy minutes reset it."""
import time
from types import SimpleNamespace

import pytest

from pokesim.app import supervisor as supervisor_module
from pokesim.app.supervisor import RESTART_FIRST_SECONDS, RESTART_MAX_SECONDS, RESTART_RESET_SECONDS, restart_delay

from test_managed_supervisor import adventure, supervisor  # noqa: F401


def answering(child, frames=None, **status):
    """Give the fake worker a summary whose frame count comes from `frames`, one value per call."""
    counts = iter(frames or [])

    def request(method, path, data=None, timeout=None):
        if path == '/api/summary':
            return {'speed': 1, 'game': {}, 'frame': 1, 'performance': {'frames': next(counts, None)}, **status}
        return {'ok': True}

    child.request = request
    child.pace = SimpleNamespace(observe=lambda value: None)


def exit_worker(supervisor, aid):  # noqa: F811
    child = supervisor.children[aid]
    child.process.poll = lambda: 1
    supervisor.check(aid, child)


def make_due(supervisor, aid):  # noqa: F811
    supervisor.restarts[aid][1] = time.monotonic() - 1


def test_the_wait_doubles_from_ten_seconds_up_to_thirty_minutes():
    assert [restart_delay(made) for made in range(4)] == [10, 20, 40, 80]
    assert restart_delay(7) == 1280
    assert restart_delay(8) == RESTART_MAX_SECONDS == 1800
    assert restart_delay(10_000) == RESTART_MAX_SECONDS


def test_a_worker_that_keeps_exiting_keeps_restarting_with_a_longer_wait(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    for made in range(1, 6):
        before = time.monotonic()
        exit_worker(supervisor, aid)
        row = supervisor.registry.adventure(aid)
        assert row['state'] == 'failed' and aid not in supervisor.children
        assert row['summary']['next_retry'] > time.time()
        count, due = supervisor.restarts[aid]
        assert count == made
        assert due - before == pytest.approx(restart_delay(made - 1), abs=1)
        # Nothing starts before the wait is over.
        supervisor.run_restarts()
        assert aid not in supervisor.children
        make_due(supervisor, aid)
        supervisor.run_restarts()
        assert supervisor.registry.adventure(aid)['state'] == 'running'
        assert supervisor.children[aid].starts == 1
    assert supervisor.restarts[aid][0] == 5


def test_ten_healthy_minutes_put_the_wait_back_to_ten_seconds(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    exit_worker(supervisor, aid)
    make_due(supervisor, aid)
    supervisor.run_restarts()
    child = supervisor.children[aid]
    answering(child, frames=[100, 200, 300])
    supervisor.check(aid, child)
    supervisor.check(aid, child)
    assert supervisor.restarts[aid][0] == 1, 'a short healthy run keeps the count'
    child.healthy_since = time.monotonic() - RESTART_RESET_SECONDS - 1
    supervisor.check(aid, child)
    assert aid not in supervisor.restarts
    exit_worker(supervisor, aid)
    assert supervisor.restarts[aid][0] == 1
    assert supervisor.restarts[aid][1] - time.monotonic() == pytest.approx(RESTART_FIRST_SECONDS, abs=1)


def test_a_restart_that_does_not_start_waits_longer_for_the_next(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    exit_worker(supervisor, aid)
    make_due(supervisor, aid)

    def broken(report):
        raise RuntimeError('the disk is full')

    supervisor.assets.prepare = broken
    supervisor.run_restarts()
    row = supervisor.registry.adventure(aid)
    assert row['state'] == 'failed' and row['error'] == 'the disk is full'
    assert supervisor.restarts[aid][0] == 2
    assert supervisor.restarts[aid][1] - time.monotonic() == pytest.approx(restart_delay(1), abs=1)


def test_an_owner_who_stops_the_adventure_cancels_its_restart(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    exit_worker(supervisor, aid)
    supervisor.stop(aid)
    make_due(supervisor, aid)
    supervisor.run_restarts()
    assert aid not in supervisor.children and aid not in supervisor.restarts
    assert supervisor.registry.adventure(aid)['state'] == 'stopped'


def test_a_worker_that_exits_during_an_unfinished_trade_is_left_for_its_recovery(supervisor, monkeypatch):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    monkeypatch.setattr(supervisor.registry, 'transactions',
                        lambda *args, **kwargs: [{'plan': {'participants': [aid]}}])
    exit_worker(supervisor, aid)
    assert supervisor.registry.adventure(aid)['state'] == 'failed'
    assert aid not in supervisor.restarts


def test_a_game_whose_frames_stop_moving_fails_and_then_restarts(supervisor, monkeypatch):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    child = supervisor.children[aid]
    answering(child, frames=[500, 500, 500])
    supervisor.check(aid, child)
    assert aid not in supervisor.unhealthy_since
    supervisor.check(aid, child)
    assert aid in supervisor.unhealthy_since
    assert supervisor.registry.adventure(aid)['state'] == 'running'
    monkeypatch.setattr(supervisor_module, 'STALE_SECONDS', 0)
    supervisor.check(aid, child)
    row = supervisor.registry.adventure(aid)
    assert row['state'] == 'failed' and row['error'] == 'Adventure game stopped moving for 0 seconds'
    assert child.stops == 1
    # The monitor's next look finds the stopped worker, keeps why it failed and schedules a restart.
    supervisor.check(aid, child)
    row = supervisor.registry.adventure(aid)
    assert row['error'] == 'Adventure game stopped moving for 0 seconds'
    assert aid not in supervisor.children and supervisor.restarts[aid][0] == 1


@pytest.mark.parametrize('status', [{'paused': True}, {'manual_mode': True}, 'trading'])
def test_frames_that_stand_still_while_paused_in_manual_play_or_trading_are_healthy(supervisor, monkeypatch,  # noqa: F811
                                                                                     status):
    aid = adventure(supervisor)
    supervisor.start(aid)
    child = supervisor.children[aid]
    if status == 'trading':
        monkeypatch.setattr(supervisor.registry, 'transactions', lambda *args, **kwargs: [{'plan': {}}])
        status = {}
    answering(child, frames=[500, 500, 500], **status)
    monkeypatch.setattr(supervisor_module, 'STALE_SECONDS', 0)
    for _ in range(3):
        supervisor.check(aid, child)
    assert aid not in supervisor.unhealthy_since
    assert supervisor.registry.adventure(aid)['state'] == 'running'
