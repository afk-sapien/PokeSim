"""The one reload ladder both generations climb, and the counts it keeps across a reload and a worker restart."""
from pokesim.runtime import supervision
from pokesim.runtime.supervision import (CANNOT_END, GIVE_UP, HOLD, KEY, LEAGUE_RESTARTS, MAX_RELOADS, RELOAD,
                                         STALL_RELOADS, Supervisor)


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
