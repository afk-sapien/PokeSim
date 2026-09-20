"""Route 23 checks a badge at each gate, and the Indigo Plateau shop is only a plan with all eight."""
from pokesim.policies.navigation import ROUTE_23_CHECKS, Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.shopping import ShoppingController
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import flags, mon

ROUTE_23 = MAPS['ROUTE_23']


def test_a_missing_badge_closes_its_row_and_earning_it_opens_the_road():
    nav = Navigator()
    nav.update_story(snap(map=ROUTE_23, badges=63))          # six badges: Volcano and Earth missing
    assert (ROUTE_23, 12, 56) in nav.story_blocks and (ROUTE_23, 4, 35) in nav.story_blocks
    assert (ROUTE_23, 12, 105) not in nav.story_blocks
    assert all(target != (ROUTE_23, 12, 56) for _, target in nav.neighbors((ROUTE_23, 12, 57), 0))
    nav.update_story(snap(map=ROUTE_23, badges=255))
    assert not any(m == ROUTE_23 for m, _, _ in nav.story_blocks)
    assert {badge for _, badge in ROUTE_23_CHECKS} == {2, 4, 8, 16, 32, 64, 128}


def test_the_indigo_plateau_shop_is_not_a_restock_plan_without_every_badge():
    # A full bag with no Poké Balls could only buy more Max Potions, which only Indigo Plateau sells.
    junk = tuple((ITEMS[name], 1) for name in ('MOON_STONE', 'DOME_FOSSIL', 'S_S_TICKET', 'HM01', 'MAX_ETHER', 'LIFT_KEY',
                                               'SILPH_SCOPE', 'ELIXER', 'ESCAPE_ROPE', 'POKE_FLUTE', 'CARD_KEY', 'PARLYZ_HEAL',
                                               'MAX_POTION', 'PROTEIN', 'HM03', 'HM04', 'HP_UP', 'CARBOS', 'RARE_CANDY'))
    goal = Goal('secret_key', 'Unlock the Cinnabar gym', 'Explore the mansion')
    options = dict(requested_goal=goal.key, healing=False, in_league=False, has_pokedex=True)
    state = snap(map=ROUTE_23, x=13, y=57, money=3890, badges=63, party=(mon(level=60),), items=junk,
                 event_flags=flags('EVENT_GOT_POKEDEX'))
    assert ShoppingController().plan(state, goal, None, **options).goal is goal
    champion = snap(map=ROUTE_23, x=13, y=57, money=3890, badges=255, party=(mon(level=60),), items=junk,
                    event_flags=flags('EVENT_GOT_POKEDEX'))
    plan = ShoppingController().plan(champion, goal, None, **options).goal
    assert plan.key == 'restock' and plan.targets == ((MAPS['INDIGO_PLATEAU_LOBBY'], 2, 5),)
