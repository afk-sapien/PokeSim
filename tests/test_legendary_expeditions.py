"""Legendary trips preserve capture resources and have meaningful travel budgets."""
import random
from dataclasses import replace
from unittest.mock import Mock

from pokesim.policies.battle import choose_battle, shopping_item
from pokesim.planning import values
from pokesim.planning.cost import FRAMES_PER_TILE
from pokesim.policies.collection import EXPECTED_FRAMES, Collection, candidate
from pokesim.policies.director import AdventureDirector, category, new_entry
from pokesim.policies.progression import Goal
from pokesim.strategy_data import ITEMS, MAPS
from test_collection import sid, state
from test_strategy import mon


def test_mewtwo_is_a_new_entry_only_while_unowned_and_waits_after_a_stand_down():
    director = AdventureDirector()
    target = {'method': 'static', 'species': sid(150), 'legendary': True, 'key': 'mewtwo'}
    assert category(target) == 'legendary' and new_entry(target)
    returned = {**target, 'repeat': True, 'needed_capture': False}
    assert not new_entry(returned) and new_entry({**returned, 'needed_capture': True})
    assert candidate(target, 0, {}, False, set()).value == values.NEW_ENTRY
    assert candidate(target, 0, {}, False, {150}).value == values.SMALL
    director.finish(target, 0, False, 'No encounter')
    assert director.waiting('mewtwo', 1)


def test_mewtwo_project_has_a_longer_budget_and_new_retry_key(monkeypatch):
    c = Collection()
    c.completed_champion = True
    c.elapsed = 2000
    c.director.monitor.stand_down('131:static:227:MEWTWO', c.elapsed)
    monkeypatch.setattr(c, 'sources', lambda: {sid(150): [{'map': MAPS['CERULEAN_CAVE_B1F'],
                    'method': 'static', 'fragment': 'MEWTWO', 'flag': 'EVENT_BEAT_MEWTWO'}]})
    monkeypatch.setattr(c.director, 'select', lambda options, projects: next(
        p for p in projects.values() if p.get('legendary')))
    nav = Mock()
    nav.distance_lookup.return_value = lambda targets: 900
    nav.visits = []
    c.choose(state(), nav, random.Random(1), Goal('collect_plan', 'Plan', 'Plan'))
    assert c.project['species'] == sid(150)
    assert c.project['key'] == 'legendary:131:227'
    # Three times the walk and the special project's own frames.
    assert c.remaining == 3 * (900 * FRAMES_PER_TILE + EXPECTED_FRAMES['special'])


def test_expedition_shops_for_ultra_balls_instead_of_cheaper_balls():
    items = ((ITEMS['POKE_BALL'], 50), (ITEMS['ULTRA_BALL'], 14))
    assert shopping_item(items, [ITEMS['POKE_BALL']], 40000, legendary=True) is None
    assert shopping_item(items, [ITEMS['ULTRA_BALL']], 40000, legendary=True) == ITEMS['ULTRA_BALL']
    assert shopping_item(((ITEMS['ULTRA_BALL'], 20),), [ITEMS['ULTRA_BALL']], 40000, legendary=True) is None


def test_capture_reapplies_sleep_after_waking_and_saves_balls_for_target():
    me = mon(species=sid(3), level=100, hp=300, max_hp=300, moves=(79, 33), pp=(14, 35))
    enemy = mon(species=sid(150), level=70, hp=200, max_hp=200, moves=(33,), pp=(35,))
    s = state(party=(me,), in_battle=1, items=((ITEMS['ULTRA_BALL'], 20),))
    decision = choose_battle(s, me, enemy, 0, used_status=(79,), collect_missing=True, capture_species=sid(150))
    assert decision.kind == 'fight' and decision.index == 0
    ordinary = replace(enemy, species=sid(16), level=70, hp=1)
    decision = choose_battle(s, me, ordinary, 0, collect_missing=True, capture_species=sid(150))
    assert decision.kind == 'run'


def test_route_battles_do_not_cancel_a_legendary_trip_on_return_to_overworld():
    c = Collection()
    c.project = {'method': 'static', 'species': sid(150), 'legendary': True, 'key': 'mewtwo'}
    c.remaining = 180000
    c.observe(state(frame=0, in_battle=1))
    for frame in range(120, 7441, 120):
        c.observe(state(frame=frame, in_battle=1))
    c.observe(state(frame=7560, in_battle=0))
    assert c.project is not None
    assert c.idle_frames == 0
    for frame in range(7680, 15001, 120):
        c.observe(state(frame=frame, in_battle=0))
    assert c.project is None


def test_legendary_supply_list_includes_repel_available_at_the_mart():
    items = ((ITEMS['ULTRA_BALL'], 20),)
    assert shopping_item(items, [ITEMS['ULTRA_BALL'], ITEMS['SUPER_REPEL']], 40000,
                         legendary=True) == ITEMS['SUPER_REPEL']
    assert shopping_item(items, [ITEMS['ULTRA_BALL'], ITEMS['MAX_REPEL']], 40000,
                         legendary=True) == ITEMS['MAX_REPEL']


def test_crowded_bag_can_sell_a_booster_but_keeps_key_items():
    from pokesim.policies.strategic import StrategicPolicy
    keys = tuple((ITEMS[name], 1) for name in ('S_S_TICKET', 'HM01', 'LIFT_KEY', 'SILPH_SCOPE',
        'POKE_FLUTE', 'CARD_KEY', 'HM03', 'HM04', 'HM05', 'SECRET_KEY', 'SUPER_ROD',
        'OLD_ROD', 'GOOD_ROD', 'COIN_CASE', 'REVIVE', 'MAX_REVIVE', 'ESCAPE_ROPE'))
    s = state(items=keys + ((ITEMS['X_ACCURACY'], 1),))
    assert StrategicPolicy._sale_index(s) == 17
    assert StrategicPolicy._sale_index(replace(s, items=keys)) is None


def test_a_bag_full_of_key_items_sells_a_spare_repel_for_legendary_supplies():
    """A Red run dropped Articuno, Zapdos and Moltres with "Need money or bag space for legendary
    capture supplies" while it held 60,958 money. Its bag, copied from the live run, had no room
    for Ultra Balls and nothing the shop rules would sell."""
    from pokesim.policies.shopping import ShoppingController
    bag = tuple((ITEMS[name], count) for name, count in (
        ('S_S_TICKET', 1), ('HM01', 1), ('LIFT_KEY', 1), ('SILPH_SCOPE', 1), ('POKE_FLUTE', 1), ('CARD_KEY', 1),
        ('HM03', 1), ('HM04', 1), ('SECRET_KEY', 1), ('SUPER_ROD', 1), ('OLD_ROD', 1), ('GOOD_ROD', 1), ('HM05', 1),
        ('COIN_CASE', 1), ('MAX_ETHER', 1), ('MAX_REPEL', 3), ('MOON_STONE', 1), ('SUPER_REPEL', 3),
        ('GREAT_BALL', 13), ('REVIVE', 5)))
    project = {'method': 'static', 'species': sid(144), 'legendary': True, 'key': 'articuno'}
    goal = Goal('collect_legendary', 'Catch Articuno', 'Bring supplies to the Seafoam Islands')
    s = state(map=MAPS['FUCHSIA_CITY'], money=60958, items=bag, badges=255)
    plan = ShoppingController().plan(s, goal, project, requested_goal=goal.key, healing=False, in_league=False,
                                     has_pokedex=True)
    assert plan.abandon is None and plan.goal.key == 'restock'
    # The weaker repel goes, since the Max Repels are used first and are what the trip restocks.
    assert bag[ShoppingController.sale_index(s)][0] == ITEMS['SUPER_REPEL']
    # The best repel stays even in a full bag, and so does a lone one.
    assert ShoppingController.sale_index(replace(s, items=bag[:17] + bag[18:] + ((ITEMS['ULTRA_BALL'], 5),))) is None


def test_a_mart_without_ultra_balls_does_not_finish_legendary_preparation():
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.screen import Screen
    from test_strategy import menu
    p = StrategicPolicy(1)
    p.collection.project = {'method': 'static', 'species': sid(150), 'legendary': True}
    s = state(map=MAPS['CERULEAN_MART'], money=40000, items=((ITEMS['ULTRA_BALL'], 14),))
    mem = menu({1: 'BUY', 3: 'SELL', 5: 'QUIT'}, (0, 1))
    p._dispatch(s, Screen(mem), 'shop', mem)
    assert not p.collection.project.get('supplies_prepared')


def test_barrier_does_not_make_a_damaging_attack_safe_for_legendary_capture():
    me = mon(species=sid(75), level=100, hp=300, max_hp=311, attack=250,
             moves=(70, 89, 88, 153), pp=(15, 10, 15, 5))
    enemy = mon(species=sid(150), level=70, hp=183, max_hp=228, defense=999,
                moves=(112, 105, 94, 129), pp=(20, 20, 10, 20))
    s = state(party=(me,), in_battle=1, items=((ITEMS['ULTRA_BALL'], 20),))
    decision = choose_battle(s, me, enemy, 0, collect_missing=True)
    assert decision.kind == 'item'


def test_accidentally_opened_move_menu_cannot_attack_a_missing_legendary():
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.screen import Screen
    from pokesim.policies import strategic
    from test_strategy import menu
    from unittest.mock import patch
    p = StrategicPolicy(1)
    me = mon(species=sid(75), moves=(89, 153, 88, 70), pp=(10, 5, 15, 15))
    enemy = mon(species=sid(150), level=70)
    s = state(party=(me,), in_battle=1)
    mem = menu({13: 'EARTHQUAKE', 14: 'EXPLOSION', 15: 'ROCK THROW', 16: 'STRENGTH'}, (5, 13))
    with patch.object(strategic, 'read_battler', side_effect=(me, enemy)):
        actions = p._dispatch(s, Screen(mem), 'moves', mem)
    assert actions[0].button == 'b'


def test_resolved_uncaught_encounter_stops_interacting_with_the_empty_spot():
    from test_strategy import flags
    c = Collection()
    c.project = {'method': 'static', 'species': sid(150), 'legendary': True,
                 'flag': 'EVENT_BEAT_MEWTWO', 'key': 'mewtwo'}
    c.remaining = 180000
    c.observe(state(event_flags=flags('EVENT_BEAT_MEWTWO')))
    assert c.project is None
    assert c.director.outcomes[-1]['reason'] == 'Legendary encounter ended without a catch'
