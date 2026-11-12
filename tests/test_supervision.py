"""The one reload ladder both generations climb, and the counts it keeps across a reload and a worker restart."""
from types import SimpleNamespace

from pokesim.runtime import supervision
from pokesim.runtime.supervision import (BEST_KEY, CANNOT_END, GIVE_UP, HOLD, KEY, LEAGUE_RESTARTS, MAX_RELOADS,
                                         RELOAD, STALL_RELOADS, Supervisor)


class Kv:
    """The two store calls the supervisor makes."""

    def __init__(self, saved=None):
        self.saved = dict(saved or {})

    def get(self, key, default=None):
        return self.saved.get(key, default)

    def set(self, key, value):
        self.saved[key] = value


def ladder(reloads=0, exhausted=False, store=None):
    """A supervisor part way up the ladder, for the emulator tests."""
    supervisor = Supervisor(store)
    supervisor.reloads, supervisor.exhausted = reloads, exhausted
    return supervisor


def never():
    raise AssertionError('gave up before the last rung')


def test_each_reload_climbs_one_rung_and_the_third_reports_the_stall():
    supervisor = Supervisor()
    rungs = [supervisor.climb('no progress', never) for _ in range(STALL_RELOADS + 1)]
    assert [rung.kind for rung in rungs] == [RELOAD] * (STALL_RELOADS + 1)
    assert [rung.reloads for rung in rungs] == [1, 2, 3, 4]
    assert [rung.report for rung in rungs] == [False, False, True, False]
    assert not any(rung.league for rung in rungs)
    assert supervisor.stalled


def test_progress_starts_the_ladder_again():
    supervisor = ladder(STALL_RELOADS, exhausted=True)
    supervisor.reset()
    assert (supervisor.reloads, supervisor.exhausted, supervisor.stalled) == (0, False, False)
    assert supervisor.climb('no progress', never).reloads == 1


def test_inside_the_league_the_second_reload_restarts_the_attempt():
    supervisor = Supervisor()
    def inside():
        return True
    assert [supervisor.climb('no progress', never, in_league=inside).league for _ in range(3)] == [False, True, True]
    assert Supervisor().climb(CANNOT_END, never, in_league=inside).league
    assert not Supervisor().climb(CANNOT_END, never).league


def test_the_loop_and_the_league_are_asked_only_when_the_rung_needs_them():
    def ask():
        raise AssertionError('asked too soon')
    assert ladder(0).climb('no progress', never, in_league=ask).kind == RELOAD
    assert ladder(MAX_RELOADS).climb('no progress', lambda: True, looping=ask).kind == GIVE_UP


def test_after_the_last_reload_it_gives_up_on_the_goal():
    supervisor, gave_up = ladder(MAX_RELOADS), []
    rung = supervisor.climb('no progress', lambda: gave_up.append(1) or True)
    assert (rung.kind, rung.reloads, gave_up) == (GIVE_UP, MAX_RELOADS, [1])
    assert (supervisor.reloads, supervisor.stalled) == (0, False)


def test_with_nothing_to_give_up_it_holds_and_says_so_once():
    supervisor = ladder(MAX_RELOADS)
    rungs = [supervisor.climb('no progress', lambda: False) for _ in range(3)]
    assert [(rung.kind, rung.first) for rung in rungs] == [(HOLD, True), (HOLD, False), (HOLD, False)]
    assert supervisor.reloads == MAX_RELOADS and supervisor.stalled


def test_a_loop_holds_without_spending_a_reload():
    supervisor = ladder(1)
    rung = supervisor.climb('the same gift and release', never, looping=lambda: 'gift and release')
    assert (rung.kind, rung.first, supervisor.reloads, supervisor.stalled) == (HOLD, True, 1, True)


def test_the_third_league_restart_without_a_new_hall_of_fame_entry_calls_the_run_off():
    supervisor = Supervisor()
    assert [supervisor.restarted_league(0) for _ in range(LEAGUE_RESTARTS)] == [False] * (LEAGUE_RESTARTS - 1) + [True]
    assert not supervisor.restarted_league(0)
    # A new entry starts the count again.
    assert [supervisor.restarted_league(1) for _ in range(LEAGUE_RESTARTS)] == [False] * (LEAGUE_RESTARTS - 1) + [True]


def test_a_league_restart_the_ladder_would_report_calls_the_run_off_first():
    supervisor = ladder(STALL_RELOADS)
    assert supervisor.call_off_league(0, lambda: True)
    assert (supervisor.reloads, supervisor.stalled, supervisor.league) == (0, False, (0, 0))
    # A first League run has nothing to call off, so the ladder stays where it is and reports.
    supervisor = ladder(STALL_RELOADS)
    assert not supervisor.call_off_league(0, lambda: False)
    assert (supervisor.stalled, supervisor.league) == (True, (0, 1))
    # Below the report, only the third restart without a new Hall of Fame entry calls the run off.
    supervisor = Supervisor()
    called = [supervisor.call_off_league(0, lambda: True) for _ in range(LEAGUE_RESTARTS)]
    assert called == [False] * (LEAGUE_RESTARTS - 1) + [True]


def test_the_counts_survive_a_worker_restart():
    store = Kv()
    first = Supervisor(store)
    for _ in range(STALL_RELOADS):
        first.climb('no progress', never)
    first.restarted_league(0)
    again = Supervisor(store)
    assert (again.reloads, again.stalled, again.league) == (STALL_RELOADS, True, (0, 1))
    # The Chuck shape: reloads that each reset an in-memory count still reach the last rung.
    for _ in range(MAX_RELOADS - STALL_RELOADS):
        Supervisor(store).climb('no progress', never)
    assert Supervisor(store).climb('no progress', lambda: False).kind == HOLD


def test_a_reset_with_nothing_to_reset_writes_nothing():
    store = Kv()
    Supervisor(store).reset()
    assert store.saved == {}


def test_the_counts_live_in_the_adventure_store(tmp_path):
    from pokesim.store import Store
    store = Store(tmp_path / 'adventure')
    supervisor = Supervisor(store)
    supervisor.climb('no progress', never)
    assert store.get(KEY) == {'reloads': 1, 'exhausted': False, 'league': [0, 0]}
    assert Supervisor(store).reloads == 1


def test_the_report_names_the_trouble_and_the_place():
    title, body = supervision.report('no progress', 'Route 29')
    assert title == 'Stuck? The adventure had to reload three times'
    assert body == 'No progress at Route 29 and 2 reloads did not help.'


def pokemon(experience, species=157, trainer_id=1, dvs=(9, 9), egg=False, friendship=0):
    return SimpleNamespace(species=species, trainer_id=trainer_id, dvs=dvs, experience=experience, egg=egg,
                           friendship=friendship)


def seen(*party, badges=1, flags=b'\x01', owned=(1,)):
    return SimpleNamespace(badges=badges, event_flags=flags, owned=set(owned), party=party)


def test_only_a_new_high_is_progress_and_the_replay_after_a_reload_is_not():
    supervisor = ladder()
    assert supervisor.progressed(seen(pokemon(1000)), 3, 0)
    supervisor.climb('no progress', never)
    # The reload goes back to a save with less, and the replay earns the same experience again.
    assert not supervisor.progressed(seen(pokemon(800)), 3, 0)
    assert not supervisor.progressed(seen(pokemon(1000)), 3, 0)
    assert supervisor.reloads == 1
    assert supervisor.progressed(seen(pokemon(1000), badges=3), 3, 0)
    assert supervisor.reloads == 0
    # A new area or a League win counts, as each part of the score does.
    assert supervisor.progressed(seen(pokemon(1000), badges=3), 4, 0)
    assert supervisor.progressed(seen(pokemon(1000), badges=3), 4, 1)


def test_a_trainee_swapped_in_still_counts_against_its_own_best():
    supervisor = ladder()
    supervisor.progressed(seen(pokemon(90000), pokemon(500, species=16)), 3, 0)
    supervisor.reloads = 2
    # The party total drops with the trained Pokémon gone, yet the trainee beat its own best.
    assert supervisor.progressed(seen(pokemon(600, species=16)), 3, 0) and supervisor.reloads == 0


def test_an_egg_counts_once_per_cycle_and_once_on_hatching():
    supervisor = ladder()
    supervisor.progressed(seen(pokemon(0, egg=True, friendship=5)), 3, 0)
    assert supervisor.progressed(seen(pokemon(0, egg=True, friendship=4)), 3, 0)
    # A reload back to a fuller egg replays steps that already counted.
    assert not supervisor.progressed(seen(pokemon(0, egg=True, friendship=5)), 3, 0)
    assert supervisor.progressed(seen(pokemon(0)), 3, 0)
    assert not supervisor.progressed(seen(pokemon(0)), 3, 0)


def test_the_bests_survive_a_worker_restart_and_forget_old_pokemon():
    store = Kv()
    Supervisor(store).progressed(seen(pokemon(1000)), 3, 0)
    again = Supervisor(store)
    assert again.best == (1, 1, 1, 3, 1000, 0) and not again.progressed(seen(pokemon(1000)), 3, 0)
    for species in range(supervision.KEEP_MONS + 5):
        again.progressed(seen(pokemon(10, species=species)), 3, 0)
    kept = Supervisor(store).trained
    assert len(kept) == supervision.KEEP_MONS and supervision.mon_key(pokemon(10, species=supervision.KEEP_MONS + 4)) in kept


def test_a_restart_forgets_the_bests_in_either_generation(tmp_path):
    from pokesim.store import Store
    for generation in (1, 2):
        store = Store(tmp_path / str(generation))
        try:
            supervisor = Supervisor(store)
            supervisor.progressed(seen(pokemon(1000)), 3, 0)
            supervisor.climb('no progress', never)
            assert store.get(BEST_KEY)['score'] == [1, 1, 1, 3, 1000, 0]
            store.restart(generation, {})
            fresh = Supervisor(store)
            assert (fresh.best, fresh.trained, fresh.reloads) == ((), {}, 0)
        finally:
            store.close()


def test_a_boss_attempt_holds_the_ladder_and_a_loss_puts_it_back():
    supervisor = ladder(2)
    supervisor.watch_boss(True, False)
    assert supervisor.progressed(seen(pokemon(1000)), 3, 0) and supervisor.reloads == 0
    supervisor.watch_boss(True, True)
    assert supervisor.reloads == 2 and supervisor.held is None
    # A won attempt keeps its progress.
    supervisor.watch_boss(True, False)
    supervisor.progressed(seen(pokemon(2000)), 3, 0)
    supervisor.watch_boss(False, False)
    assert supervisor.reloads == 0 and supervisor.held is None
    supervisor.lost()
    assert supervisor.reloads == 0
