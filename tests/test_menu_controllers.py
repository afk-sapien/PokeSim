"""Menu ownership survives goal changes and discards obsolete confirmation state."""
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController
from pokesim.policies.storage import StorageController
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from pokesim.strategy_data import ITEMS
from test_shopping_context import shopping_state
from test_strategy import menu


def test_shop_choices_do_not_mutate_the_callers_goal_or_project():
    shop = ShoppingController()
    project = {'method': 'train', 'parent': 153}
    memory = menu({1: '  BUY', 3: '  SELL', 5: '  QUIT'}, (1, 1), top=(1, 1))
    decision = shop.step(shopping_state(), Screen(memory), 'shop', 'party_upgrade', project)
    assert decision.actions[0].button == 'a' and shop.buying
    assert shop.item == ITEMS['GREAT_BALL']
    assert project == {'method': 'train', 'parent': 153}


def test_restore_discards_shop_and_pc_intents_but_preserves_durable_project():
    policy = StrategicPolicy(7)
    project = {'method': 'train', 'parent': 153, 'key': 'train:153:20'}
    policy.collection.project = project
    policy.shop.buying = policy.shop.restocking = True
    policy.pc.operation = 'withdraw'
    policy.pc.pending_release = (0, 0, {'nick': 'OLD'})
    policy.pending_trade_key = 'obsolete'
    policy.on_restore()
    assert policy.shop == ShoppingController() and policy.pc == StorageController()
    assert policy.pending_trade_key is None
    assert policy.collection.project is project


def test_restored_pc_cannot_accept_an_old_release_confirmation():
    policy = StrategicPolicy(7)
    policy.goal = Goal('party_release', 'Make room', 'Release a duplicate')
    policy.pc.pending_release = (0, 0, {'nick': 'OLD'})
    policy.on_restore()
    memory = menu({0: 'Once released, BULBASAUR', 1: 'is gone forever. OK?', 12: '  YES', 13: '  NO'},
                  (1, 12), top=(1, 12))
    assert policy._dispatch(shopping_state(), Screen(memory), 'yes_no', memory)[0].button == 'down'
