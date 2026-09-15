from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_screen import fake_mem
from test_strategy import mon


def supply_goal(money, location='INDIGO_PLATEAU', sale=False):
    policy = StrategicPolicy(7)
    policy.completed['pokedex'] = True
    policy.goal = Goal('collect_train', 'Train a partner', 'Gain experience', ((MAPS['INDIGO_PLATEAU'], 10, 15),))
    policy.collection.choose = lambda *args: None
    policy.pickups.choose = lambda *args: None
    items = ((ITEMS['GREAT_BALL'], 1), (ITEMS['ANTIDOTE'], 1))
    if sale:
        items += ((ITEMS['NUGGET'], 1),)
        items += tuple((item, 1) for item in range(201, 216))
    state = snap(map=MAPS[location], x=10, y=15, money=money,
                 party=(mon(level=50),), items=items)
    policy._overworld(state, fake_mem({}))
    return policy.goal


def test_optional_antidote_does_not_interrupt_training_with_a_distant_trip():
    assert supply_goal(455).key == 'collect_train'


def test_affordable_core_supplies_still_trigger_a_shopping_trip():
    assert supply_goal(10000).key == 'restock'


def test_optional_supplies_can_still_be_bought_in_the_current_mart():
    goal = supply_goal(455, 'VIRIDIAN_MART')
    assert goal.key == 'restock'
    assert all(target[0] == MAPS['VIRIDIAN_MART'] for target in goal.targets)


def test_a_full_bag_of_saleable_items_still_triggers_a_shop_visit():
    assert supply_goal(455, sale=True).key == 'restock'
