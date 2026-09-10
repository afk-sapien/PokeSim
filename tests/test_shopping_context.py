from dataclasses import replace

from pokesim.policies.base import PolicyContext
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import flags, mon, menu


def shopping_state():
    return snap(map=MAPS['LAVENDER_MART'], x=2, y=5, money=10000,
                party=(mon(level=40),), items=((ITEMS['GREAT_BALL'], 1),),
                event_flags=flags('EVENT_GOT_POKEDEX'))


def test_active_shop_list_takes_priority_over_pending_pc_upgrade():
    p = StrategicPolicy(7)
    p.goal = Goal('party_upgrade', 'Upgrade the party', 'Visit the PC')
    p.storage_species = 17
    p.storage_map = MAPS['LAVENDER_POKECENTER']
    p.shopping = True
    p.menu_context = 'shop'
    s = shopping_state()
    memory = menu({4: 'GREAT BALL', 6: 'SUPER POTION', 8: 'CANCEL'}, (5, 4), top=(5, 4))
    p._pc_target = lambda _: (_ for _ in ()).throw(AssertionError('Shop must not read a PC slot'))
    action = p._dispatch(s, Screen(memory), 'list', memory)[0]
    assert p.shop_item == ITEMS['GREAT_BALL']
    assert action.button == 'a'


def test_finished_shop_list_exits_even_when_pc_upgrade_is_pending():
    p = StrategicPolicy(7)
    p.goal = Goal('party_upgrade', 'Upgrade the party', 'Visit the PC')
    p.menu_context = 'shop'
    memory = menu({4: 'GREAT BALL', 6: 'CANCEL'}, (5, 4), top=(5, 4))
    assert p._dispatch(shopping_state(), Screen(memory), 'list', memory)[0].button == 'b'


def test_pc_upgrade_destination_stays_at_center_during_shop_detour():
    p = StrategicPolicy(7)
    p.storage_species = 17
    p.storage_map = MAPS['LAVENDER_POKECENTER']
    p.observed_map = MAPS['LAVENDER_MART']
    s = replace(shopping_state(), frame=100, textbox=True, boxed_pokemon=((17, 22),))
    memory = menu({1: '  BUY', 3: '  SELL', 5: '  QUIT'}, (1, 1), top=(1, 1))
    p.step(PolicyContext(s, 0, 0, memory))
    assert p.goal.targets == ((MAPS['LAVENDER_POKECENTER'], 13, 4),)
    assert p.menu_context == 'shop'


def test_storage_list_still_withdraws_target_inside_pc_context():
    p = StrategicPolicy(7)
    p.goal = Goal('party_upgrade', 'Upgrade the party', 'Visit the PC')
    p.menu_context = 'pc'
    p.pc_operation = 'withdraw'
    p.storage_species = 17
    s = replace(shopping_state(), boxed_pokemon=((165, 3), (17, 22)))
    memory = menu({4: 'RATTATA', 6: 'CUBONE', 8: 'CANCEL'}, (5, 4), top=(5, 4))
    assert p._dispatch(s, Screen(memory), 'list', memory)[0].button == 'down'
