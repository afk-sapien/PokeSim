"""A League run that fails with a trainee the team cannot carry stands the trainee down, and no run goes
back to the League until the team can carry it.

A Gold run took a level 100 Typhlosion and a level 22 trainee to the Elite Four for prize money. It lost,
restarted from the League entry save and went in again and again: the reload took back the loss with the
run's other records, and a run for prize money never asked the readiness oracle.
"""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection
from pokesim.gen2.collection import (call_off_league, funding_closed, funding_run, league_key, league_restarted,
                                     league_verdict, postgame_league, trainee_out)
from pokesim.gen2.standdown import standing_down
from pokesim.planning.readiness import DEPTH, Boss, Team, Train
from pokesim.runtime.supervision import Supervisor

TRAINEE = [47325, [5, 14, 15, 14, 9]]


def mon(level, trainer_id=47325, dvs=(5, 14, 15, 14, 9)):
    return SimpleNamespace(level=level, trainer_id=trainer_id, dvs=dvs, egg=False)


def gold(trainee=22, inside=False, boxed=False, **state):
    state.setdefault('training', {'identity': TRAINEE})
    policy = SimpleNamespace(collection=state, monitor_tables={}, clock=1000, completed={'champion': 1},
                             in_league=lambda snapshot: inside, person=lambda snapshot, key, *args: key)
    party, stored = [mon(100, dvs=(1, 2, 3, 4, 5)), mon(20, dvs=(14, 1, 15, 15, 6))], []
    (stored if boxed else party).append(mon(trainee))
    snapshot = SimpleNamespace(party=party, stored=stored, hall_of_fame_count=1, event=lambda name: False)
    return policy, snapshot


@pytest.fixture(autouse=True)
def oracle(monkeypatch):
    """The Gold save's League as planning/league.run reads it: 26 foes from level 40, and a team whose one
    fighter at level 40 or over has 55 attacks and depth 100."""
    def run(policy, snapshot):
        boss = Boss('league', ace=50, league=True, opponents=26, low=40, lost=policy.collection.get('league_lost'))
        return boss, Team(level=100, stamina=55, depth=100, size=6)
    monkeypatch.setattr(collection, 'league_run', run)


def test_a_league_run_restarted_from_its_entry_save_stands_the_trainee_down_and_is_called_off():
    policy, snapshot = gold(inside=True, funding=2)
    assert funding_run(policy, snapshot, None) == 'funds_will'
    assert policy.collection['league_entered']
    # The reload to the entry save rewinds the run's records and keeps the monitor's stand-downs.
    policy.collection = {'funding': 2, 'training': {'identity': TRAINEE}}
    assert league_restarted(policy, snapshot) and call_off_league(policy)
    assert standing_down(policy, league_key(TRAINEE))
    policy.in_league = lambda snapshot: False
    assert funding_run(policy, snapshot, None) is None
    assert 'funding' not in policy.collection and policy.collection['league_lost'] == 100
    # The oracle now asks for a deeper team, so no run for prize money or for its own sake starts.
    assert league_verdict(policy, snapshot) == Train(DEPTH, 110)
    assert funding_closed(policy, snapshot) and not postgame_league(policy, snapshot, None, None)


def test_the_stand_down_outlasts_a_reload_that_takes_the_loss_back():
    policy, snapshot = gold(funding=2)
    assert league_restarted(policy, snapshot)
    # An earlier save has no loss noted and a run for prize money started.
    assert league_verdict(policy, snapshot) is None
    assert funding_closed(policy, snapshot)
    assert funding_run(policy, snapshot, None) is None and 'funding' not in policy.collection
    assert not postgame_league(policy, snapshot, None, None)


def test_a_boxed_trainee_stands_down_too():
    # The Gold save's trainee waited in a box while a level 100 fighter and weak partners went in.
    policy, snapshot = gold(trainee=25, boxed=True, funding=2)
    assert league_restarted(policy, snapshot) and call_off_league(policy)
    assert standing_down(policy, league_key(TRAINEE)) and funding_closed(policy, snapshot)
    assert funding_run(policy, snapshot, None) is None and 'funding' not in policy.collection
    # Once it reaches the lineup's lowest level it can join the team, so only the oracle keeps the League shut.
    snapshot.stored[0].level = 40
    assert not trainee_out(policy, snapshot)


def test_a_trainee_at_the_lineups_lowest_level_goes_back_to_the_league():
    policy, snapshot = gold(trainee=40, funding=2)
    # It counts toward the oracle's team, so the stand-down is not needed.
    assert not league_restarted(policy, snapshot)
    assert not funding_closed(policy, snapshot)
    assert funding_run(policy, snapshot, None) == 'funds_will' and policy.collection['funding'] == 2


def test_a_run_with_no_trainee_restarts_until_the_supervisor_calls_it_off():
    policy, snapshot = gold(training=None, funding=2)
    assert not league_restarted(policy, snapshot)
    supervisor = Supervisor()
    called = [supervisor.call_off_league(1, lambda: call_off_league(policy)) for _ in range(3)]
    assert called == [False, False, True]
    assert Supervisor().call_off_league(1, lambda: call_off_league(policy), now=True)
