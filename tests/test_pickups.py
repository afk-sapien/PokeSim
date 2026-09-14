from dataclasses import replace
import json
from unittest.mock import Mock

from pokesim.policies.collection import Collection
from pokesim.policies.navigation import Navigator
from pokesim.policies.pickups import Pickups, ground_item
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import DATA, ITEMS, MAPS, WORLD
from test_collection import state, sid


def cave():
    return state(map=MAPS['VICTORY_ROAD_2F'], x=18, y=10, money=100000,
                 items=((ITEMS['POKE_BALL'], 10), (ITEMS['SUPER_POTION'], 5)),
                 hidden_objects=bytes(64), hall_of_fame_count=1)


def hidden(s, index):
    bits = bytearray(s.hidden_objects)
    offset = DATA['toggle_objects'].index([s.map, index])
    bits[offset // 8] |= 1 << (offset % 8)
    return replace(s, hidden_objects=bytes(bits))


def test_item_detection_excludes_starters_gifts_and_disguised_pokemon():
    balls = [obj for w in WORLD.values() for obj in w['objects'] if obj[2] == 'SPRITE_POKE_BALL']
    for obj in balls:
        if any(name in obj[4] for name in ('BULBASAUR', 'CHARMANDER', 'SQUIRTLE', 'VOLTORB', 'ELECTRODE', 'EEVEE', 'HITMON')):
            assert ground_item(obj) is None
    potion = next(obj for obj in balls if obj[4] == 'TEXT_MTMOON1F_POTION2')
    assert ground_item(potion)['item'] == ITEMS['POTION']
    tm = next(obj for obj in balls if obj[4] == 'TEXT_VICTORYROAD2F_TM_SUBMISSION')
    assert ground_item(tm)['name'] == 'TM Submission'


def test_pickup_works_in_victory_road_during_a_collection_objective():
    s = cave()
    p = StrategicPolicy(1)
    p.collection.project = {'method': 'grass', 'species': sid(132), 'map': MAPS['ROUTE_15'], 'key': 'ditto'}
    p.goal = p.collection.goal(s)
    p.collection.choose = Mock(return_value=p.goal)
    p.nav.update_story(s)
    p._overworld(s, bytearray(65536))
    assert p.goal.key == 'collect_pickup'
    assert p.goal.title == 'Pick up Full Heal'
    assert p.collection.project['key'] == 'ditto'


def test_completion_requires_the_object_to_disappear_and_survives_restart():
    s = cave()
    nav = Navigator()
    nav.update_story(s)
    p = Pickups()
    main = Goal('collect_plan', 'Plan', 'Plan')
    assert p.choose(s, nav, main, 0).title == 'Pick up Full Heal'
    index = p.active['object']
    p.observe(s, 100)
    assert p.active is not None
    restored = Pickups()
    restored.load(json.loads(json.dumps(p.state_dict())))
    after = hidden(s, index)
    restored.observe(after, 200)
    assert restored.active is None
    assert restored.history == ['Collected Full Heal']
    assert f'{s.map}:{index}' in restored.completed
    restored.choose(after, nav, main, 1000)
    assert not restored.active or restored.active['object'] != index


def test_full_bag_accepts_an_existing_stack_but_not_a_new_item_or_full_stack():
    full = tuple((item, 1) for item in range(30, 50))
    s = replace(cave(), items=full)
    assert not Pickups.has_space(s, ITEMS['FULL_HEAL'])
    assert Pickups.has_space(s, 30)
    assert not Pickups.has_space(replace(s, items=((30, 99),) + full[1:]), 30)
    assert not Pickups.has_space(s, None)


def test_unreachable_item_is_not_selected_and_failed_pickups_have_a_persisted_retry():
    s = cave()
    nav = Navigator()
    nav.update_story(s)
    p = Pickups()
    main = Goal('collect_plan', 'Plan', 'Plan')
    assert p.choose(s, nav, main, 0)
    key = p.active['key']
    p.observe(s, 1800)
    assert p.active is None and p.retry[key] > 1800
    restored = Pickups()
    restored.load(json.loads(json.dumps(p.state_dict())))
    assert restored.retry == p.retry
    nav.route = Mock(return_value=None)
    assert Pickups().choose(replace(s, x=17, y=10), nav, main, 0) is None


def test_healing_and_party_management_take_priority_over_pickups():
    s = cave()
    nav = Navigator()
    for key in ('heal', 'restock', 'party_collection', 'teach_surf', 'league_lorelei'):
        p = Pickups()
        assert p.choose(s, nav, Goal(key, key, key), 0) is None
        assert p.active is None


def test_pickup_time_does_not_consume_the_main_project_budget():
    c = Collection()
    c.project = {'method': 'grass', 'species': sid(132), 'key': 'ditto'}
    c.remaining = 1000
    c.observe(cave())
    c.observe(replace(cave(), frame=120), suspended=True)
    assert c.remaining == 1000
    assert c.elapsed == 120
    c.observe(replace(cave(), frame=240))
    assert c.remaining == 880


def test_legacy_saves_load_without_pickup_state():
    p = StrategicPolicy(1)
    p.load_state_dict({'version': 1})
    assert p.pickups.active is None
    assert p.pickups.completed == []


def test_stationary_pickup_recovery_preserves_the_original_expedition():
    s = cave()
    p = StrategicPolicy(1)
    p.collection.project = {'method': 'grass', 'species': sid(132), 'key': 'ditto'}
    p.nav.update_story(s)
    p.pickups.choose(s, p.nav, Goal('collect_plan', 'Plan', 'Plan'), 0)
    assert p.pickups.active
    p.recover_stall(s)
    assert p.pickups.active is None
    assert p.pickups.retry
    assert p.collection.project['key'] == 'ditto'


def test_ground_item_journal_requires_a_new_pickup_flag_and_does_not_repeat():
    from pokesim.events import RunMemory, diff
    before = cave()
    index = next(i for i, obj in enumerate(WORLD[before.map]['objects']) if obj[4].endswith('FULL_HEAL'))
    after = replace(hidden(before, index), items=before.items + ((ITEMS['FULL_HEAL'], 1),))
    memory = RunMemory(seen_maps={before.map})
    events = diff(before, after, memory)
    pickup = next(event for event in events if event.title == 'Picked up Full Heal')
    assert pickup.still(after)
    assert not pickup.still(before)
    assert not [event for event in diff(after, after, memory) if event.type == 'item']
    bought = replace(before, items=after.items)
    assert not [event for event in diff(before, bought, memory) if event.type == 'item']
