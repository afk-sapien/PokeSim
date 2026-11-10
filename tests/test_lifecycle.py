"""An adventure's state changes only through the lifecycle, which logs each move with its reason."""
import logging

import pytest

from pokesim.app import lifecycle

from test_managed_supervisor import adventure, supervisor  # noqa: F401


def registry_lines(caplog):
    return [(record.levelname, record.getMessage()) for record in caplog.records
            if record.name == 'pokesim.app.registry']


def test_every_listed_move_is_between_known_states():
    assert set(lifecycle.MOVES) == set(lifecycle.STATES)
    assert all(targets <= set(lifecycle.STATES) for targets in lifecycle.MOVES.values())
    assert lifecycle.LIVE <= set(lifecycle.STATES)


def test_each_state_change_logs_one_line_with_its_reason(supervisor, caplog):  # noqa: F811
    registry = supervisor.registry
    aid = adventure(supervisor)
    with caplog.at_level(logging.INFO, 'pokesim.app.registry'):
        registry.transition(aid, 'starting', 'test start', error=None)
        registry.transition(aid, 'starting', 'test start again')
        row = registry.transition(aid, 'running', 'test worker up')
    assert row['state'] == 'running'
    # Staying in the same state is not a change, so it logs nothing.
    assert registry_lines(caplog) == [('INFO', f'Adventure {aid} went from stopped to starting: test start'),
                                      ('INFO', f'Adventure {aid} went from starting to running: test worker up')]


def test_a_move_the_lifecycle_does_not_allow_is_logged_as_an_error_and_still_written(supervisor, caplog):  # noqa: F811
    registry = supervisor.registry
    aid = adventure(supervisor)
    with caplog.at_level(logging.INFO, 'pokesim.app.registry'):
        row = registry.transition(aid, 'running', 'test skip starting')
    assert row['state'] == 'running'
    assert registry_lines(caplog) == [
        ('ERROR', f'Adventure {aid} went from stopped to running, a move the lifecycle does not allow: '
                  'test skip starting')]


def test_a_state_changes_only_through_a_transition(supervisor):  # noqa: F811
    registry = supervisor.registry
    aid = adventure(supervisor)
    with pytest.raises(ValueError, match='transition'):
        registry.update(aid, state='running')
    with pytest.raises(ValueError, match='Unknown adventure state'):
        registry.transition(aid, 'paused', 'test')
    with pytest.raises(ValueError, match='Unsupported'):
        registry.transition(aid, 'starting', 'test', state='running')
    assert registry.adventure(aid)['state'] == 'stopped'


def test_the_monitor_fails_an_adventure_recorded_as_running_with_no_worker(supervisor):  # noqa: F811
    registry = supervisor.registry
    lost, starting = adventure(supervisor), adventure(supervisor)
    registry.transition(lost, 'starting', 'test setup')
    registry.transition(lost, 'running', 'test setup')
    # A Start the owner pressed reads as starting before the supervisor holds its worker.
    registry.transition(starting, 'starting', 'test setup')
    supervisor.monitor_once()
    assert registry.adventure(lost)['state'] == 'failed'
    assert registry.adventure(lost)['error'] == 'Adventure worker was not running'
    assert registry.adventure(starting)['state'] == 'starting'


def test_the_monitor_leaves_an_adventure_whose_worker_runs(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    supervisor.start(aid)
    assert supervisor.registry.adventure(aid)['state'] == 'running'
    supervisor.fail_missing_workers()
    assert supervisor.registry.adventure(aid)['state'] == 'running'
