"""The Gen II collection ladder: every rung offers a candidate and the utility arbiter picks one."""
import inspect
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection, errands, tower
from pokesim.gen2.collection import ERRAND_FRAMES, INTERRUPT_FRAMES, MAP_FRAMES, Ladder
from pokesim.planning import values
from pokesim.planning.arbiter import Candidate, Tier


def goal(key, map_name='HERE'):
    return SimpleNamespace(key=key, label=key, map_name=map_name, x=1, y=1, face=None)


def policy(**extra):
    data = SimpleNamespace(map_ids={'HERE': 1, 'NEAR': 2, 'FAR': 3})
    hops = {(1, 1): [], (1, 2): [None], (1, 3): [None] * 20}
    nav = SimpleNamespace(route=lambda source, target: hops.get((source, target)))
    return SimpleNamespace(data=data, nav=nav, collection={'target': None}, menu=None, completed={}, decisions=10, **extra)


def ladder(owner):
    return Ladder(owner, SimpleNamespace(map=1))


def build(owner, key, result, **changes):
    def run():
        owner.collection.update(changes)
        return result
    return run


def test_the_cheaper_rung_wins_in_a_tier_and_the_losers_change_nothing():
    owner = policy()
    rungs = ladder(owner)
    rungs.offer('far', Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES, build(owner, 'far', goal('far', 'FAR'), far=1))
    rungs.offer('near', Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES, build(owner, 'near', goal('near', 'NEAR'), near=1))
    rungs.offer('later', Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES, build(owner, 'later', goal('later', 'FAR'), later=1))
    assert rungs.rung == 'near' and rungs.goal.key == 'near'
    # The far pick was beaten, so what it saved is undone. The later loser never kept its change.
    assert owner.collection == {'target': None, 'near': 1}
    near = next(candidate for candidate in rungs.candidates if candidate.goal == 'near')
    assert near.expected_frames == ERRAND_FRAMES + MAP_FRAMES


def test_a_higher_tier_wins_and_a_lower_rung_is_not_asked():
    owner = policy()
    rungs = ladder(owner)
    asked = []
    rungs.offer('rod', Tier.UPKEEP, values.NEW_ENTRY, 10 ** 6, lambda: goal('rod', 'FAR'))
    rungs.offer('gift', Tier.PROGRESS, values.NEW_ENTRY, 1, lambda: asked.append('gift') or goal('gift'))
    assert rungs.rung == 'rod' and not asked


def test_a_rung_that_offers_nothing_keeps_its_stand_down():
    owner = policy()
    rungs = ladder(owner)
    rungs.offer('hunt', Tier.PROGRESS, values.NEW_ENTRY, 0, build(owner, 'hunt', None, stood_down={'hunt:7': 3}))
    assert rungs.pick is None and owner.collection['stood_down'] == {'hunt:7': 3}


def test_the_day_care_walk_is_passive_and_runs_only_without_other_work():
    owner = policy()
    rungs = ladder(owner)
    rungs.offer('breed', Tier.PROGRESS, values.NEW_ENTRY, 0, lambda: goal('collection_hatch'))
    assert rungs.pick is None and [g.key for g in rungs.passive] == ['collection_hatch']
    rungs.offer('training', Tier.PROGRESS, values.NEW_ENTRY, 10 ** 6, lambda: goal('collection_train', 'FAR'))
    assert rungs.rung == 'training'
    assert any(candidate.passive for candidate in rungs.candidates)


def test_cutting_into_the_running_rung_pays_the_interrupt():
    owner = policy(ladder_rung='hunt')
    rungs = ladder(owner)
    rungs.offer('hunt', Tier.PROGRESS, values.NEW_ENTRY, 3 * ERRAND_FRAMES, lambda: goal('collection_hunt'))
    # Cheaper by less than the walk back to the hunt, so the hunt goes on.
    rungs.offer('gift', Tier.PROGRESS, values.NEW_ENTRY, 3 * ERRAND_FRAMES - INTERRUPT_FRAMES // 2, lambda: goal('gift'))
    assert rungs.rung == 'hunt'
    gift = next(candidate for candidate in rungs.candidates if candidate.goal == 'gift')
    assert gift.interrupt_frames == INTERRUPT_FRAMES


def test_the_clock_wait_is_a_passive_candidate_worth_its_catch():
    owner = policy()
    owner.data = SimpleNamespace(encounters=[], species={})
    mem = SimpleNamespace(byte=lambda name: 0)
    original = collection.clock_wait
    try:
        collection.clock_wait = lambda *args: 'Lapras waits for Friday'
        import pokesim.gen2.ledger as ledger
        room = ledger.catch_room
        ledger.catch_room = lambda *args: True
        try:
            wait = collection.waiting(owner, SimpleNamespace(), mem, 'day')
            assert wait.passive and wait.value == values.NEW_ENTRY
            assert collection.named_wait(owner, SimpleNamespace(), mem, 'day') == 'Lapras waits for Friday'
            ledger.catch_room = lambda *args: False
            assert collection.waiting(owner, SimpleNamespace(), mem, 'day').value == 0
            assert collection.named_wait(owner, SimpleNamespace(), mem, 'day') is None
        finally:
            ledger.catch_room = room
    finally:
        collection.clock_wait = original
    from pokesim.planning import arbiter
    hunt = Candidate('hunt', Tier.PROGRESS, values.SMALL, 10 ** 7)
    assert arbiter.choose([wait, hunt]) is hunt


def test_the_old_timers_are_gone():
    assert not hasattr(tower, 'RETRY_AFTER')
    for module in (collection, tower):
        source = inspect.getsource(module)
        assert "'attempts'" not in source and 'tower_after\'] =' not in source
    shop = inspect.getsource(__import__('pokesim.gen2.policy', fromlist=['Policy']).Policy.shop)
    for name in ('MAHOGANY_MART_1F', 'BLACKTHORN_MART', 'ICE_PATH_', 'len(route) > 5', 'BLACKTHORN_GYM_1F'):
        assert name not in shop
    assert 'clock_wait(policy' not in inspect.getsource(collection.postgame_league)


def test_a_hunt_with_no_tile_stands_down_instead_of_timing_a_retry(monkeypatch):
    owner = policy()
    owner.data.maps = {1: {'constant': 'HERE'}}
    owner.collection['target'] = {'species': 7, 'map': 1, 'method': 'grass', 'time': 'any'}
    monkeypatch.setattr(collection, 'encounter_points', lambda *args, **kwargs: [])
    Goal = lambda *args: SimpleNamespace(key=args[0])  # noqa: E731
    assert collection.hunt(owner, SimpleNamespace(map=1, x=1, y=1), Goal).key == 'collection_wait'
    assert owner.collection['target'] is None and 'attempts' not in owner.collection
    from pokesim.gen2.standdown import hunt_key, standing_down
    assert standing_down(owner, hunt_key(7))


@pytest.fixture(scope='module', params=['gold', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def test_puzzle_maps_come_from_the_map_data(real_data):
    names = {real_data.maps[mid]['constant'] for mid in errands.puzzle_maps(real_data)}
    assert {'ICE_PATH_1F', 'ICE_PATH_B1F', 'ICE_PATH_B3F', 'MAHOGANY_GYM', 'BLACKTHORN_GYM_1F', 'BLACKTHORN_GYM_2F'} <= names
    assert not names & {'MAHOGANY_MART_1F', 'BLACKTHORN_MART', 'GOLDENROD_CITY', 'ROUTE_44'}


def test_a_shop_trip_weighs_its_walk_puzzles_and_what_it_breaks_off(real_data):
    ids = real_data.map_ids
    owner = SimpleNamespace(data=real_data, completed={}, goal=None, in_league=lambda snapshot: False,
                            in_transmitter_room=lambda snapshot: False)
    town = SimpleNamespace(map=ids['GOLDENROD_CITY'], pockets={'balls': [(5, 3)]})
    assert errands.worth_trip(owner, town, 'buy_balls', 5)
    assert not errands.worth_trip(owner, town, 'buy_balls', 6)
    # The shop already chosen is walked to however far it is, but never through a puzzle.
    assert errands.worth_trip(owner, town, 'buy_balls', 20, current=True)
    assert not errands.worth_trip(owner, town, 'buy_balls', 2, [ids['ICE_PATH_B1F']], current=True)
    # After Red, and with no ball left, a longer trip is worth it.
    owner.completed = {'red': 1}
    assert errands.worth_trip(owner, town, 'buy_balls', 20)
    empty = SimpleNamespace(map=ids['GOLDENROD_CITY'], pockets={'balls': []})
    assert errands.worth(owner, empty) == errands.EMPTY_FRAMES
    # Nothing is worth breaking off a puzzle, the League or a story dungeon for.
    ice = SimpleNamespace(map=ids['ICE_PATH_B1F'], pockets={'balls': []})
    assert errands.exit_cost(owner, ice) == errands.SEQUENCE_FRAMES
    assert not errands.worth_trip(owner, ice, 'buy_balls', 1)
    owner.completed = {}
    owner.goal = SimpleNamespace(map_name='GOLDENROD_UNDERGROUND_WAREHOUSE')
    warehouse = SimpleNamespace(map=ids['GOLDENROD_UNDERGROUND_WAREHOUSE'], pockets={'balls': [(5, 3)]})
    assert errands.exit_cost(owner, warehouse) == errands.SEQUENCE_FRAMES
    owner.goal = SimpleNamespace(map_name='GOLDENROD_CITY')
    assert errands.exit_cost(owner, warehouse) == 0
