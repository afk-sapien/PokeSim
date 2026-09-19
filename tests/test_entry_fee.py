"""An objective behind a paid gate raises the fee instead of bouncing off the attendant."""
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import CASH_RESERVE, SAFARI_FEE, ShoppingController, cash_reserve, entry_fee
from pokesim.screen import Screen
from pokesim.strategy_data import ITEMS, MAPS
from test_strategy import flags, menu, mon, snap

SURF = Goal('surf', 'Find the Safari Zone’s secret house', 'Reach the secret house')


def broke(**changes):
    values = dict(map=MAPS['SAFARI_ZONE_GATE'], x=4, y=3, money=314, badges=63, party=(mon(level=40),),
                  items=((ITEMS['POKE_BALL'], 5), (ITEMS['FULL_RESTORE'], 1), (ITEMS['HP_UP'], 1),
                         (ITEMS['MOON_STONE'], 1), (ITEMS['HM01'], 1)),
                  event_flags=flags('EVENT_GOT_POKEDEX'))
    return snap(**{**values, **changes})


def plan(shop, state, goal=SURF, **changes):
    options = dict(requested_goal=goal.key, healing=False, in_league=False, has_pokedex=True)
    return shop.plan(state, goal, None, **{**options, **changes})


def test_unaffordable_safari_goal_becomes_a_sale_at_a_shop():
    shop = ShoppingController()
    goal = plan(shop, broke()).goal
    assert goal.key == 'restock' and 'fee' in goal.title
    assert (MAPS['FUCHSIA_MART'], 2, 5) in goal.targets
    assert shop.fund_target == SAFARI_FEE + CASH_RESERVE


def test_fee_is_not_raised_when_affordable_inside_the_zone_or_for_other_goals():
    for state, goal in ((broke(money=SAFARI_FEE), SURF), (broke(map=MAPS['SAFARI_ZONE_WEST']), SURF),
                        (broke(), Goal('secret_key', 'Unlock the Cinnabar gym', 'Explore the mansion'))):
        shop = ShoppingController()
        assert plan(shop, state, goal).goal is goal and not shop.fund_target
    assert entry_fee(broke(), 'teeth') == SAFARI_FEE


def test_healing_and_an_unsellable_bag_keep_the_original_goal():
    assert plan(ShoppingController(), broke(), healing=True).goal is SURF
    keepsakes = ((ITEMS['MOON_STONE'], 1), (ITEMS['HM01'], 1), (ITEMS['ELIXER'], 1))
    assert plan(ShoppingController(), broke(items=keepsakes)).goal is SURF


def test_luxuries_are_sold_before_medicine_and_balls_and_unpriced_items_never():
    state = broke()
    assert state.items[ShoppingController.fund_index(state)][0] == ITEMS['HP_UP']
    spare = broke(items=state.items + ((ITEMS['NUGGET'], 1),))
    assert spare.items[ShoppingController.fund_index(spare)][0] == ITEMS['NUGGET']
    supplies = broke(items=((ITEMS['POKE_BALL'], 5), (ITEMS['FULL_RESTORE'], 1), (ITEMS['HM01'], 1)))
    assert supplies.items[ShoppingController.fund_index(supplies)][0] == ITEMS['FULL_RESTORE']


def test_shop_menu_sells_until_the_target_is_met_then_stops():
    shop = ShoppingController()
    state = broke(map=MAPS['FUCHSIA_MART'], x=2, y=5)
    plan(shop, state)
    counter = Screen(menu({1: '  BUY', 3: '  SELL', 5: '  QUIT'}, (1, 1), top=(1, 1)))
    assert shop.step(state, counter, 'shop', 'restock', None).actions[0].button != 'b' and shop.selling
    funded = broke(map=MAPS['FUCHSIA_MART'], x=2, y=5, money=5214, items=state.items[:2] + state.items[3:])
    listing = Screen(menu({4: 'POKé BALL', 6: 'FULL RESTORE', 8: 'CANCEL'}, (5, 4), top=(5, 4)))
    assert shop.step(funded, listing, 'list', 'restock', None).actions[0].button == 'b' and not shop.selling


def test_purchases_leave_the_fee_until_both_safari_prizes_are_collected():
    assert cash_reserve(broke()) == CASH_RESERVE + SAFARI_FEE
    assert cash_reserve(broke(badges=7)) == CASH_RESERVE
    done = broke(items=((ITEMS['HM03'], 1), (ITEMS['GOLD_TEETH'], 1)))
    assert cash_reserve(done) == CASH_RESERVE
    stock = [ITEMS['ULTRA_BALL']]   # 1200 each
    assert ShoppingController.item_for(broke(money=2000, items=()), stock, 'restock', None) == ITEMS['ULTRA_BALL']
    assert ShoppingController.item_for(broke(money=1500, items=()), stock, 'restock', None) is None
    assert ShoppingController.item_for(broke(money=1500, items=(), badges=7), stock, 'restock', None) == ITEMS['ULTRA_BALL']
