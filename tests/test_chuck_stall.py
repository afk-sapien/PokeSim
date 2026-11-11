"""The Chuck stall (#464), scripted in Crystal: reloads out of a boss attempt climb the ladder and report.

A live Crystal run lost to Chuck at Cianwood Gym over and over. Each attempt earned experience before
the watchdog reloaded it. That experience started the ladder again, since the boss hold rolled back
only on a blackout, and each reload restarted the quiet clock. The run reloaded six times and never
said it was stuck.
"""
from types import SimpleNamespace

from pokesim.gen2.emulator import Emulator
from pokesim.gen2.policy import Goal
from pokesim.play_clock import PlayClock
from pokesim.runtime.supervision import STALL_RELOADS, Supervisor
from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE, LoopGuard, StallWatch
from pokesim.store import Store

CITY, GYM = 1, 2
TYPHLOSION = 157
START = 100000


def save():
    return SimpleNamespace(name='auto-1.state', stat=lambda: SimpleNamespace(st_mtime=0))


def crystal(tmp_path):
    """A Crystal run on its way to Chuck, whose reload goes back to Cianwood City."""
    store = Store(tmp_path / 'adventure')
    store.autosaves = lambda: [save()]
    store.checkpoint_metadata = lambda path: {'frame': 0}
    store.state_path = lambda key: None
    policy = SimpleNamespace(collection={}, decisions=100, menu=None, completed={}, pin=None, recoveries=0,
                             ladder_rung=None, goal=Goal('storm', 'Challenge Chuck', 'CIANWOOD_GYM', 4, 4),
                             in_league=lambda snapshot: False,
                             constant=lambda snapshot: '', on_restore=lambda: None)
    emu = SimpleNamespace(policy=policy, store=store, supervisor=Supervisor(store),
                          stall=StallWatch(game_minutes=120, real_minutes=0),
                          play_clock=PlayClock({'frames': 0, 'initialized': True}), frame=0, reloads=0,
                          adventure_seed=7, data=SimpleNamespace(map_ids={'CIANWOOD_GYM': GYM}),
                          history={'maps': {CITY, GYM}, 'league': 0}, snapshot=None, previous=None,
                          experience=START, reports=[], reloaded=0,
                          _behind_barrier=lambda metadata: False, _reset_watch=lambda: None, _tick=lambda frames: None)
    emu._event = lambda event, snapshot: emu.reports.append(event.title)
    emu.loop_guard = LoopGuard(lambda: emu.play_clock.frames, replaying=lambda: emu.supervisor.reloads > 0)

    def load(path):
        # The save is from before the attempt: back in the city with the experience it had then.
        emu.reloaded += 1
        emu.experience = START
        emu.snapshot = emu.previous = None
    emu._load_state_file = load
    return emu


def observe(emu, where, minutes=10):
    """One observation in ``where``, as Emulator._observe runs the boss watch and then the progress watch."""
    emu.play_clock.advance(minutes * MINUTE)
    emu.frame += minutes * MINUTE
    party = (SimpleNamespace(species=TYPHLOSION, trainer_id=1, dvs=(9, 9), experience=emu.experience, egg=False),)
    snapshot = SimpleNamespace(valid=True, started=True, map=where, map_name=str(where), all_fainted=False,
                               in_battle=2 if where == GYM else 0, hall_of_fame_count=0, badges=0x1F,
                               event_flags=b'\x07', owned={1, 2, 3}, party=party)
    Emulator._watch_boss(emu, emu.previous, snapshot)
    Emulator._note_progress(emu, snapshot, 0.0)
    emu.snapshot = emu.previous = snapshot


def test_reloads_out_of_chucks_gym_climb_the_ladder_and_the_third_reports(tmp_path):
    emu = crystal(tmp_path)
    try:
        observe(emu, CITY)
        quiet_since = emu.stall.frame
        quiet = []
        for attempt in range(1, 8):
            observe(emu, CITY)
            observe(emu, GYM)
            # Each attempt gets a little further than the last, a new high for Typhlosion every time.
            for _ in range(attempt + 2):
                emu.experience += 3000
                observe(emu, GYM)
            # The guard check scans for a loop before it reloads. Reloading one save again and again
            # is not a loop to it, so the seventh reload still reloads and the ladder alone counts them.
            emu.loop_guard.looping(emu.store)
            Emulator._unstick(emu, emu.frame, 'no progress')
            assert emu.reloaded == attempt and emu.supervisor.reloads == attempt
            assert emu.reports.count('Stuck? The adventure had to reload three times') == (attempt >= STALL_RELOADS)
            # A reload is not progress, so the quiet stretch runs on from before the first attempt.
            assert emu.stall.frame == quiet_since and emu.stall.held is None
            quiet.append(emu.stall.game_minutes(emu.play_clock.frames))
        assert quiet == sorted(quiet) and len(set(quiet)) == 7
        assert emu.loop_guard.reason is None
        assert emu.supervisor.stalled and emu.stall.stalled(emu.play_clock.frames)
        assert emu.stall.check(emu.play_clock.frames, 1e9)[0] == quiet[-1]
        # A worker restart keeps the count, so the eighth reload climbs from seven.
        assert Supervisor(emu.store).reloads == 7
    finally:
        emu.store.close()


def test_winning_against_chuck_is_progress(tmp_path):
    emu = crystal(tmp_path)
    try:
        observe(emu, CITY)
        emu.supervisor.reloads = 2
        observe(emu, GYM)
        emu.experience += 3000
        observe(emu, GYM)
        emu.experience += 3000
        observe(emu, CITY)
        assert emu.supervisor.reloads == 0 and emu.stall.frame == emu.play_clock.frames
    finally:
        emu.store.close()
