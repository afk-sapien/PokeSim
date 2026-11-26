"""A restock plans only a shop the open story reaches, and judges each shop as its counter does."""
from dataclasses import replace
from functools import partial

from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController
from pokesim.strategy_data import DATA, ITEMS, MAPS, WORLD
from test_events import snap
from test_strategy import flags, mon

LOBBY = MAPS['INDIGO_PLATEAU_LOBBY']
SWITCHES = ('EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH', 'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1',
            'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2', 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1')
GOAL = Goal('train_league', 'Train for the League', 'Train')
OPTIONS = dict(requested_goal=GOAL.key, healing=False, in_league=False, has_pokedex=True)


def plateau(**changes):
    values = dict(map=MAPS['INDIGO_PLATEAU'], x=9, y=7, badges=255, party=(mon(level=60, moves=(70, 57, 15, 0)),),
                  event_flags=flags('EVENT_GOT_POKEDEX'))
    values.update(changes)
    return snap(**values)


def reach(s):
    nav = Navigator()
    nav.update_story(s)
    nav.live_map = s.map
    nav.live_positions = [tuple(obj[:2]) for obj in WORLD[s.map]['objects']]
    return partial(nav.open_target, s)


def counter(map_id):
    clerk = next(obj for obj in WORLD[map_id]['objects'] if obj[2] == 'SPRITE_CLERK')
    return map_id, 2, clerk[1]


def test_a_restock_plans_no_shop_beyond_the_shut_victory_road_gates():
    # A Blue run bought the League kit down to 894 and left the lobby with 7 Poké Balls. The restock
    # chose the southern marts, which only a boulder puzzle on each floor opens, and wandered the road
    # for 50 minutes.
    s = plateau(money=894, items=((ITEMS['POKE_BALL'], 7),))
    assert ShoppingController().plan(s, GOAL, None, **OPTIONS).goal.key == 'restock'
    shop = ShoppingController()
    assert shop.plan(s, GOAL, None, **OPTIONS, reach=reach(s)).goal is GOAL
    assert not shop.restocking
    opened = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', *SWITCHES))
    plan = ShoppingController().plan(opened, GOAL, None, **OPTIONS, reach=reach(opened)).goal
    assert plan.key == 'restock' and plan.targets == (counter(MAPS['VIRIDIAN_MART']),)


def test_the_plateau_judges_the_lobby_as_its_counter_does():
    # The League kit keeps half the spare money for a second run, so the counter sells no Full Restore
    # that an ordinary mart would. Judged as an ordinary mart, the lobby drew a trip that bought nothing.
    kit = ((ITEMS['ULTRA_BALL'], 15), (ITEMS['REVIVE'], 2), (ITEMS['FULL_HEAL'], 3))
    s = plateau(money=3300, items=kit)
    stock = DATA['marts']['IndigoPlateauLobby']
    inside = replace(s, map=LOBBY, x=7, y=11)
    assert ShoppingController.item_for(inside, stock, GOAL.key, None) is None
    assert ShoppingController.item_for(s, stock, GOAL.key, None) == ITEMS['FULL_RESTORE']
    assert ShoppingController.item_for(s, stock, GOAL.key, None, LOBBY) is None
    # A trip under way left the lobby with no medicine. The southern marts are past the shut gates.
    shop = ShoppingController(restocking=True)
    assert shop.plan(s, GOAL, None, **OPTIONS, reach=reach(s)).goal is GOAL
    assert not shop.restocking
