import logging
import threading
from types import SimpleNamespace

from pokesim.app.loops import Loop, Throttle, problems


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def raise_error(kind, message='broken'):
    try:
        raise kind(message)
    except kind as error:
        return error


def test_a_repeating_failure_is_logged_once_a_minute_with_its_traceback(caplog):
    clock = Clock()
    throttle = Throttle(logging.getLogger('test.loops'), clock)
    with caplog.at_level(logging.ERROR, 'test.loops'):
        assert throttle.failed('The check of adventure a', raise_error(KeyError))
        clock.now += 30
        assert not throttle.failed('The check of adventure a', raise_error(KeyError))
        assert not throttle.failed('The check of adventure a', raise_error(KeyError))
        # Another place or another kind of error is news, so it is logged at once.
        assert throttle.failed('The check of adventure b', raise_error(KeyError))
        assert throttle.failed('The check of adventure a', raise_error(ValueError))
        clock.now += 31
        assert throttle.failed('The check of adventure a', raise_error(KeyError))
    lines = [record.getMessage() for record in caplog.records]
    assert lines == ['The check of adventure a failed', 'The check of adventure b failed',
                     'The check of adventure a failed',
                     'The check of adventure a failed, and 2 more times since the last report']
    assert all(record.exc_info and record.exc_info[2] is not None for record in caplog.records)


def test_a_failing_body_is_logged_and_the_loop_keeps_running(caplog):
    stop = threading.Event()
    calls = []

    def body():
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError('first pass fails')
        stop.set()

    loop = Loop('test-loop', body, 0.01, stop.wait, logger=logging.getLogger('test.loops'))
    with caplog.at_level(logging.ERROR, 'test.loops'):
        loop.start().join(5)
    assert calls == [0, 1]
    assert [record.getMessage() for record in caplog.records] == ['test-loop failed']
    assert caplog.records[0].exc_info[0] is RuntimeError
    assert loop.finished and loop.problem() is None


def test_a_loop_thread_that_dies_is_named(caplog):
    def wait(seconds):
        raise SystemExit   # not an Exception, so it ends the thread

    loop = Loop('test-loop', lambda: None, 1, wait, logger=logging.getLogger('test.loops'))
    assert loop.problem() is None   # never started
    with caplog.at_level(logging.CRITICAL, 'test.loops'):
        loop.start().join(5)
    assert loop.problem() == 'test-loop stopped'
    assert [record.getMessage() for record in caplog.records] == ['The test-loop loop stopped']
    assert problems([None, loop]) == ['test-loop stopped']


def test_a_stale_heartbeat_is_named_and_a_fresh_one_is_not():
    clock = Clock()
    loop = Loop('test-loop', lambda: None, 3, lambda seconds: True, stale=180, clock=clock)
    loop.thread = SimpleNamespace(is_alive=lambda: True)
    loop.beat()
    clock.now += 180
    assert loop.problem() is None
    clock.now += 5
    assert loop.problem() == 'test-loop has made no progress for 185 seconds'
    loop.beat()
    assert loop.problem() is None


def test_a_guard_keeps_one_failing_step_from_stopping_the_next(caplog):
    loop = Loop('test-loop', lambda: None, 1, lambda seconds: True, logger=logging.getLogger('test.loops'))
    ran = []
    with caplog.at_level(logging.ERROR, 'test.loops'):
        for name in ('a', 'b'):
            with loop.guard(f'Step {name}'):
                if name == 'a':
                    raise KeyError(name)
                ran.append(name)
    assert ran == ['b']
    assert [record.getMessage() for record in caplog.records] == ['Step a failed']
