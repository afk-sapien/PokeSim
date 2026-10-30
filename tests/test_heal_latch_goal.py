"""A heal under way is the goal of every step, not only the overworld ones."""
from pokesim.policies.base import PolicyContext
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon


def step(policy, s):
    policy.observed_map = s.map
    policy.step(PolicyContext(s, 0, 0, bytearray(65536)))
    return policy.goal.key


def test_a_battle_on_the_way_to_the_nurse_keeps_the_heal_goal():
    policy = StrategicPolicy(7)
    policy.heal_latch = True
    s = snap(map=MAPS['ROUTE_15'], x=30, y=8, frame=1000, in_battle=1, party=(mon(hp=10, status=8),))
    assert step(policy, s) == 'heal'


def test_a_hurt_party_in_battle_does_not_latch_the_heal_before_the_overworld():
    policy = StrategicPolicy(7)
    s = snap(map=MAPS['ROUTE_15'], x=30, y=8, frame=1000, in_battle=1, party=(mon(hp=1),))
    assert step(policy, s) != 'heal'
    assert not policy.heal_latch


def test_the_league_keeps_its_own_goal_while_the_heal_is_latched():
    policy = StrategicPolicy(7)
    policy.heal_latch = True
    s = snap(map=MAPS['LORELEIS_ROOM'], x=5, y=5, frame=1000, in_battle=1, party=(mon(hp=10),))
    assert step(policy, s) != 'heal'
