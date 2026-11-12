"""The map audit passes on every game, and still catches the map facts behind #254, #241, #268 and #124, and walks through Ilex Forest or over a gate link without the field move.

Check E walks the story steps of all five games. Each step is offered in turn and reachable from the one before."""
import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pokesim import game_data, story
from pokesim.gen2.navigation import Navigator
from pokesim.gen2.routes import CARPETS, Regions, walk_crossings

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('map_audit_tool', ROOT / 'tools' / 'map_audit.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


@pytest.fixture(scope='module', params=tool.GAMES)
def game(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, request.param)
    return request.param, data, tool.audit(data)


def test_every_allow_row_names_its_games_and_a_reason():
    for key, (games, reason) in tool.ALLOWED.items():
        assert games and games <= tool.EVERY, key
        assert reason.strip(), key


def test_every_finding_is_allowed_and_every_allow_row_is_found(game):
    name, _, findings = game
    new, stale = tool.problems(name, findings)
    assert new == {}
    assert stale == []


SEAMS = {
    ('seam', 'ROUTE_44', 'east', 'BLACKTHORN_CITY', 'pocket'),
    ('seam', 'BLACKTHORN_CITY', 'west', 'ROUTE_44', 'pocket'),
    ('seam', 'ROUTE_10_NORTH', 'south', 'ROUTE_10_SOUTH', 'pocket'),
    ('seam', 'ROUTE_10_SOUTH', 'north', 'ROUTE_10_NORTH', 'pocket'),
    ('seam', 'AZALEA_TOWN', 'west', 'ROUTE_34', 'no crossing'),
    ('seam', 'ROUTE_34', 'east', 'AZALEA_TOWN', 'no crossing'),
}


def test_a_router_that_counts_every_link_fails_on_the_seams(game):
    # The router counted Blackthorn one map from Route 44, so a healing trip walked into Ice Path
    # and stalled (#254). The walk router skips that link and five like it, and the audit must
    # name all six for a router that counts them again.
    _, data, findings = game
    assert not any(key[0] == 'seam' for key in findings)
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    every = tool.check_seams(data, Regions(data), Navigator(data), names, walk=False)
    assert set(every) == SEAMS


def walker(data):
    """A walk between two maps by name, with the field moves given, as the names of the maps it enters."""
    ids = {entry['constant']: mid for mid, entry in data.maps.items()}
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    navigator = Navigator(data)

    def walk(start, target, *moves):
        route = navigator.walk(tool.player(ids[start], moves), ids[target])
        return None if route is None else [names[step[1]] for step in route]
    return walk


def test_a_walk_goes_through_the_cave_or_forest_between_two_seam_maps(game):
    _, data, _ = game
    walk = walker(data)
    assert walk('ROUTE_44', 'BLACKTHORN_CITY') == ['ICE_PATH_1F', 'BLACKTHORN_CITY']
    assert walk('ROUTE_10_NORTH', 'ROUTE_10_SOUTH') == ['ROUTE_9', 'ROCK_TUNNEL_1F', 'ROUTE_10_SOUTH']
    assert walk('AZALEA_TOWN', 'ROUTE_34', 'cut') == [
        'ILEX_FOREST_AZALEA_GATE', 'ILEX_FOREST', 'ROUTE_34_ILEX_FOREST_GATE', 'ROUTE_34']
    assert walk('ROUTE_34', 'GOLDENROD_CITY') == ['GOLDENROD_CITY']


def test_a_walk_through_ilex_forest_needs_cut(game):
    # The tree in Ilex Forest splits its two gates, so before Cut the walk from Azalea Town to
    # Route 34 is not the four maps through the forest.
    _, data, findings = game
    assert not any(key[0] == 'crossing' for key in findings)
    ids = {entry['constant']: mid for mid, entry in data.maps.items()}
    forest = (ids['ILEX_FOREST_AZALEA_GATE'], ids['ILEX_FOREST'], ids['ROUTE_34_ILEX_FOREST_GATE'])
    assert walk_crossings(data)[forest] == (frozenset({'cut'}),)
    assert walk_crossings(data)[forest[::-1]] == (frozenset({'cut'}),)
    walk = walker(data)
    for moves in ((), ('surf',)):
        route = walk('AZALEA_TOWN', 'ROUTE_34', *moves)
        assert route is not None and 'ILEX_FOREST' not in route and len(route) > 4
        assert 'ILEX_FOREST' not in walk('ROUTE_34', 'AZALEA_TOWN', *moves)
    assert walk('ROUTE_34', 'AZALEA_TOWN', 'cut') == [
        'ROUTE_34_ILEX_FOREST_GATE', 'ILEX_FOREST', 'ILEX_FOREST_AZALEA_GATE', 'AZALEA_TOWN']


def test_a_walk_over_a_gate_link_lands_at_the_gate(game):
    # Ecruteak City meets Route 42 only through its gate, whose door opens west of the water. A walk
    # over that link once landed nowhere, so it reached Mahogany Town in two maps before Surf.
    _, data, _ = game
    ids = {entry['constant']: mid for mid, entry in data.maps.items()}
    needs = walk_crossings(data)
    for crossing, move in ((('ECRUTEAK_CITY', 'ROUTE_42', 'MAHOGANY_TOWN'), 'surf'),
                           (('GOLDENROD_CITY', 'ROUTE_35', 'ROUTE_36'), 'cut')):
        key = tuple(ids[name] for name in crossing)
        assert needs[key] == needs[key[::-1]] == (frozenset({move}),)
    walk = walker(data)
    assert walk('ECRUTEAK_CITY', 'MAHOGANY_TOWN') == ['ROUTE_42', 'MOUNT_MORTAR_1F_OUTSIDE', 'ROUTE_42', 'MAHOGANY_TOWN']
    assert walk('ECRUTEAK_CITY', 'MAHOGANY_TOWN', 'surf') == ['ROUTE_42', 'MAHOGANY_TOWN']
    assert 'NATIONAL_PARK' in walk('GOLDENROD_CITY', 'ROUTE_36')
    assert walk('GOLDENROD_CITY', 'ROUTE_36', 'cut') == ['ROUTE_35', 'ROUTE_36']


class FieldMovesIgnored(Navigator):
    """A navigator that walks as if the player had every field move, as walks did before they read them."""
    def walk(self, snapshot, target):
        return super().walk(tool.player(snapshot.map, ('cut', 'surf')), target)


def test_a_walk_that_ignores_field_moves_fails_the_crossing_check(game):
    _, data, _ = game
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    found = tool.check_crossings(data, FieldMovesIgnored(data), names)
    forest = ('crossing', 'ILEX_FOREST_AZALEA_GATE', 'ILEX_FOREST', 'ROUTE_34_ILEX_FOREST_GATE')
    assert forest + ('no moves',) in found
    assert forest + ('surf',) in found
    assert not any(key[-1] == 'cut+surf' for key in found)


class CarpetDoors:
    """The game data with a warp on every carpet that has none, which is how routes read carpets before #244."""
    def __init__(self, data):
        self.data = data
        self.maps = {}
        for mid, entry in data.maps.items():
            width = entry['width']
            doors = {(warp['x'], warp['y']) for warp in entry['warps']}
            extra = [{'x': index % width, 'y': index // width, 'map': mid, 'warp': 1}
                     for index, tile in enumerate(entry['collision'])
                     if tile in CARPETS and (index % width, index // width) not in doors]
            self.maps[mid] = {**entry, 'warps': entry['warps'] + extra}

    def __getattr__(self, name):
        return getattr(self.data, name)


def test_a_carpet_read_as_a_door_cuts_off_the_olivine_port_pier(game):
    # The gangway carpet at (7, 17) has no warp. Read as a door, it split the pier from the gangway,
    # so boarding the S.S. Aqua walked back and forth at the port entrance (#241).
    _, data, findings = game
    assert not any(key[0] == 'carpet' for key in findings)
    view = CarpetDoors(data)
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}
    before = tool.check_carpets(data, Regions(view), Navigator(view), names)
    assert ('carpet', 'OLIVINE_PORT', 7, 17, 'walled in') in before


# Check E runs the whole story, so a run past this many seconds fails, as it would slow every push.
STORY_SECONDS = 60


def gen1_tool(variant='red'):
    """Skip unless the Gen I data of ``variant`` is prepared."""
    try:
        game_data.bundle_path(variant=variant)
    except RuntimeError:
        pytest.skip(f'{variant.title()} game data is not prepared')


def timed_story_check(*args, check=None, **kwargs):
    import time
    start = time.perf_counter()
    found = (check or tool.check_story_gen1)(*args, **kwargs)
    seconds = time.perf_counter() - start
    assert seconds < STORY_SECONDS, f'check E took {seconds:.0f} s'
    return found


def test_every_gen2_story_step_is_offered_and_reachable_in_turn(game):
    name, data, _ = game
    assert timed_story_check(data, check=tool.check_story_gen2) == {}, name


def test_a_gen2_story_row_the_manifest_drops_is_not_offered_in_turn(game):
    name, data, _ = game
    rows = story.steps(2, name)
    keys = [row['key'] for row in rows]
    skipped = keys.index('officer')
    after = rows[skipped + 1]
    found = timed_story_check(data, rows=rows[:skipped] + rows[skipped + 1:], check=tool.check_story_gen2)
    assert found == {('story', after['key'], tool.where(after), 'not offered'): 'the story offers officer here'}


def test_switches_that_open_no_doors_cut_off_the_radio_tower_director(game):
    # Each underground switch opens and shuts its own set of shutters, so a manifest that forgets
    # the doors a switch moves leaves the director behind closed shutters.
    name, data, _ = game
    rows = [dict(row) for row in story.steps(2, name)]
    for row in rows:
        if row['key'].startswith('switch_'):
            row['done_when'] = {'flags': [flag for flag in row['done_when']['flags'] if 'DOOR' not in flag]}
    found = timed_story_check(data, rows=rows, check=tool.check_story_gen2)
    key = ('story', 'card_key', 'GoldenrodUndergroundWarehouseDirectorScript', 'no route')
    assert found[key] == 'no route from GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES (16, 2)'


def test_a_fly_map_blind_to_regions_flies_from_route_23_into_johto(game):
    # The cartridge's Fly map lists only the region the player stands in, so a run stuck on Route 23
    # must walk back into Johto before it can fly to Olivine (#124).
    _, data, _ = game
    names = {mid: entry['constant'] for mid, entry in data.maps.items()}

    def blind(data, mid, visited):
        return list(enumerate(data.fly_points))

    found = tool.check_flight(data, names, blind)
    assert found[('fly', 'ROUTE_23', 'OLIVINE_CITY', 'crosses regions')] == (
        'the Fly map on ROUTE_23 shows Kanto, not OLIVINE_CITY')
    assert tool.check_flight(data, names) == {}


def test_each_starter_row_is_offered_by_a_policy_that_chose_it(game):
    name, _, _ = game
    starters = story.rows(2, name, 'starter')
    assert [row['starter'] for row in starters] == list(tool.GEN2_STARTERS)
    assert {row['done_when']['party'] for row in starters} == {True}


def test_every_gen1_story_step_is_offered_and_reachable_in_turn():
    gen1_tool()
    assert timed_story_check() == {}


def test_every_yellow_story_step_is_offered_and_reachable_in_turn():
    gen1_tool('yellow')
    env = dict(os.environ, **{game_data.VARIANT_ENV: 'yellow'})
    script = textwrap.dedent(f'''
        import importlib.util, time
        spec = importlib.util.spec_from_file_location('map_audit_tool', {str(ROOT / 'tools' / 'map_audit.py')!r})
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        from pokesim.policies.progression import GAME
        start = time.perf_counter()
        found = tool.check_story_gen1()
        print(GAME, len(found), round(time.perf_counter() - start), sorted(map(str, found)))
    ''')
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr[-3000:]
    game, count, seconds, *rest = result.stdout.split(maxsplit=3)
    assert (game, count) == ('yellow', '0'), result.stdout
    assert int(seconds) < STORY_SECONDS


def test_a_lift_that_always_goes_to_b1f_cuts_off_mr_fuji():
    # The Rocket Hideout lift once always left for B1F, whatever floor the player picked, so the
    # walk to the Silph Scope never reached B4F and the run looped in the lift (#268).
    gen1_tool()
    from pokesim.policies.navigation import Navigator

    class LiftToB1F(Navigator):
        def hideout_lift_floor(self):
            return 'B1F'

    found = timed_story_check(LiftToB1F)
    assert found[('story', 'fuji', 'MR_FUJI', 'no route')] == 'no route from ROCKET_HIDEOUT_B4F (24, 2)'


def test_a_story_row_the_manifest_drops_is_not_offered_in_turn():
    gen1_tool()
    from pokesim.policies.progression import GAME
    rows = story.steps(1, GAME)
    skipped, after = rows[1], rows[2]
    found = timed_story_check(rows=rows[:1] + rows[2:])
    first = next(iter(found))
    assert first == ('story', after['key'], tool.where(after), 'not offered')
    assert found[first] == f"the story offers {skipped['key']} here"


def test_each_cinnabar_gym_door_row_names_its_gate_and_its_trainer():
    gen1_tool()
    from pokesim.policies.navigation import CINNABAR_GYM_DOORS
    from pokesim.policies.progression import GAME
    doors = [row for row in story.rows(1, GAME, 'volcano') if not row.get('gym')]
    assert len(doors) == len(CINNABAR_GYM_DOORS)
    for number, (row, (gate, _)) in enumerate(zip(doors, CINNABAR_GYM_DOORS), 1):
        assert row['done_when']['flags'] == [gate.flag] == [f'EVENT_CINNABAR_GYM_GATE{number}_UNLOCKED']
        assert row['map'] == 'CINNABAR_GYM' and row['object'] == f'SUPER_NERD{number + 1}'
