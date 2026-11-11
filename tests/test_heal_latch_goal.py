"""A heal under way is the goal of every step, not only the overworld ones."""
from pokesim.policies import strategic
from pokesim.runtime.policy import PolicyContext
from pokesim.policies.progression import object_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon


def step(policy, s):
    policy.observed_map = s.map
    policy.step(PolicyContext(s, 0, bytearray(65536)))
    return policy.goal.key


def test_a_battle_on_the_way_to_the_nurse_keeps_the_heal_goal():
    policy = StrategicPolicy(7)
    policy.heal.latched = True
    s = snap(map=MAPS['ROUTE_15'], x=30, y=8, frame=1000, in_battle=1, party=(mon(hp=10, status=8),))
    assert step(policy, s) == 'heal'


def test_a_hurt_party_in_battle_does_not_latch_the_heal_before_the_overworld():
    policy = StrategicPolicy(7)
    s = snap(map=MAPS['ROUTE_15'], x=30, y=8, frame=1000, in_battle=1, party=(mon(hp=1),))
    assert step(policy, s) != 'heal'
    assert not policy.heal.latched


def test_the_league_keeps_its_own_goal_while_the_heal_is_latched():
    policy = StrategicPolicy(7)
    policy.heal.latched = True
    s = snap(map=MAPS['LORELEIS_ROOM'], x=5, y=5, frame=1000, in_battle=1, party=(mon(hp=10),))
    assert step(policy, s) != 'heal'


def test_an_item_ball_a_step_away_comes_before_the_heal(monkeypatch):
    # Giovanni's battle ends one step from the Silph Scope and latches a heal. Healing first took the run
    # to Celadon and back down the hideout for the Scope.
    scope = object_goal('scope', 'Collect the Silph Scope', '', 'ROCKET_HIDEOUT_B4F', 'SILPH_SCOPE')
    monkeypatch.setattr(strategic, 'story_goal', lambda *args: scope)
    hurt = (mon(hp=1),)
    policy = StrategicPolicy(7)
    assert step(policy, snap(map=MAPS['ROCKET_HIDEOUT_B4F'], x=24, y=3, frame=1000, party=hurt)) == 'scope'
    assert policy.heal.latched
    # Nine steps away the heal still goes first.
    far = snap(map=MAPS['ROCKET_HIDEOUT_B4F'], x=24, y=10, frame=1000, party=hurt)
    assert step(StrategicPolicy(7), far) == 'heal'
