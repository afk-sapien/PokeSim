"""A restock plans only a shop a walk reaches, keeps it for the trip, and judges each shop as its counter
does."""
from dataclasses import replace
from functools import partial

from pokesim.planning import boss
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController, cash_reserve
from pokesim.strategy_data import DATA, ITEMS, MAPS, PRICES, WORLD
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


def test_a_walk_from_the_south_opens_the_victory_road_gates_on_the_way():
    # A Red run at Mt. Moon with every switch off could buy only at the lobby. The puzzle policies push
    # each boulder onto its switch on the way north, so with Strength the walk reaches the lobby.
    lobby = (counter(LOBBY),)
    s = plateau(map=MAPS['VICTORY_ROAD_1F'], x=9, y=16)
    assert reach(s)(lobby) == counter(LOBBY)
    weak = replace(s, party=(mon(level=60, moves=(57, 15, 0, 0)),))
    assert reach(weak)(lobby) is None


def test_a_restock_trip_keeps_the_shop_it_picked():
    s = plateau(money=894, items=((ITEMS['POKE_BALL'], 7),), event_flags=flags('EVENT_GOT_POKEDEX', *SWITCHES))
    shop = ShoppingController()
    picked = shop.plan(s, GOAL, None, **OPTIONS, reach=lambda targets: targets[-1]).goal.targets

    def unasked(targets):
        raise AssertionError('the trip asked for a shop again')
    assert len(picked) == 1 and shop.plan(s, GOAL, None, **OPTIONS, reach=unasked).goal.targets == picked


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


def test_the_lobby_stocks_the_league_kit_only_for_a_walk_into_the_league():
    # A Red run after the League stopped at the lobby PC to deposit, bought the kit there first and gave
    # it the bag's last free entry, and the Fishing Gurus then had no room for their rods.
    s = plateau(map=LOBBY, x=7, y=11, money=30000, items=((ITEMS['POKE_BALL'], 20), (ITEMS['HYPER_POTION'], 4)))
    for deposit in (Goal('party_collection_space', 'Make room', 'Deposit'), Goal('heal', 'Heal', 'Heal')):
        shop = ShoppingController()
        assert shop.plan(s, deposit, None, **{**OPTIONS, 'requested_goal': deposit.key}).goal is deposit
        assert not shop.restocking
    for key in ('league_lorelei', 'league_entrance'):
        trip = Goal(key, 'Challenge Lorelei', 'Start the League')
        plan = ShoppingController().plan(s, trip, None, **{**OPTIONS, 'requested_goal': key}).goal
        assert plan.key == 'restock' and plan.targets == (counter(LOBBY),)
    # A ball short of the reserve still restocks there, whatever the visit is for.
    short = replace(s, items=((ITEMS['POKE_BALL'], 3), (ITEMS['HYPER_POTION'], 4)))
    deposit = Goal('party_collection_space', 'Make room', 'Deposit')
    assert ShoppingController().plan(short, deposit, None, **{**OPTIONS, 'requested_goal': deposit.key}).goal.key == 'restock'


def counter_walk(s):
    """What the lobby counter sells one at a time, and the money it leaves."""
    stock, bought = DATA['marts']['IndigoPlateauLobby'], []
    while (item := ShoppingController.item_for(s, stock, 'restock', None)) is not None:
        bought.append(next(name for name, value in ITEMS.items() if value == item))
        counts = dict(s.items)
        counts[item] = counts.get(item, 0) + 1
        s = replace(s, items=tuple(counts.items()), money=s.money - PRICES[item])
    return bought, s.money


def test_the_lobby_counter_sells_the_league_kit_before_any_ball():
    # With 9,587 the counter sold one Max Potion, one Revive and four Ultra Balls, and no Full Heal.
    s = plateau(map=LOBBY, x=7, y=11, money=9587, items=((ITEMS['POKE_BALL'], 3),))
    bought, left = counter_walk(s)
    assert bought == ['MAX_POTION', 'REVIVE', 'FULL_HEAL', 'FULL_HEAL', 'FULL_HEAL'] and left == 3787
    # A ball spends only what the whole kit and the share it keeps for a second run leave over.
    rich = replace(s, money=40000)
    bought, left = counter_walk(rich)
    assert bought[:10] == ['MAX_POTION'] * 5 + ['REVIVE'] * 2 + ['FULL_HEAL'] * 3
    assert bought[10:] and set(bought[10:]) <= {'ULTRA_BALL', 'GREAT_BALL'}
    assert left - cash_reserve(rich) >= boss.kit_floor(5, 2, PRICES[ITEMS['MAX_POTION']], PRICES[ITEMS['REVIVE']])


def test_a_walk_into_the_league_stocks_only_what_the_counter_sells():
    # A walk in restocks when the counter sells it something, the kit boss.kit sizes for the purse, and
    # not by a fixed 10 restores and 5 Revives the kit never reaches.
    trip = Goal('league_lorelei', 'Challenge Lorelei', 'Start the League')
    kit = ((ITEMS['POKE_BALL'], 15), (ITEMS['MAX_POTION'], 2), (ITEMS['REVIVE'], 1), (ITEMS['FULL_HEAL'], 3))
    s = plateau(map=LOBBY, x=7, y=11, money=4000, items=kit)
    shop = ShoppingController()
    assert shop.plan(s, trip, None, **{**OPTIONS, 'requested_goal': trip.key}).goal is trip
    assert not shop.restocking
    plan = ShoppingController().plan(replace(s, money=12300), trip, None, **{**OPTIONS, 'requested_goal': trip.key})
    assert plan.goal.key == 'restock' and plan.goal.targets == (counter(LOBBY),)
