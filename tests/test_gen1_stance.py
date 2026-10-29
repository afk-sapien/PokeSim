"""Red, Blue and Yellow meet wild battles through the shared battle stance (planner design S5)."""
from dataclasses import replace

import pytest

from pokesim.planning.ledger import HP, PP
from pokesim.planning.stance import FLEE_TRIES, HUNT, STORY, TRAIN, TRAVEL
from pokesim.policies.battle import Decision, choose_battle, needs_healing
from pokesim.policies.collection import Collection
from pokesim.policies.ledger import battle_room, walk_spent
from pokesim.policies.progression import Goal, teaching_goal, training_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS
from test_collection import sid, state
from test_strategy import mon

LEAD = mon(level=50, hp=150, max_hp=150, attack=120, special=120, speed=120)
# A Pidgey the run already owns, with a stronger one in the party, so nothing wants it.
PIDGEY = mon(species=sid(16), level=3, hp=12, max_hp=12, moves=(33,), pp=(35,))
OWNED = dict(owned=frozenset({1, 16}), party=(LEAD, replace(PIDGEY, level=60, hp=150, max_hp=150)))


def battle(kind, enemy=PIDGEY, flee_tries=0, **changes):
    s = state(**{'in_battle': 1, **OWNED, **changes})
    return choose_battle(s, s.party[0], enemy, 0, collect_missing=True, kind=kind, flee_tries=flee_tries)


@pytest.mark.parametrize('kind,runs', [(STORY, False), (TRAIN, False), (TRAVEL, True), (HUNT, True)])
def test_each_goal_kind_meets_a_plain_wild_battle_by_its_stance(kind, runs):
    decision = battle(kind)
    assert (decision.kind == 'run') is runs
    assert decision.stance is runs


@pytest.mark.parametrize('kind', [STORY, TRAIN, TRAVEL, HUNT])
def test_trainer_battles_are_fought_whatever_the_goal(kind):
    assert battle(kind, in_battle=2).kind != 'run'


@pytest.mark.parametrize('kind', [TRAVEL, HUNT])
def test_a_hunt_or_journey_still_catches_what_the_collection_wants(kind):
    # A species the Pokédex lacks is a collection target.
    assert battle(kind, owned=frozenset({1})).kind == 'item'
    # Without balls there is nothing to catch with, so the battle is run from.
    assert battle(kind, owned=frozenset({1}), items=()).kind == 'run'


def test_story_goal_runs_once_the_walk_budget_is_spent():
    worn = replace(LEAD, hp=60)
    party = (worn, replace(PIDGEY, level=60, hp=60, max_hp=150))
    assert walk_spent(party)
    assert battle(STORY, party=party).stance
    # A training goal fights on, since every battle is experience.
    assert battle(TRAIN, party=party).kind != 'run'


def test_two_failed_runs_fight_the_battle_out():
    assert battle(HUNT, flee_tries=FLEE_TRIES - 1).kind == 'run'
    assert battle(HUNT, flee_tries=FLEE_TRIES).kind == 'fight'


def test_a_shiny_without_balls_is_run_from_on_any_goal():
    for kind in (STORY, TRAIN):
        decision = battle(kind, items=(), enemy_shiny=True)
        assert decision.kind == 'run' and decision.stance


def test_the_battle_budget_is_the_former_heal_line():
    full = mon(hp=100, max_hp=100, moves=(33,), pp=(35,))
    assert battle_room(()) == {HP: 1, PP: 1}
    # 0.55 of 100 is a hair above 55 in floating point, so 55 HP was already under the old line.
    assert battle_room((full,)) == {HP: 45, PP: 30}
    assert not needs_healing((replace(full, hp=56),))
    assert needs_healing((replace(full, hp=55),))
    assert needs_healing((replace(full, status=8),))
    assert needs_healing((replace(full, pp=(1,)),))
    # 0.15 of Tackle's 35 uses is 5.25, so five uses already ask for a Pokémon Center.
    assert needs_healing((replace(full, pp=(5,)),))
    assert not needs_healing((replace(full, pp=(6,)),))


@pytest.mark.parametrize('project', [
    {'method': 'grass', 'species': sid(16), 'map': MAPS['ROUTE_1']},
    {'method': 'grass', 'species': sid(16), 'map': MAPS['ROUTE_1'], 'repeat': True},
    {'method': 'grass', 'species': sid(16), 'map': MAPS['ROUTE_1'], 'repeat': True, 'dv_hunt': True},
    {'method': 'fish', 'species': sid(129), 'map': MAPS['PALLET_TOWN']},
])
def test_every_pokedex_partner_and_quality_hunt_is_a_hunt(project):
    goal = Collection().project_goal(state(), project)
    assert goal.key == 'collect_hunt' and goal.kind == HUNT


def test_field_move_carrier_hunts_and_training_goals_carry_their_kind():
    s = state(party=(mon(species=sid(8), level=30),), badges=3, map=MAPS['ROUTE_6'])
    carrier = teaching_goal('teach_cut', 'Teach Cut', 'Open the route', s)
    assert carrier.key == 'catch_cut' and carrier.kind == HUNT
    assert training_goal('route', 'Train', 'Train', 'ROUTE_1').kind == TRAIN
    assert Goal('heal', 'Heal', 'Heal').kind == STORY


def test_a_carrier_hunt_keeps_its_carrier_wanted_while_the_catcher_is_hurt():
    # Oddish learns Cut. A hurt catcher still fights for it instead of running.
    hurt = replace(LEAD, hp=20)
    s = state(in_battle=1, owned=frozenset({1, 43}), party=(hurt,))
    oddish = mon(species=sid(43), level=40, hp=90, max_hp=90, attack=90, moves=(33,), pp=(35,))
    decision = choose_battle(s, hurt, oddish, 0, required_move=15, kind=HUNT)
    assert not decision.stance


def test_policy_counts_stance_runs_and_failures(monkeypatch):
    policy = StrategicPolicy(seed=1)
    s = state(in_battle=1, **OWNED)
    monkeypatch.setattr(policy, '_run', lambda snapshot: ['run'])
    policy.intent = Decision('run', reason='Run', stance=True)
    assert policy._battle_shortcut(s, LEAD, PIDGEY) == ['run']
    assert policy._battle_shortcut(s, LEAD, PIDGEY) == ['run']
    assert policy.flees['attempts'] == 1 and policy.fleeing
    # A run the stance did not choose is not counted.
    policy.fleeing = False
    policy.intent = Decision('run', reason='Leave the ghost')
    policy._battle_shortcut(s, LEAD, PIDGEY)
    assert policy.flees['attempts'] == 1 and not policy.fleeing


def test_ball_stock_keeps_the_hunt_catching():
    assert battle(HUNT, owned=frozenset({1}), items=((ITEMS['ULTRA_BALL'], 1),)).kind == 'item'
