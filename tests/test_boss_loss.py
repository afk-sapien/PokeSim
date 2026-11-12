"""A loss to a boss is never progress, in both generations.

A live Gen II run lost at Lance for 12 hours. Each run earned experience, levels and trainer wins before
the blackout, so the stall alert never fired.
"""
import time
from types import SimpleNamespace

from pokesim.emulator import Emulator
from pokesim.gen2.emulator import Emulator as Gen2Emulator
from pokesim.runtime.supervision import Supervisor
from pokesim.stalls import LOOP_LIMIT, SCAN_FRAMES, LoopGuard, StallWatch
from pokesim.store import Store
from pokesim.strategy_data import MAPS
from test_events import snap
from test_loop_guard import Clock, add
from test_strategy import mon

TYPHLOSION = 157
LEAGUE = {'WILLS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'}


def blackout_emu(stall):
    policy = SimpleNamespace(in_league=lambda snapshot: snapshot.where in LEAGUE, constant=lambda snapshot: snapshot.where,
                             goal=None)
    return SimpleNamespace(stall=stall, loop_guard=None, store=None, policy=policy, data=SimpleNamespace(map_ids={}),
                           history={'maps': set(), 'league': 0}, play_clock=SimpleNamespace(frames=0),
                           supervisor=Supervisor())


def test_repeated_gen2_league_blackouts_trip_the_stall_while_experience_keeps_rising():
    stall = StallWatch(game_minutes=120, real_minutes=0)
    emu = blackout_emu(stall)
    experience, before, alerts = 100000, None, []

    def tick(where, fainted=False, gain=0):
        nonlocal experience, before
        experience += gain
        emu.play_clock.frames += 3600 * 5
        party = (SimpleNamespace(species=TYPHLOSION, trainer_id=1, dvs=(9,), experience=experience, egg=False),)
        snapshot = SimpleNamespace(valid=True, started=True, where=where, all_fainted=fainted, badges=255,
                                   event_flags=b'\x01', owned={1}, party=party)
        Gen2Emulator._watch_boss(emu, before, snapshot)
        Gen2Emulator._note_progress(emu, snapshot, 0.0)
        before = snapshot
        alerts.append(stall.check(emu.play_clock.frames, 1e9))

    tick('INDIGO_PLATEAU_POKECENTER_1F')
    for _ in range(12):
        tick('WILLS_ROOM', gain=5000)
        tick('LANCES_ROOM', gain=5000)
        tick('LANCES_ROOM', fainted=True)
        tick('INDIGO_PLATEAU_POKECENTER_1F')
    assert experience == 220000 and any(alerts)


def test_repeated_gen1_league_blackouts_trip_the_stall_while_experience_keeps_rising():
    stall = StallWatch(game_minutes=120, real_minutes=0)
    emu = SimpleNamespace(stall=stall, loop_guard=None, store=None, policy=SimpleNamespace(goal=None),
                          supervisor=Supervisor(), play_clock=SimpleNamespace(frames=0),
                          mem=SimpleNamespace(seen_maps=set(), championships=0))
    experience, before, alerts, frame = 100000, None, [], 0

    def tick(room, fainted=False, gain=0):
        nonlocal experience, before, frame
        experience += gain
        frame += 3600 * 5
        emu.play_clock.frames = frame
        party = (mon(level=56, hp=0 if fainted else 100, max_hp=100, experience=experience),)
        s = snap(map=MAPS[room], party=party, badges=255)
        # As Emulator._observe_snapshot does.
        Emulator._watch_boss(emu, before, s)
        Emulator._note_progress(emu, before, s)
        before = s
        alerts.append(stall.check(frame, time.time() + 60))

    tick('INDIGO_PLATEAU_LOBBY')
    for _ in range(12):
        tick('LORELEIS_ROOM', gain=5000)
        tick('LANCES_ROOM', gain=5000)
        tick('LANCES_ROOM', fainted=True)
        tick('INDIGO_PLATEAU_LOBBY')
    assert experience == 220000 and any(alerts)


def test_a_boss_won_keeps_its_progress():
    stall, supervisor = StallWatch(), Supervisor()
    stall.progress(10, 1.0)
    supervisor.watch_boss(True, False, stall)
    stall.progress(20, 2.0)
    supervisor.watch_boss(False, False, stall)
    assert stall.held is None and (stall.frame, stall.since) == (20, 2.0)
    supervisor.watch_boss(True, False, stall)
    stall.progress(30, 3.0)
    supervisor.watch_boss(False, True, stall)
    assert stall.held is None and (stall.frame, stall.since) == (20, 2.0)


def test_a_boss_lost_puts_the_ladder_back_where_the_attempt_began():
    stall, supervisor = StallWatch(), Supervisor()
    supervisor.reloads = 2
    supervisor.watch_boss(True, False, stall)
    supervisor.reset()
    supervisor.watch_boss(True, True, stall)
    assert supervisor.reloads == 2 and supervisor.held is None


def test_a_reload_out_of_a_boss_attempt_is_a_loss():
    stall, supervisor = StallWatch(), Supervisor()
    stall.progress(10, 1.0)
    supervisor.reloads = 1
    supervisor.watch_boss(True, False, stall)
    stall.progress(20, 2.0)
    supervisor.reset()
    supervisor.lost(stall)
    assert supervisor.reloads == 1 and stall.held is None and stall.frame == 10
    # Outside an attempt there is nothing to lose.
    supervisor.lost(stall)
    assert supervisor.reloads == 1 and stall.frame == 10


def test_a_loss_to_a_named_boss_writes_a_loss_row_and_counts_toward_the_loss_loop(tmp_path):
    store, clock = Store(tmp_path), Clock()
    # PlayClock frames are whole numbers.
    clock.now = 0
    store.clock = clock
    try:
        stall, supervisor = StallWatch(), Supervisor(store)
        for _ in range(5):
            supervisor.watch_boss('league', False, stall)
            clock.now += 3600
            supervisor.lost(stall)
        # A boss attempt with no key, as an older caller passes, writes no row.
        supervisor.watch_boss(True, False, stall)
        supervisor.lost(stall)
        rows = store.db.execute("SELECT identity, net FROM progress_events WHERE kind = 'loss'").fetchall()
        assert [tuple(row) for row in rows] == [('league', 0)] * 5
        assert supervisor.loss_loop.reason is None
        # The count outlives a restart, and the sixth loss within two game hours is a loop.
        supervisor = Supervisor(store)
        supervisor.watch_boss('league', False, stall)
        clock.now += 3600
        supervisor.lost(stall)
        assert supervisor.loss_loop.reason == 'Lost to league 6 times in 5 game minutes.'
    finally:
        store.close()


def test_trainer_wins_before_a_blackout_do_not_end_a_loop(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard, stall, supervisor = LoopGuard(clock=clock), StallWatch(), Supervisor(store)
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Totodile')
        supervisor.watch_boss(True, False, stall, guard)
        add(store, 'trainer', 'Defeated Elite Four Will')
        add(store, 'level', 'TYPHLOSION grew to level 57')
        supervisor.watch_boss(False, True, stall, guard)
        clock.now += SCAN_FRAMES
        assert 'received and released Totodile 6 times' in guard.looping(store)
        # A won battle outside any boss attempt is real progress again.
        add(store, 'badge', 'Earned the Rising Badge')
        clock.now += SCAN_FRAMES
        assert guard.looping(store) is None
    finally:
        store.close()
