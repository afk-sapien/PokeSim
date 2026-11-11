"""A walk with no route ends its turn and records a failed attempt, with no reload and no stall event.

A Gen II walk with no route explored for 60 turns and then failed its menu-task count, and three of
those reloaded the save. The reload replayed the same missing route after a full stall timeout and fed
the stall watchdog. Both generations now record the attempt on the goal, with its map and target, and
the picker leaves that target until the wait runs out.
"""
import time
from types import SimpleNamespace

import pytest

from pokesim.planning.unreachable import DECISIONS, FRAMES, NoRoute
from pokesim.stalls import StallWatch

ROUTE_23, OLIVINE = 1, 99


def gen2_walk():
    """A Gold, Silver and Crystal policy whose walk to Olivine finds no route, and the attempts it records."""
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy.__new__(Policy)
    policy.data = SimpleNamespace(map_ids={'OLIVINE_CITY': OLIVINE})
    explored = []
    policy.nav = SimpleNamespace(regions=SimpleNamespace(route=lambda *args, **kwargs: None,
                                                         memberships=lambda *args, **kwargs: {1}),
                                 explore=lambda *args, **kwargs: explored.append(1) or ['up'])
    policy.goal = Goal('olivine', 'Travel to Olivine', 'OLIVINE_CITY', 5, 6)
    policy.collection, policy.decisions = {}, 100
    policy.stranded = policy.unreachable_waits = 0
    policy.failure, policy.recoveries = None, 0
    where = SimpleNamespace(map=ROUTE_23, map_name='Route 23', x=3, y=3, badges=0, party=[])
    action = policy.follow(where, None, None, False, False)
    assert action.button is None and not explored
    assert policy.no_route_waiting(policy.goal)
    policy.decisions += DECISIONS.wait(1)
    assert not policy.no_route_waiting(policy.goal)
    return policy, NoRoute(policy.collection, DECISIONS).attempts(), ('OLIVINE_CITY', [[5, 6]], 'Route 23')


def gen1_walk():
    """A Red, Blue and Yellow policy whose walk to the Pewter Gym finds no route, and the attempts it records."""
    from pokesim.policies.progression import Goal
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.strategy_data import MAPS
    from test_collection import state
    policy = StrategicPolicy(42)
    target = (MAPS['PEWTER_GYM'], 4, 2)
    policy.goal = Goal('buy_tm', 'Buy a move', 'Reach the shop', (target,))
    policy.nav.guided = lambda *args, **kwargs: None
    explored = []
    policy.nav.explore = lambda *args: explored.append(1) or 'up'
    recoveries = policy.recoveries
    where = state(map=MAPS['PALLET_TOWN'], x=5, y=5, frame=1000)
    policy._overworld(where, bytearray(65536))
    assert policy.mode == 'no route' and not explored and policy.recoveries == recoveries
    assert policy.no_route_waiting(policy.goal)
    # While it waits, the walk looks around instead of recording the same target again.
    policy._overworld(where, bytearray(65536))
    assert explored and len(NoRoute(policy.collection.director.progress, FRAMES).attempts()) == 1
    policy.clock += FRAMES.wait(1)
    assert not policy.no_route_waiting(policy.goal)
    return policy, NoRoute(policy.collection.director.progress, FRAMES).attempts(), (str(target[0]), [list(target)], MAPS['PALLET_TOWN'])


def gen2_guards(policy):
    """Run Gen II's stuck and stall watchdogs once over ``policy``. The reloads and stall events they ask for."""
    from pokesim.gen2.emulator import Emulator
    reloads, events = [], []
    frame = 10 ** 6
    watched = SimpleNamespace(recoveries=0, take_failure=policy.take_failure, idle=lambda snapshot: False,
                              waiting=lambda snapshot: False, recover=lambda level: None, details=lambda: {})
    emu = SimpleNamespace(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                          snapshot=SimpleNamespace(valid=True, started=True, map_name='Route 23'), frame=frame,
                          play_clock=SimpleNamespace(frames=frame), last_reload_frame=0, policy=watched, failure_streak=0, invalid_frame=None, battle_frame=None,
                          stuck_frame=frame, screen_frame=frame, progress_frame=frame,
                          stall=StallWatch(), waiting=False)
    emu._unstick = lambda since, why: reloads.append(why)
    emu._event = lambda event, snapshot: events.append(event)
    emu._check_stall = lambda: Emulator._check_stall(emu)
    Emulator._check_guards(emu)
    assert emu.failure_streak == 0
    return reloads, events


def gen1_guards(policy):
    """Run Gen I's stall watchdog once over ``policy``. The stall events it reports."""
    from pokesim.emulator import Emulator
    events = []
    emu = SimpleNamespace(snapshot=SimpleNamespace(valid=True, started=True), play_clock=SimpleNamespace(frames=1000),
                          stall=StallWatch(), policy=policy)
    emu._handle_events = lambda batch, snapshot: events.extend(batch)
    Emulator._check_stall(emu, time.time())
    return [], events


@pytest.mark.parametrize('walk, guards', [(gen2_walk, gen2_guards), (gen1_walk, gen1_guards)], ids=['gen2', 'gen1'])
def test_a_walk_with_no_route_records_the_attempt_without_a_reload_or_a_stall(walk, guards):
    policy, attempts, (place, targets, origin) = walk()
    assert [(row['map'], row['targets'], row['origin']) for row in attempts] == [(place, targets, origin)]
    reloads, events = guards(policy)
    assert reloads == [] and events == []


def test_a_gen1_step_tried_while_a_trainer_engages_is_not_a_failed_step():
    """Blue badges_2 stalled on Route 25. While a trainer walked up, every step tried failed and was blocked,
    so the walk to Bill found no route four times in a row and tripped the retry loop stall."""
    from dataclasses import replace

    from pokesim.policies.base import PolicyContext
    from pokesim.policies.strategic import StrategicPolicy
    from test_events import snap

    def tried(held):
        policy = StrategicPolicy(42)
        memory = bytearray(65536)
        # wFlags_D733 bit 3 is set while a trainer who spotted the player engages them.
        memory[0xD733] = 0x08 if held else 0
        where = snap(frame=1000)
        policy.observed_map = where.map
        here = (where.map, where.x, where.y)
        for frame in (1000, 1040):
            policy.nav.issued(here, 'left', frame)
            policy.step(PolicyContext(replace(where, frame=frame + 30), 0, memory))
        return policy.nav.failures.get((here, 'left')), (here, 'left') in policy.nav.blocked

    # Two steps that fail on their own block that side, and the same two tried while held do not.
    assert tried(False) == (2, True)
    assert tried(True) == (None, False)


def test_a_target_that_keeps_failing_waits_longer_each_time():
    record = NoRoute({}, DECISIONS)
    first = record.record('olivine', 'OLIVINE_CITY', [(5, 6)], 0)
    second = record.record('olivine', 'OLIVINE_CITY', [(5, 6)], first)
    assert second - first == 2 * (first - 0)
    # Another tile of the same goal is another target.
    assert not record.waiting('olivine', 'OLIVINE_CITY', [(7, 6)], first)
    assert len(record.attempts()) == 1
