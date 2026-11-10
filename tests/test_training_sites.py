"""Every map a training or hunting walk can head for has wild Pokémon in the cartridge's table, within reach."""
import os
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def mon(level, trainer_id=1, experience=1000):
    return SimpleNamespace(species=155, level=level, egg=False, trainer_id=trainer_id, dvs=(level % 16,) * 5,
                           experience=experience, name='MON')


def at_mr_pokemons_house(data, *party):
    """Where a Gold run stood for hours once the Exp. Share errand ended (#359), with every Johto badge."""
    mid = data.map_ids['MR_POKEMONS_HOUSE']
    door = data.maps[mid]['warps'][0]
    return SimpleNamespace(map=mid, x=door['x'], y=door['y'], badges=0xFF, party=party, stored=(), items=())


def mid_jump_outside_silver_cave(data, *party):
    """Halfway down the left ledge at (21, 20) outside the Silver Cave Pokémon Center.

    In a ledge jump the coordinates read the wall tile jumped over until the player lands. A Crystal
    postgame run found no route to Mt. Silver from there, ended training, and stood down one trainee
    after another (#376).
    """
    mid = data.map_ids['SILVER_CAVE_OUTSIDE']
    entry = data.maps[mid]
    assert entry['collision'][20 * entry['width'] + 21] == 0xA1
    return SimpleNamespace(map=mid, x=20, y=20, badges=0xFF, party=party, stored=(), items=(), objects=())


def policy_for(data):
    from pokesim.gen2.policy import Policy
    policy = Policy(data)
    policy.memory = None
    return policy


def rows(data, name):
    mid = data.map_ids[name]
    return [row for row in data.encounters if row['map'] == mid and row['method'] == 'grass']


def test_named_training_maps_have_wild_tables(data):
    from pokesim.gen2.collection import PATROL_MAP
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.training import SITE
    for name in (SITE, PATROL_MAP, *Policy.BOSS_TRAINING.values()):
        assert rows(data, name), name


def test_a_victory_road_walk_aims_at_floor_it_can_reach(data):
    """Victory Road's top left corner is cave floor outside its walls. A walk once aimed there, found no
    route and stood in Mr. Pokémon's House while each trainee in turn gained nothing."""
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal
    policy = policy_for(data)
    snapshot = at_mr_pokemons_house(data, mon(56))
    road = data.map_ids['VICTORY_ROAD']
    points = training.walk_points(policy, snapshot, road)
    assert points and (0, 0) not in {point[:2] for point in points}
    goal = training.walk_goal(policy, snapshot, Goal, lambda: 'Train', map_name='VICTORY_ROAD')
    assert goal.map_name == 'VICTORY_ROAD' and (goal.x, goal.y) in {point[:2] for point in points}
    route = policy.nav.regions.route(snapshot, road, [(goal.x, goal.y)], cut=True, surf=True)
    assert route


@pytest.mark.parametrize('project', [{'map': 'VICTORY_ROAD'}, {}])
@pytest.mark.parametrize('level', [5, 20, 40, 60, 99])
def test_every_site_the_picker_returns_has_a_wild_table_and_a_reachable_tile(data, project, level):
    from pokesim.gen2 import training
    from pokesim.gen2.standdown import site_key, stand_down
    policy = policy_for(data)
    trainee = mon(level)
    snapshot = at_mr_pokemons_house(data, trainee)
    seen = []
    # Standing each pick down walks the picker through every fallback it can return from here.
    while (place := training.site(policy, snapshot, dict(project), trainee)) is not None:
        assert place not in seen and len(seen) <= training.SITES
        seen.append(place)
        mid = data.map_ids[place]
        assert rows(data, place), place
        assert training.walk_points(policy, snapshot, mid), place
        stand_down(policy, site_key(mid))
    assert seen
    if project:
        assert seen[0] == 'VICTORY_ROAD'
    assert training.site(policy_for(data), snapshot, dict(project), mon(100)) is None


def test_a_stint_without_experience_fails_its_site_for_the_next_trainee(data):
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import STAND_DOWNS, site_key, standing_down
    policy = policy_for(data)
    first, second = mon(30, trainer_id=1), mon(28, trainer_id=2)
    snapshot = at_mr_pokemons_house(data, first, second)
    road = data.map_ids['VICTORY_ROAD']
    project = {'map': 'VICTORY_ROAD', 'identity': training.identity(first)}
    assert training.site(policy, snapshot, project, first) == 'VICTORY_ROAD'
    project['site'] = 'VICTORY_ROAD'
    policy.collection['training'] = project
    policy.goal = Goal('collection_train', 'Train', 'VICTORY_ROAD', 1, 1)
    for _ in range(20000):
        if policy.collection['training'] is None:
            break
        policy.decisions += 1
        training.observe(policy, snapshot)
    assert policy.collection['training'] is None
    key = site_key(road)
    assert standing_down(policy, key)
    assert policy.collection[STAND_DOWNS][key] == 1
    # The next trainee does not take the same walk.
    assert training.site(policy, snapshot, {'map': 'VICTORY_ROAD'}, second) not in {None, 'VICTORY_ROAD'}


def test_a_stint_that_gained_keeps_its_site(data):
    from pokesim.gen2 import training
    from pokesim.gen2.standdown import site_key, standing_down
    policy = policy_for(data)
    project = {'site': 'VICTORY_ROAD', 'gained': True}
    training.site_failed(policy, project)
    assert not standing_down(policy, site_key(data.map_ids['VICTORY_ROAD']))


def test_a_stint_split_by_a_break_is_one_stint(data):
    """A heal between two halves of one stint keeps the first half's experience, so the second half never
    counts as a stint without experience."""
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import site_key, standing_down
    policy = policy_for(data)
    trainee = mon(30)
    project = {'map': 'VICTORY_ROAD', 'site': 'VICTORY_ROAD', 'identity': training.identity(trainee)}
    policy.collection['training'] = project
    train, heal = Goal('collection_train', 'Train', 'VICTORY_ROAD', 1, 1), Goal('heal', 'Heal', None, 1, 1)
    policy.goal = train
    training.observe(policy, at_mr_pokemons_house(data, trainee))
    policy.decisions += 1
    training.observe(policy, at_mr_pokemons_house(data, mon(30, experience=1500)))
    policy.goal = heal
    for _ in range(50):
        policy.decisions += 1
        training.observe(policy, at_mr_pokemons_house(data, mon(30, experience=1500)))
    policy.goal = train
    for _ in range(20000):
        if policy.collection['training'] is None:
            break
        policy.decisions += 1
        training.observe(policy, at_mr_pokemons_house(data, mon(30, experience=1500)))
    assert not standing_down(policy, site_key(data.map_ids['VICTORY_ROAD']))


def test_a_reload_for_lack_of_progress_fails_the_site_of_a_stint_without_experience(data):
    """A walk with no route ends in a reload, and that reload counts as a failed attempt at the site."""
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import site_key, stalled_objectives, train_key
    policy = policy_for(data)
    policy.goal = Goal('collection_train', 'Train', 'VICTORY_ROAD', 1, 1)
    identity = [1, [0] * 5]
    policy.collection['training'] = {'identity': identity, 'site': 'VICTORY_ROAD'}
    keys = set(stalled_objectives(policy)['keys'])
    assert {train_key(identity), site_key(data.map_ids['VICTORY_ROAD'])} <= keys
    policy.collection['training']['gained'] = True
    assert site_key(data.map_ids['VICTORY_ROAD']) not in stalled_objectives(policy)['keys']


def test_a_trainee_mid_jump_keeps_its_site(data):
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal
    policy = policy_for(data)
    trainee = mon(60)
    snapshot = mid_jump_outside_silver_cave(data, trainee)
    assert training.site(policy, snapshot, {}, trainee) == training.SITE
    goal = training.walk_goal(policy, snapshot, Goal, lambda: 'Train')
    assert goal is not None and goal.map_name == training.SITE
    # Once landed, the walk judges the route again.
    landed = mid_jump_outside_silver_cave(data, trainee)
    landed.x = 19
    assert training.walk_points(policy, landed, data.map_ids[training.SITE])


def test_a_hunt_mid_jump_aims_at_a_tile_instead_of_giving_up(data):
    from pokesim.gen2 import collection
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import SITE
    policy = policy_for(data)
    snapshot = mid_jump_outside_silver_cave(data, SimpleNamespace(**vars(mon(60)), moves=()))
    # A search of the grass here, and one of the cave floor beyond.
    for name in ('SILVER_CAVE_OUTSIDE', SITE):
        goal = collection.hunt(policy, snapshot, Goal, target=dict(rows(data, name)[0], started=0), label='Search')
        assert goal is not None and goal.key == 'collection_hunt', name


def test_gen1_training_sites_have_wild_tables_and_tiles():
    """Gen 1 walks pick any reachable tile among all of a map's encounter tiles, so each site needs rows and tiles."""
    from pokesim.policies.collection import DATA, _training_tiles, evolution_training_targets, training_targets
    from pokesim.policies.progression import GYMS, training_goal
    from pokesim.strategy_data import MAPS
    for version, table in DATA['versions'].items():
        grass = {row['map'] for sources in table.values() for row in sources if row['method'] == 'grass'}
        for place in {row[6] for row in GYMS} | {'ROUTE_23', 'POKEMON_MANSION_1F'}:
            assert MAPS[place] in grass, (version, place)
            assert training_goal('x', place, '', place).targets, (version, place)
        for level in range(2, 101):
            for targets in (training_targets(version, level), evolution_training_targets(version, level)):
                for map_id in {target[0] for target in targets}:
                    assert map_id in grass and _training_tiles(map_id), (version, level, map_id)
