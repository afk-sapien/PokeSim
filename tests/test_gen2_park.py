"""A stall sets the collection's goal aside in place of the first reload, and the goal comes back.

In Gold, Silver and Crystal a hunt or an activity that stopped moving, stopped making progress or
whose menu task kept failing stands down with that failure and the planner picks again, with no
reload. A second stall before new progress reloads, and so do a story goal, a battle, a glitch and
the League. Red, Blue and Yellow always set the project aside, and keep the failure the same way.
Each test runs the real guards into the real recovery.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.gen2 import standdown
from pokesim.gen2.emulator import Emulator
from pokesim.gen2.policy import Goal
from pokesim.planning import decide
from pokesim.planning.monitor import FAILURES, Backoff, Monitor
from pokesim.play_clock import PlayClock
from pokesim.runtime.supervision import PARK, RELOAD, Supervisor, Tables
from test_supervision import ladder, never

ZUBAT, GEODUDE = 41, 74
STUCK_FRAMES = config.STUCK_RELOAD_SECONDS * 60
HUNT = Goal('collection_hunt', 'Catch Zubat', 'Route 32', 5, 5, kind='hunt')
SAVE = Path('auto-v1-1.state')


def hunting(**extra):
    """A run hunting Zubat on Route 32 that has stopped moving, its last decision the hunt rung's pick."""
    loaded, events = [], []
    policy = SimpleNamespace(collection={'target': {'species': ZUBAT}}, goal=HUNT, menu=None, picked=('hunt', HUNT.key),
                             monitor_tables=Tables(), clock=500000, data=SimpleNamespace(map_ids={}), recoveries=0,
                             decisions=0, in_league=lambda snapshot: False, take_failure=lambda: None,
                             idle=lambda snapshot: False, waiting=lambda snapshot: False, recover=lambda level: None,
                             hopeless_battle=lambda snapshot: False, details=lambda: {})
    store = SimpleNamespace(get=lambda key: None, autosaves=lambda: [SAVE], state_path=lambda name: None,
                            checkpoint_metadata=lambda path: {'frame': 1, 'settled': True})
    values = dict(paused=False, manual_mode=False, preparation=None, store=store, policy=policy,
                  snapshot=SimpleNamespace(valid=True, started=True, map_name='Route 32', in_battle=0, hall_of_fame_count=0),
                  frame=100000, last_reload_frame=0, failure_streak=0, invalid_frame=None, battle_frame=None,
                  stuck_frame=100000 - STUCK_FRAMES - 1, screen_frame=100000, progress_frame=100000,
                  supervisor=Supervisor(), play_clock=PlayClock(), adventure_seed=7, reloads=0, last_reload=0,
                  _behind_barrier=lambda metadata: False, _load_state_file=loaded.append, _tick=lambda frames: None,
                  _event=lambda event, snapshot: events.append(event), _check_stall=lambda: None)
    values.update(extra)
    emu = SimpleNamespace(**values)
    emu._unstick = lambda since, why: Emulator._unstick(emu, since, why)
    emu._reset_watch = lambda: Emulator._reset_watch(emu)
    return emu, loaded, events


def failure(policy, key):
    return standdown.monitor(policy).failure(key, policy.clock)


def stop_again(emu, species=GEODUDE):
    """The next decision picks a hunt for ``species`` and the run stops moving again."""
    emu.policy.goal, emu.policy.picked = HUNT, ('hunt', HUNT.key)
    emu.policy.collection['target'] = {'species': species}
    emu.frame += STUCK_FRAMES + 1
    emu.stuck_frame = emu.frame - STUCK_FRAMES - 1


@pytest.mark.parametrize('extra, kind, body', [
    ({}, decide.STUCK, 'It stopped moving at Route 32'),
    ({'stuck_frame': 100000, 'progress_frame': 100000 - 3 * STUCK_FRAMES - 1}, decide.NO_PROGRESS,
     'It stopped making progress at Route 32'),
    ({'stuck_frame': 100000, 'failure_streak': 3}, decide.MENU_FAILED, 'A menu task for it kept failing at Route 32'),
])
def test_a_hunt_that_stalls_is_set_aside_with_no_reload(extra, kind, body):
    emu, loaded, events = hunting(**extra)
    Emulator._check_guards(emu)
    assert not loaded and emu.reloads == 0
    # The park takes the first rung, so the report and the give-up come after as many stalls as before.
    assert emu.supervisor.reloads == 1
    policy = emu.policy
    assert policy.goal is None and policy.collection['target'] is None
    assert failure(policy, standdown.hunt_key(ZUBAT)) == kind.kind
    assert [event.title for event in events] == ['Set aside: Catch Zubat']
    assert events[0].body.startswith(body)
    # The guards wait after a park as they do after a reload.
    assert emu.failure_streak == 0 and emu.last_reload_frame == emu.stuck_frame == emu.frame


def test_a_parked_hunt_comes_back_once_its_stand_down_on_the_play_clock_runs_out():
    emu, _, _ = hunting()
    Emulator._check_guards(emu)
    policy, key = emu.policy, standdown.hunt_key(ZUBAT)
    parked = policy.clock
    policy.clock = parked + standdown.STAND_DOWN - 1
    assert standdown.standing_down(policy, key)
    policy.clock = parked + standdown.STAND_DOWN
    assert not standdown.standing_down(policy, key)
    assert failure(policy, key) is None
    standdown.monitor(policy).expire(policy.clock)
    assert policy.monitor_tables[FAILURES] == {}


def test_a_second_stall_before_new_progress_reloads():
    emu, loaded, events = hunting()
    Emulator._check_guards(emu)
    stop_again(emu)
    Emulator._check_guards(emu)
    assert loaded == [SAVE] and emu.reloads == 1 and emu.supervisor.reloads == 2
    assert [event.title for event in events] == ['Set aside: Catch Zubat']
    # The reload stands the new hunt down as a reload always has.
    assert standdown.standing_down(emu.policy, standdown.hunt_key(GEODUDE))


def test_new_progress_lets_the_next_stall_park_again():
    emu, loaded, _ = hunting()
    Emulator._check_guards(emu)
    emu.supervisor.reset()
    stop_again(emu)
    Emulator._check_guards(emu)
    assert not loaded and emu.supervisor.reloads == 1
    assert failure(emu.policy, standdown.hunt_key(GEODUDE)) == decide.STUCK.kind


def story(emu):
    goal = Goal('story_whitney', 'Beat Whitney', 'Goldenrod Gym', 5, 5)
    emu.policy.goal, emu.policy.picked = goal, ('story', goal.key)


def stale(emu):
    emu.policy.picked = ('hunt', 'collection_box')


def unpicked(emu):
    emu.policy.picked = None


def battling(emu):
    emu.snapshot.in_battle = 1


def league(emu):
    emu.policy.in_league = lambda snapshot: True


def nothing_to_stand_down(emu):
    emu.policy.collection = {}


def glitched(emu):
    emu.invalid_frame = emu.frame - 601


@pytest.mark.parametrize('setup', [story, stale, unpicked, battling, league, nothing_to_stand_down, glitched])
def test_a_stall_the_collection_cannot_park_reloads_as_before(setup):
    emu, loaded, events = hunting()
    setup(emu)
    Emulator._check_guards(emu)
    assert loaded == [SAVE] and emu.reloads == 1 and emu.supervisor.reloads == 1
    assert not [event for event in events if event.title.startswith('Set aside')]


def test_a_park_takes_the_first_rung_of_the_ladder():
    parks = []

    def park():
        parks.append(True)
        return True

    supervisor = Supervisor()
    assert supervisor.climb('stuck', never, park=park).kind == PARK and supervisor.reloads == 1
    # Gold, Silver and Crystal reload on the next stall before new progress.
    assert supervisor.climb('stuck', never, park=park).kind == RELOAD and parks == [True]
    # Without reload_after_park every stall parks, and the parks still count toward the stall flag.
    supervisor = ladder(2)
    assert supervisor.climb('stuck', never, park=park, reload_after_park=False).kind == PARK
    assert supervisor.reloads == 3 and supervisor.stalled
    # A park that finds nothing to set aside falls through to the reload.
    assert Supervisor().climb('stuck', never, park=lambda: False).kind == RELOAD


def test_a_failure_is_kept_only_while_its_key_stands_down():
    tables = {}
    monitor = Monitor(tables, Backoff(100))
    monitor.stand_down('a', 0)
    # A run that never parks keeps the tables it had.
    assert FAILURES not in tables
    monitor.stand_down('a', 0, failure='stuck')
    assert monitor.failure('a', 99) == 'stuck' and monitor.failure('a', 100) is None
    # A later stand-down for no named failure forgets the earlier one.
    monitor.stand_down('a', 300)
    assert monitor.failure('a', 301) is None
    monitor.stand_down('b', 0, failure='menu_failed')
    monitor.stand_down('c', 0, failure='stuck')
    monitor.clear('c')
    assert tables[FAILURES] == {'b': 'menu_failed'}
    monitor.expire(10 ** 6)
    assert tables[FAILURES] == {}
    for key in 'xyz':
        monitor.stand_down(key, 0, failure='stuck')
    monitor.trim(2)
    assert list(tables[FAILURES]) == ['y', 'z']


def test_red_sets_a_stationary_project_aside_with_its_failure():
    from pokesim.policies.strategic import StrategicPolicy
    from test_collection import sid, state
    p = StrategicPolicy(7)
    p.collection.project = {'method': 'grass', 'species': sid(132), 'key': 'ditto'}
    p.collection.clock = 10000
    p.recover_stall(state(frame=300))
    assert p.collection.director.monitor.failure('ditto', p.collection.clock) == decide.STUCK.kind


def test_red_sets_a_stationary_project_aside_even_after_a_reload():
    from unittest.mock import Mock
    from pokesim.emulator import Emulator as RedEmulator
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.runtime.reload import FRAMES_PER_SECOND
    from test_events import snap
    emu = RedEmulator.__new__(RedEmulator)
    emu.policy = StrategicPolicy(7)
    emu.snapshot = snap(frame=1000)
    emu.supervisor = ladder(1)
    emu.frame = 10 ** 6
    emu.stuck_frame = emu.frame - (config.STUCK_RELOAD_SECONDS + 1) * FRAMES_PER_SECOND
    emu.play_clock = PlayClock()
    emu.input_epoch = 0
    emu._unstick = Mock()
    emu._check_guards()
    emu._unstick.assert_not_called()
    assert emu.policy.recoveries == 1
