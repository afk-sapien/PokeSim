"""A restock for 0 medicine ends at an ordinary mart, and no restock crosses Victory Road to shop.

A Red run reached Viridian with 20 bag entries and no medicine. It sold a TM, bought 2 Antidotes into the
freed entry and left with 19, so no ordinary mart could sell it a restore. Only the Indigo Plateau lobby,
whose limit is 20, could, and the run walked Victory Road to it for 30 minutes.
"""
from dataclasses import replace

from pokesim.policies.progression import Goal
from pokesim.policies.shopping import BALL_KINDS, RESTORES, ShoppingController, cure_room, plateau_side, supply_room
from pokesim.strategy_data import DATA, ITEMS, MAPS
from test_events import snap
from test_restock_reach import counter, reach
from test_strategy import flags, mon

GOAL = Goal('train_league_partner', 'Train a partner for the League', 'Train')
OPTIONS = dict(requested_goal=GOAL.key, healing=False, in_league=False, has_pokedex=True)
KEPT = tuple((ITEMS[name], 1) for name in ('MOON_STONE', 'DOME_FOSSIL', 'S_S_TICKET', 'HM01', 'LIFT_KEY', 'SILPH_SCOPE',
                                           'POKE_FLUTE', 'CARD_KEY', 'HM03', 'HM04', 'SECRET_KEY'))
SPARE = ((ITEMS['ELIXER'], 1), (ITEMS['GREAT_BALL'], 5), (ITEMS['POKE_BALL'], 5), (ITEMS['ULTRA_BALL'], 5),
         (214, 1), (238, 1), (ITEMS['REVIVE'], 1))           # 214 and 238 are TM14 and TM38
# The Red bag as it left Viridian Mart, and as it came in with TM27 and TM06.
LEFT = KEPT + SPARE + ((ITEMS['ANTIDOTE'], 2),)
CAME = KEPT + SPARE + ((227, 1), (206, 1))
LOBBY = MAPS['INDIGO_PLATEAU_LOBBY']


def viridian(items, **changes):
    values = dict(map=MAPS['VIRIDIAN_CITY'], x=29, y=20, money=5000, badges=255, items=items,
                  party=(mon(level=60, moves=(70, 57, 15, 0)),), event_flags=flags('EVENT_GOT_POKEDEX'))
    values.update(changes)
    return snap(**values)


def mart(name, items):
    return viridian(items, map=MAPS[name], x=3, y=6)


def test_a_viridian_restock_with_no_medicine_and_19_entries_goes_to_a_restore_mart_and_not_the_lobby():
    s = viridian(LEFT)
    assert len(s.items) == 19 and supply_room(s, RESTORES)
    targets = ShoppingController(restocking=True).plan(s, GOAL, None, **OPTIONS).goal.targets
    assert counter(LOBBY) not in targets and counter(MAPS['PEWTER_MART']) in targets
    # Viridian Mart sells no restore, so the trip goes on to the nearest mart that does.
    assert counter(MAPS['VIRIDIAN_MART']) not in targets
    plan = ShoppingController(restocking=True).plan(s, GOAL, None, **OPTIONS, reach=reach(s)).goal
    assert plan.key == 'restock' and plan.targets == (counter(MAPS['PEWTER_MART']),)
    assert ShoppingController().step(mart('PEWTER_MART', LEFT), GOAL.key, None).request == ('buy', ITEMS['POTION'], 3)


def test_a_trip_that_picked_viridian_mart_ends_there():
    # The bag came in full, so the trip picked the nearest counter to sell at. Once it sold, Viridian
    # Mart had nothing left for the bag, and the trip ended there rather than walking on to Pewter.
    came = viridian(CAME)
    shop = ShoppingController()
    assert shop.plan(came, GOAL, None, **OPTIONS, reach=reach(came)).goal.targets == (counter(MAPS['VIRIDIAN_MART']),)
    sold = mart('VIRIDIAN_MART', CAME[:-2] + CAME[-1:])
    assert shop.plan(sold, GOAL, None, **OPTIONS, reach=reach(sold)).goal is GOAL and not shop.restocking


def test_a_restore_outranks_a_cure_for_the_last_entry():
    # The bag sold TM27 at the counter, and the entry it freed is the restore's, not an Antidote's.
    sold = mart('VIRIDIAN_MART', CAME[:-2] + CAME[-1:])
    assert ShoppingController().step(mart('VIRIDIAN_MART', CAME), GOAL.key, None).request == ('sell', 227, 1)
    assert supply_room(sold, RESTORES) and not cure_room(sold)
    assert ShoppingController().step(sold, GOAL.key, None).request is None
    held = replace(sold, items=sold.items[:-1] + ((ITEMS['POTION'], 3),))
    assert cure_room(held)
    assert ShoppingController.item_for(held, DATA['marts']['ViridianMart'], GOAL.key, None) == ITEMS['ANTIDOTE']


def test_a_bag_with_no_room_sells_its_cure_for_a_first_restore():
    # Two fossils no ledger sells leave a 19-entry bag no room past a restore.
    keys = tuple((item, 1) for item in (6, 5, 73, 72, 48, 69, 71, 76, 77, 75, 196, 197, 198, 199, 200))
    locked = keys + ((ITEMS['HELIX_FOSSIL'], 1), (ITEMS['SECRET_KEY'], 1), (ITEMS['ULTRA_BALL'], 15),
                     (ITEMS['ANTIDOTE'], 2))
    shop = ShoppingController()
    assert shop.step(mart('PEWTER_MART', locked), GOAL.key, None).request == ('sell', ITEMS['ANTIDOTE'], 2)
    sold = mart('PEWTER_MART', locked[:-1])
    assert shop.step(sold, GOAL.key, None).request == ('buy', ITEMS['POTION'], 3)
    # With the restore held the cure is not bought back, and a mart with no restore sells nothing.
    assert shop.step(mart('PEWTER_MART', locked[:-1] + ((ITEMS['POTION'], 3),)), GOAL.key, None).request is None
    assert shop.step(mart('VIRIDIAN_MART', locked), GOAL.key, None).request is None


def test_a_hunt_with_no_ball_and_no_room_restocks_at_an_ordinary_mart_and_sells_its_revive():
    # A Red Clefairy hunt threw its last ball in Mt. Moon with 19 entries and nothing the ledger sells.
    # Only the lobby could add a ball, and the trip would cross Victory Road to shop.
    names = ('S_S_TICKET', 'HM01', 'HM05', 'LIFT_KEY', 'SILPH_SCOPE', 'POKE_FLUTE', 'CARD_KEY', 'HM03', 'HM04',
             'SECRET_KEY', 'OLD_ROD', 'SUPER_ROD', 'GOOD_ROD', 'MOON_STONE', 'REVIVE', 'MASTER_BALL', 'MAX_ELIXER',
             'ELIXER', 'MAX_POTION')
    spent = tuple((ITEMS[name], 1) for name in names)
    s = viridian(spent, map=MAPS['MT_MOON_B2F'], x=6, y=7)
    assert supply_room(s, BALL_KINDS) and not supply_room(s, RESTORES)
    plan = ShoppingController().plan(s, GOAL, None, **OPTIONS, reach=reach(s)).goal
    assert plan.key == 'restock' and len(plan.targets) == 1 and plan.targets[0][0] != LOBBY
    shop = ShoppingController()
    at = mart('CERULEAN_MART', spent)
    assert shop.step(at, GOAL.key, None).request == ('sell', ITEMS['REVIVE'], 1)
    sold = mart('CERULEAN_MART', tuple(row for row in spent if row[0] != ITEMS['REVIVE']))
    assert shop.step(sold, GOAL.key, None).request == ('buy', ITEMS['POKE_BALL'], 15)


def test_the_plateau_side_is_the_road_the_plateau_and_the_route_23_strip_between_them():
    assert plateau_side(snap(map=MAPS['VICTORY_ROAD_1F'], x=9, y=16))
    assert plateau_side(snap(map=MAPS['INDIGO_PLATEAU'], x=9, y=7))
    assert plateau_side(snap(map=MAPS['ROUTE_23'], x=14, y=32)) and plateau_side(snap(map=MAPS['ROUTE_23'], x=18, y=30))
    assert not plateau_side(snap(map=MAPS['ROUTE_23'], x=4, y=32))
    assert not plateau_side(snap(map=MAPS['ROUTE_23'], x=13, y=57))
    assert not plateau_side(viridian(LEFT))
