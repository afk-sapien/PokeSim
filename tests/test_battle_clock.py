"""A ball thrown in a wild battle restarts the hung-battle clock in every generation, once per ball carried."""
from types import SimpleNamespace
from unittest.mock import Mock

from pokesim import config
from pokesim.events import RunMemory
from pokesim.runtime import battle_clock
from pokesim.runtime.battle_clock import ThrowClock
from pokesim.runtime.reload import FRAMES_PER_SECOND
from pokesim.strategy_data import ITEMS

LIMIT = config.BATTLE_TIMEOUT_SECONDS * FRAMES_PER_SECOND


def wild(balls, in_battle=1):
    return SimpleNamespace(valid=True, started=True, in_battle=in_battle, balls=balls)


def count(snapshot):
    return snapshot.balls


def test_a_throw_restarts_the_clock_once_for_each_ball_carried():
    clock = ThrowClock()
    assert clock.look(wild(3), 100, count) is None and clock.since(100) == 100
    assert clock.look(wild(2), 500, count) == 500 and clock.since(100) == 500
    # The same count, or a count misread higher, is no throw.
    assert clock.look(wild(2), 700, count) == 500
    assert clock.look(wild(3), 900, count) == 500
    assert clock.look(wild(2), 950, count) == 500
    assert clock.look(wild(1), 1000, count) == 1000
    assert clock.look(wild(0), 1200, count) == 1200
    # With the bag empty nothing restarts it again, and the timeout runs out as before.
    assert clock.look(wild(0), 5000, count) == 1200
    # A snapshot that does not read as a running game changes nothing.
    assert clock.look(SimpleNamespace(valid=False, in_battle=0), 5100, count) == 1200
    # A trainer battle or the overworld starts the count over, and the next battle's first look only sets it.
    assert clock.look(wild(5, in_battle=2), 6000, count) is None
    assert clock.look(wild(4), 6100, count) is None and clock.since(6100) == 6100
    assert clock.since(None) is None


def gen1_wild(balls):
    return SimpleNamespace(valid=True, started=True, in_battle=1,
                           items=[(ITEMS['POTION'], 9), (ITEMS['ULTRA_BALL'], balls), (ITEMS['MASTER_BALL'], 1)])


def test_gen1_a_throw_holds_the_battle_timeout_and_the_reload_still_goes_before_the_battle():
    from pokesim.emulator import Emulator
    start = 10 ** 6
    game = SimpleNamespace(frame=start, last_reload_frame=-10 ** 9, stuck_frame=start, invalid_frame=None,
                           battle_frame=start, throws=None, snapshot=None,
                           policy=SimpleNamespace(hopeless_battle=lambda snapshot: False),
                           _unstick=Mock(), _check_stall=Mock())
    battle_clock.note_throws(game, gen1_wild(5), battle_clock.gen1_balls)
    game.frame = start + LIMIT - 10
    battle_clock.note_throws(game, gen1_wild(4), battle_clock.gen1_balls)
    game.frame = game.stuck_frame = start + LIMIT + 1
    Emulator._check_guards(game)
    game._unstick.assert_not_called()
    game.frame = game.stuck_frame = start + 2 * LIMIT
    Emulator._check_guards(game)
    game._unstick.assert_called_once_with(start, 'battle never ended')


def gen2_wild(balls):
    return SimpleNamespace(valid=True, started=True, in_battle=1, enemy_species=249, enemy_level=40,
                           pockets={'balls': [(2, balls), (5, 0)]})


def test_gen2_a_throw_holds_the_battle_timeout_and_the_reload_still_goes_before_the_battle():
    from pokesim.gen2.emulator import Emulator
    start = 10 ** 6
    policy = SimpleNamespace(recoveries=0, take_failure=lambda: None, idle=lambda snapshot: False,
                             waiting=lambda snapshot: False, hopeless_battle=lambda snapshot: False)
    emu = SimpleNamespace(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                          frame=start, last_reload_frame=0, policy=policy, failure_streak=0, invalid_frame=None,
                          battle_frame=None, throws=None, stall=SimpleNamespace(frame=None), waiting=False,
                          _unstick=Mock(), _check_stall=lambda: None)

    def step(frame, balls):
        emu.frame = emu.stuck_frame = emu.progress_frame = emu.screen_frame = frame
        emu.snapshot = gen2_wild(balls)
        Emulator._time_battle(emu, emu.snapshot)
        Emulator._check_guards(emu)

    step(start, 20)
    step(start + LIMIT - 10, 19)
    step(start + LIMIT + 1, 19)
    emu._unstick.assert_not_called()
    step(start + 2 * LIMIT, 19)
    emu._unstick.assert_called_once_with(start, 'battle never ended')


def test_the_scenario_replays_restart_their_battle_clock_on_a_throw_too():
    from pokesim.scenarios import Gen1Watch, Gen2Watch
    gen1 = Gen1Watch(SimpleNamespace(memory=RunMemory(), policy=SimpleNamespace(collection={})))
    assert gen1.battle_clock(gen1_wild(5), None, 100) == 100
    assert gen1.battle_clock(gen1_wild(4), 100, 500) == 500
    assert gen1.battle_clock(gen1_wild(4), 500, 900) == 500
    gen2 = Gen2Watch(SimpleNamespace(data=None, history={}))
    assert gen2.battle_clock(gen2_wild(20), None, 100) == 100
    assert gen2.battle_clock(gen2_wild(19), 100, 500) == 500
    assert gen2.battle_clock(gen2_wild(19), 500, 900) == 500
    # A reload resets the watch, so the restored bag is not counted as balls picked back up.
    gen2.reset()
    assert gen2.battle_clock(gen2_wild(20), None, 1000) == 1000
