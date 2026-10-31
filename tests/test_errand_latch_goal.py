"""An errand under way stays the goal on the walking, warp and menu steps between overworld decisions.

In red-randomized the steps between decisions ran under the story pick, so the goal flipped between
restock and the story goal at every warp, and the mart purchases were credited to the story goal.
"""
from pokesim.policies.base import PolicyContext
from pokesim.policies.pickups import Pickups
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController
from pokesim.policies.strategic import W_WALK_COUNTER, StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import mon

RESTOCK = Goal('restock', 'Restock supplies', 'Buy useful balls and medicine with a cash reserve',
               ((MAPS['LAVENDER_MART'], 2, 5),), 'left', True)


def walk(policy, **changes):
    mem = bytearray(65536)
    mem[W_WALK_COUNTER] = 8
    s = snap(**{**dict(map=MAPS['ROUTE_8'], x=10, y=9, frame=1000, party=(mon(),)), **changes})
    policy.observed_map = s.map
    policy.step(PolicyContext(s, 0, 0, mem))
    return policy.goal


def test_a_walking_step_keeps_the_errand_under_way():
    policy = StrategicPolicy(7)
    policy.errand = RESTOCK
    assert walk(policy) is RESTOCK


def test_a_battle_runs_under_the_pick_not_the_errand():
    policy = StrategicPolicy(7)
    policy.errand = RESTOCK
    assert walk(policy, in_battle=1).key != 'restock'


def test_without_an_errand_the_walking_step_keeps_the_pick():
    policy = StrategicPolicy(7)
    assert walk(policy).key != 'restock'


def bag(count):
    names = ('POTION ANTIDOTE BURN_HEAL ICE_HEAL AWAKENING PARLYZ_HEAL FULL_HEAL REVIVE ESCAPE_ROPE REPEL '
             'FIRE_STONE THUNDER_STONE WATER_STONE LEAF_STONE RARE_CANDY CALCIUM NUGGET CARBOS HP_UP').split()
    return ((ITEMS['POKE_BALL'], 3),) + tuple((ITEMS[name], 1) for name in names[:count - 1])


def plan(s):
    lift = Goal('lift_rocket', 'Take the Lift Key', 'Beat the Rocket who holds the Lift Key')
    return ShoppingController().plan(s, lift, None, requested_goal=lift.key, healing=False, in_league=False,
                                     has_pokedex=True).goal.key


def test_a_dungeon_does_not_start_a_restock_for_a_crowded_bag_or_few_balls():
    # Red-randomized badges_4: a hideout pickup made 18 entries, and the restock walked to Lavender.
    hideout = snap(map=MAPS['ROCKET_HIDEOUT_B3F'], money=20000, items=bag(18))
    assert plan(hideout) == 'lift_rocket'
    assert not Pickups.has_space(hideout, ITEMS['MAX_ETHER'])
    assert plan(snap(map=MAPS['ROCKET_HIDEOUT_B3F'], money=20000, items=bag(20))) == 'restock'
    assert plan(snap(map=MAPS['CELADON_CITY'], money=20000, items=bag(18))) == 'restock'
