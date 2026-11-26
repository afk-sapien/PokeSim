from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_screen import fake_mem
from test_strategy import flags, mon

# With every badge, Strength and Surf, and every Victory Road switch set, a walk from the Plateau reaches
# the marts to the south.
SWITCHES = flags('EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH', 'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1',
                 'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2', 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1')


def supply_goal(money, location='INDIGO_PLATEAU', sale=False, balls=1, at=(10, 15)):
    policy = StrategicPolicy(7)
    policy.completed['pokedex'] = True
    policy.goal = Goal('collect_train', 'Train a partner', 'Gain experience', ((MAPS['INDIGO_PLATEAU'], 10, 15),))
    policy.collection.pick = lambda *args: None
    policy.pickups.pick = lambda *args: None
    items = ((ITEMS['GREAT_BALL'], balls), (ITEMS['ANTIDOTE'], 1))
    if sale:
        items += ((ITEMS['NUGGET'], 1),)
        items += tuple((item, 1) for item in range(201, 216))
    state = snap(map=MAPS[location], x=at[0], y=at[1], money=money, badges=255,
                 party=(mon(level=50, moves=(70, 57, 15, 0)),), items=items, event_flags=SWITCHES)
    policy._overworld(state, fake_mem({}))
    return policy.goal


def test_optional_antidote_does_not_interrupt_training_with_a_distant_trip():
    assert supply_goal(455).key == 'collect_train'


def test_affordable_core_supplies_still_trigger_a_shopping_trip():
    assert supply_goal(10000).key == 'restock'


def test_optional_supplies_can_still_be_bought_in_the_current_mart():
    goal = supply_goal(455, 'VIRIDIAN_MART', at=(3, 6))
    assert goal.key == 'restock'
    assert all(target[0] == MAPS['VIRIDIAN_MART'] for target in goal.targets)


def test_a_full_bag_of_saleable_items_still_triggers_a_shop_visit():
    assert supply_goal(455, sale=True).key == 'restock'


def test_a_ball_reserve_of_ten_triggers_a_restock_when_affordable():
    assert supply_goal(10000, balls=9).key == 'restock'
    assert supply_goal(10000, balls=10).key == 'collect_train'
    assert supply_goal(455, balls=9).key == 'collect_train'
