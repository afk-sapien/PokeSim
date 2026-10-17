"""The library watchdog: each check starts, clears, and stays quiet when it should."""
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from pokesim.app import notifications
from pokesim.app import watchdog as watchdog_module
from pokesim.app.coordinator import SET_ASIDE
from pokesim.app.watchdog import (OWNER_FAILURES, ErrorLog, Limits, TracebackReader, Watchdog, duration,
                                  error_signature, normalise_failure)

AID, BID = 'a' * 32, 'b' * 32


class Clock:
    def __init__(self, now=10_000.0):
        self.now = now

    def __call__(self):
        return self.now


class Process:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class FakeRegistry:
    def __init__(self):
        self.rows = []
        self.trades = []
        self.settings = {}

    def adventures(self):
        return self.rows

    def setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def transactions(self, unresolved=False):
        return [row for row in self.trades if not unresolved or row['phase'] not in {'completed', 'aborted'}]


def game(aid=AID, name='Mischievous Badge Hunt', **changes):
    return {'id': aid, 'name': name, 'archived': False, 'state': 'running', 'desired_state': 'running',
            'summary': {}, **changes}


def status(stuck=0, map_name='Violet City', **changes):
    return {'stuck_seconds': stuck, 'paused': False, 'manual_mode': False, 'help_request': None,
            'game': {'map_name': map_name}, 'areas_discovered': 4,
            'watch': {'map': 1, 'owned': 5, 'badges': 1, 'hall_of_fame': 0},
            'progress': {'last_achievement': {'id': 7}}, 'league_rewards': {'wins': 0}, **changes}


@pytest.fixture
def world():
    clock = Clock()
    registry = FakeRegistry()
    sent = []
    manager = SimpleNamespace(
        registry=registry, closing=False, suspended=False,
        supervisor=SimpleNamespace(children={}, worker_output=None),
        coordinator=SimpleNamespace(reserved=lambda aid: False),
        notifications=SimpleNamespace(alert=lambda title, body, adventure_id=None: sent.append((title, body)) and None))
    watchdog = Watchdog(manager, clock=clock, limits=Limits(), environ={})
    clock.now += Limits().grace + 1   # past the startup grace unless a test says otherwise

    def child(aid=AID, seen=None, code=None):
        manager.supervisor.children[aid] = SimpleNamespace(process=Process(code), watch=(clock.now, seen or status()))

    def tick(advance=0):
        clock.now += advance
        for aid, item in manager.supervisor.children.items():
            if item.watch:
                item.watch = (clock.now, item.watch[1])
        return watchdog.tick()
    return SimpleNamespace(clock=clock, registry=registry, manager=manager, watchdog=watchdog, sent=sent,
                           child=child, tick=tick)


def test_a_stuck_adventure_is_announced_once_and_recovers(world):
    world.registry.rows = [game()]
    world.child(seen=status(stuck=60))
    world.tick()
    assert world.sent == []
    world.child(seen=status(stuck=18 * 60))
    world.tick(60)
    world.tick(60)
    assert world.sent == [('Needs attention', 'Mischievous Badge Hunt has been stuck in Violet City for 18 minutes.')]
    assert world.watchdog.public()['problems'][0]['kind'] == 'stuck'
    world.child(seen=status(stuck=5))
    world.tick(60)
    assert world.sent[-1] == ('Recovered', 'Mischievous Badge Hunt is moving again.')
    assert world.watchdog.public()['problems'] == []


def test_a_problem_that_returns_within_the_cooldown_stays_quiet(world):
    world.registry.rows = [game()]
    world.child(seen=status(stuck=1000))
    world.tick()
    world.child(seen=status(stuck=0))
    world.tick(60)
    world.child(seen=status(stuck=1000))
    world.tick(60)
    assert [title for title, _ in world.sent] == ['Needs attention', 'Recovered']
    # Once the cooldown has passed, the same problem is worth hearing about again.
    world.tick(Limits().cooldown)
    assert [title for title, _ in world.sent] == ['Needs attention', 'Recovered', 'Needs attention']


def test_a_crashed_adventure_is_announced_after_the_down_limit(world):
    world.registry.rows = [game(state='failed')]
    world.tick()
    world.tick(60)
    assert world.sent == []
    world.tick(61)
    assert world.sent == [('Needs attention', 'Mischievous Badge Hunt stopped unexpectedly and has not been running for 2 minutes.')]
    world.child()
    world.tick(60)
    assert world.sent[-1] == ('Recovered', 'Mischievous Badge Hunt is running again.')


def test_an_exited_child_counts_as_down(world):
    world.registry.rows = [game()]
    world.child(code=1)
    world.tick()
    world.tick(Limits().down)
    assert world.sent and 'stopped unexpectedly' in world.sent[0][1]


def test_an_adventure_the_owner_stopped_is_never_a_problem(world):
    world.registry.rows = [game(state='stopped', desired_state='stopped')]
    world.tick()
    world.tick(3600)
    assert world.sent == [] and world.watchdog.public()['problems'] == []
    # An adventure that crashed and was then stopped clears without a recovery note.
    world.registry.rows = [game(state='failed')]
    world.tick()
    world.tick(Limits().down)
    world.registry.rows = [game(state='stopped', desired_state='stopped')]
    world.tick(60)
    assert world.sent[-1][0] == 'Recovered'
    world.sent.clear()
    world.registry.rows = [game(state='failed', archived=True)]
    world.tick(Limits().down * 2)
    assert world.sent == []


def test_a_trade_reservation_is_not_downtime(world):
    world.manager.coordinator.reserved = lambda aid: True
    world.registry.rows = [game(state='stopped')]
    world.tick()
    world.tick(3600)
    assert world.sent == []


def test_a_restart_does_not_repeat_problems_it_inherits(world):
    world.watchdog.started = world.clock.now   # just started
    world.registry.rows = [game()]
    world.child(seen=status(stuck=2000))
    world.tick()
    world.tick(Limits().grace + 1)
    assert world.sent == []
    # The problem clears without a recovery note, since the owner never heard about it here.
    world.child(seen=status(stuck=0))
    world.tick(60)
    assert world.sent == []


def test_a_problem_that_starts_during_the_grace_is_announced_after_it(world):
    world.watchdog.started = world.clock.now
    world.registry.rows = [game(state='failed')]
    world.tick(10)
    world.tick(Limits().down)
    assert world.sent == []
    world.tick(Limits().grace)
    assert len(world.sent) == 1 and 'stopped unexpectedly' in world.sent[0][1]


def test_a_game_looping_in_place_is_no_progress(world):
    world.registry.rows = [game()]
    world.child(seen=status())
    world.tick()
    for _ in range(59):
        world.tick(60)
        # Moving between known spots does not count as progress.
        world.manager.supervisor.children[AID].watch[1]['stuck_seconds'] = 30
    assert world.sent == []
    world.tick(61)
    assert world.sent == [('Needs attention',
                           'Mischievous Badge Hunt has made no progress for 60 minutes. It is still playing in Violet City.')]
    seen = status()
    seen['watch']['owned'] = 6
    world.child(seen=seen)
    world.tick(60)
    assert world.sent[-1] == ('Recovered', 'Mischievous Badge Hunt is making progress again.')


def test_a_new_map_or_a_pause_restarts_the_progress_window(world):
    world.registry.rows = [game()]
    world.child(seen=status())
    world.tick()
    world.tick(3000)
    moved = status()
    moved['watch']['map'] = 2
    world.child(seen=moved)
    world.tick(60)
    world.tick(3000)
    assert world.sent == []
    world.child(seen=status(paused=True))
    world.tick(60)
    world.child(seen=status())
    world.tick(60)
    world.tick(3000)
    assert world.sent == []


def test_a_stuck_game_is_not_also_reported_as_no_progress(world):
    world.registry.rows = [game()]
    world.child(seen=status(stuck=0))
    world.tick()
    world.child(seen=status(stuck=4000))
    world.tick(4000)
    assert [problem['kind'] for problem in world.watchdog.public()['problems']] == ['stuck']


def test_a_help_request_shows_but_does_not_send(world):
    world.registry.rows = [game()]
    world.child(seen=status(help_request={'reason': 'The policy has stopped making game progress'}))
    world.tick()
    assert world.sent == []
    assert world.watchdog.public()['problems'][0]['message'] == (
        'Mischievous Badge Hunt asked for help. The policy has stopped making game progress.')


def trade(tid, phase, updated, error=None, participants=(AID, BID)):
    return {'id': tid, 'phase': phase, 'updated_at': updated, 'created_at': updated, 'error': error,
            'plan': {'participants': list(participants)}}


def test_a_trade_waiting_too_long_is_announced(world):
    world.registry.rows = [game(desired_state='stopped'), game(BID, 'Cozy Escape', desired_state='stopped')]
    now = world.clock.now
    world.registry.trades = [trade('t1', 'preparing', now - 300)]
    world.tick()
    assert world.sent == []
    world.tick(301)
    assert world.sent == [('Needs attention',
                           'The trade between Mischievous Badge Hunt and Cozy Escape has been preparing for 10 minutes.')]
    world.registry.trades = [trade('t1', 'committing', world.clock.now)]
    world.tick(60)
    assert world.sent[-1] == ('Recovered', 'The trade between Mischievous Badge Hunt and Cozy Escape moved on.')


def test_a_new_phase_restarts_the_trade_clock(world):
    now = world.clock.now
    world.registry.trades = [trade('t1', 'preparing', now - 500)]
    world.tick()
    world.registry.trades = [trade('t1', 'connecting', now - 500)]
    world.tick(200)
    world.tick(300)
    assert world.sent == []
    world.tick(301)
    assert 'has been connecting for 10 minutes' in world.sent[0][1]


def test_failure_reasons_are_compared_without_ids_and_numbers():
    first = normalise_failure(f'Cable Club preparation exceeded its travel deadline (adventure {AID}) after 312 s')
    second = normalise_failure(f'Cable Club preparation exceeded its  travel deadline (adventure {BID}) after 45.5 s.')
    assert first == second == 'cable club preparation exceeded its travel deadline after n s'
    assert normalise_failure('Worker for ' + 'c' * 32 + ' failed') == normalise_failure('Worker for ' + 'd' * 32 + ' failed')
    assert SET_ASIDE in OWNER_FAILURES


def test_repeated_trade_failures_are_announced(world):
    now = world.clock.now
    reason = 'Cable Club preparation exceeded its travel deadline (adventure {}) after {} s'
    world.registry.trades = [trade(f't{n}', 'aborted', now - 600 * n, reason.format(AID, 100 + n)) for n in range(2)]
    world.registry.trades += [trade('owner', 'aborted', now, 'Cancelled by the owner'),
                              trade('aside', 'aborted', now, SET_ASIDE),
                              trade('old', 'aborted', now - 8000, reason.format(AID, 1))]
    world.tick()
    assert world.sent == []
    world.registry.trades.append(trade('t9', 'aborted', now + 60, reason.format(BID, 999)))
    world.tick(60)
    assert world.sent == [('Needs attention', 'Trades failed the same way 3 times in the last 2 hours. '
                           'An adventure took too long to reach the Cable Club and prepare its Pokémon.')]
    world.tick(7200)
    assert world.sent[-1] == ('Recovered', 'Trades stopped failing the same way.')


def test_owner_cancellations_never_add_up(world):
    now = world.clock.now
    world.registry.trades = [trade(f'c{n}', 'aborted', now - n, 'Cancelled by the owner') for n in range(5)]
    world.tick()
    assert world.sent == []


PACKAGE = str(Path(watchdog_module.__file__).resolve().parents[1])
TRACEBACK = f'''Traceback (most recent call last):
  File "/usr/lib/python3.14/threading.py", line 1012, in run
    self._target(*self._args)
  File "{PACKAGE}/gen2/emulator.py", line 640, in _loop
    self.step()
  File "{PACKAGE}/gen2/policy.py", line 88, in step
    return table[key]
  File "/usr/lib/python3.14/collections/__init__.py", line 20, in __getitem__
    raise KeyError(key)
KeyError: 'route'
'''


def test_worker_tracebacks_are_grouped_by_type_and_place(world):
    world.registry.rows = [game(desired_state='stopped'), game(BID, 'Cozy Escape', desired_state='stopped')]
    for aid in (AID, BID, AID):
        for line in TRACEBACK.splitlines(keepends=True):
            world.watchdog.errors.worker_line(aid, line)
    world.watchdog.errors.worker_line(AID, '2026-10-17 INFO pokesim: Ordinary line\n')
    world.tick()
    assert world.sent == [('Needs attention', 'Cozy Escape and Mischievous Badge Hunt logged an unexpected error: '
                           'KeyError in pokesim/gen2/policy.py line 88 (step). It happened 3 times in the last 60 minutes.')]
    # The same error again inside the quiet period does not send a second alert.
    for line in TRACEBACK.splitlines(keepends=True):
        world.watchdog.errors.worker_line(AID, line)
    world.tick(600)
    assert len(world.sent) == 1
    # Errors age out silently. They have no recovery note.
    world.tick(Limits().error_quiet + 1)
    assert len(world.sent) == 1 and world.watchdog.public()['problems'] == []


def test_traceback_reader_ignores_chained_context_and_noise():
    found = []
    reader = TracebackReader(lambda kind, frames: found.append(error_signature(kind, frames)))
    chained = TRACEBACK + '\nDuring handling of the above exception, another exception occurred:\n\n' + TRACEBACK.replace(
        'KeyError: \'route\'', 'pokesim.trade.TradeError: no partner')
    for line in ('not a traceback\n', *chained.splitlines(keepends=True)):
        reader.feed(line)
    assert found == ['KeyError in pokesim/gen2/policy.py line 88 (step)',
                     'TradeError in pokesim/gen2/policy.py line 88 (step)']
    assert error_signature('ValueError', [('/usr/lib/x.py', 3, 'f')]) == 'ValueError in x.py line 3 (f)'


def test_manager_errors_come_from_logs_and_threads(world):
    world.watchdog.install()
    try:
        try:
            {}['missing']
        except KeyError:
            logging.getLogger('pokesim.app.manager').exception('Background application operation failed')
            logging.getLogger('pokesim.app.watchdog').exception('The watchdog check failed')

        def broken():
            raise RuntimeError('boom')
        thread = threading.Thread(target=broken)
        thread.start()
        thread.join()
    finally:
        world.watchdog.uninstall()
    signatures = [row[1] for row in world.watchdog.errors.since(0)]
    assert len(signatures) == 2
    assert signatures[0].startswith('KeyError in test_watchdog.py line ') and signatures[0].endswith('(test_manager_errors_come_from_logs_and_threads)')
    assert signatures[1].startswith('RuntimeError in') and '(broken)' in signatures[1]
    assert world.manager.supervisor.worker_output == world.watchdog.errors.worker_line
    world.tick()
    assert world.sent[0][1].startswith('PokeSim logged an unexpected error: KeyError')


def test_switching_off_clears_problems_and_stops_alerts(world):
    world.registry.rows = [game(state='failed')]
    world.tick()
    world.tick(Limits().down)
    assert world.watchdog.public()['problems']
    world.watchdog.set_enabled(False)
    assert world.watchdog.public() == {'enabled': False, 'problems': []}
    world.sent.clear()
    world.tick(3600)
    assert world.sent == []
    with pytest.raises(ValueError):
        world.watchdog.set_enabled('yes')


def test_nothing_runs_while_saving_or_shutting_down(world):
    world.registry.rows = [game(state='failed')]
    world.manager.suspended = True
    world.tick()
    world.tick(3600)
    assert world.sent == [] and world.watchdog.problems == {}


def test_limits_and_switch_read_the_environment():
    limits = Limits.from_environment({'POKESIM_WATCHDOG_STUCK': '20', 'POKESIM_WATCHDOG_FAILURE_REPEATS': '5',
                                      'POKESIM_WATCHDOG_INTERVAL': '0', 'POKESIM_WATCHDOG_DOWN': 'soon'})
    assert (limits.stuck, limits.failure_repeats, limits.interval, limits.down) == (1200, 5, 60, 120)
    manager = SimpleNamespace(registry=FakeRegistry())
    assert Watchdog(manager, environ={'POKESIM_WATCHDOG': 'off'}).enabled() is False
    assert Watchdog(manager, environ={}).enabled() is True
    manager.registry.settings['watchdog'] = {'enabled': True}
    assert Watchdog(manager, environ={'POKESIM_WATCHDOG': '0'}).enabled() is True
    assert [duration(s) for s in (30, 60, 18 * 60, 7200, 7260 + 60)] == [
        'less than a minute', '1 minute', '18 minutes', '2 hours', '2 hours and 2 minutes']


def test_error_log_is_thread_safe_and_bounded():
    log = ErrorLog(clock=lambda: 1, keep=3)
    for n in range(5):
        log.record(f's{n}')
    assert [row[1] for row in log.since(0)] == ['s2', 's3', 's4']


# The manager sends watchdog alerts through the real notification settings ---------------------------------

from test_notifications import client, adventure  # noqa: E402,F401


def test_the_manager_sends_watchdog_alerts_through_notifications(client, monkeypatch):
    client, manager = client
    red = adventure(manager, 'Mischievous Badge Hunt')
    assert client.patch('/api/v1/notifications', json={'enabled': True, 'topic': 'topic'}).status_code == 200
    sent = []
    monkeypatch.setattr(notifications, 'publish', lambda url, token, title, body, **extra: sent.append(
        (url, title, body, extra['click'], extra['priority'])))
    clock = Clock()
    manager.watchdog.clock = clock
    manager.watchdog.started = clock.now - Limits().grace - 1
    manager.registry.update(red, desired_state='running', state='failed')
    manager.watchdog.tick()
    clock.now += Limits().down
    manager.watchdog.tick()
    for thread in manager.watchdog.deliveries:
        thread.join(5)
    assert sent == [('https://ntfy.sh/topic', 'Needs attention',
                     'Mischievous Badge Hunt stopped unexpectedly and has not been running for 2 minutes.',
                     f'http://testserver/games/{red}', 4)]
    attention = client.get('/api/v1/adventures').json()['attention']
    assert attention['enabled'] is True and attention['problems'][0]['adventure_id'] == red
    # Turning off the Stuck category silences the watchdog too.
    sent.clear()
    client.patch('/api/v1/notifications', json={'categories': {'stall': False}})
    assert manager.notifications.alert('Needs attention', 'Test') is None
    # The switch has its own endpoint, and it survives a restart because it is saved.
    response = client.patch('/api/v1/watchdog', json={'enabled': False})
    assert response.status_code == 200 and response.json() == {'enabled': False, 'problems': []}
    assert client.get('/api/v1/watchdog').json()['enabled'] is False
    assert client.patch('/api/v1/watchdog', json={'enabled': 'no'}).status_code == 422
    assert client.patch('/api/v1/watchdog', json={'other': True}).status_code == 422
