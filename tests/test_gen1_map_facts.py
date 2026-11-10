"""The Gen I map facts are generated from the disassembly, and they open and shut the same blocks as before."""
import importlib.util
import itertools
from pathlib import Path

import pytest

from pokesim.data_tools.strategy import opened_blocks
from pokesim.game_data import SOURCE_REVISION, YELLOW_REVISION
from pokesim.mapfacts import gen1
from pokesim.policies.navigation import HIDEOUT_DOOR, HIDEOUT_DOOR_FLAG, Navigator
from pokesim.policies.travel import TravelNavigator
from pokesim.strategy_data import MAPS, WORLD
from test_events import snap
from test_gen1_gates import checkout
from test_strategy import flags

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'pokesim' / 'mapfacts' / 'gen1.py'
_spec = importlib.util.spec_from_file_location('gen1_map_facts_tool', ROOT / 'tools' / 'gen1_map_facts.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)
SOURCES = [('pokered', 'POKERED_SOURCE', SOURCE_REVISION), ('pokeyellow', 'POKEYELLOW_SOURCE', YELLOW_REVISION)]

# The blocks data_tools/strategy.py opened by hand before the facts, keyed by map constant.
FORMER_OPENED = {
    'LORELEIS_ROOM': [(2, 0, 0x05, 'EVENT_BEAT_LORELEIS_ROOM_TRAINER_0')],
    'BRUNOS_ROOM': [(2, 0, 0x05, 'EVENT_BEAT_BRUNOS_ROOM_TRAINER_0')],
    'AGATHAS_ROOM': [(2, 0, 0x0E, 'EVENT_BEAT_AGATHAS_ROOM_TRAINER_0')],
    'VICTORY_ROAD_1F': [(4, 6, 0x1D, 'EVENT_VICTORY_ROAD_1_BOULDER_ON_SWITCH')],
    'VICTORY_ROAD_2F': [(3, 4, 0x15, 'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1'),
                        (11, 7, 0x1D, 'EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2')],
    'VICTORY_ROAD_3F': [(3, 5, 0x1D, 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1')],
}
# The Rocket Hideout B1F door tiles navigation shut by hand before the facts (#264).
FORMER_DOOR_FLAG = 'EVENT_BEAT_ROCKET_HIDEOUT_1_TRAINER_4'
FORMER_DOOR = {(MAPS['ROCKET_HIDEOUT_B1F'], x, y) for x in (24, 25) for y in (16, 17)}


def pinned(name, env, revision):
    src = checkout(name, env)
    if src is None:
        pytest.skip(f'no {name} checkout, set {env} or fill .reference/{name}')
    if tool.source(src)[1] != revision:
        pytest.skip(f'{name} checkout is not at the pinned commit')
    return src


def test_the_facts_name_the_commit_they_came_from():
    assert f'pret/pokered {SOURCE_REVISION}' in TABLE.read_text(encoding='utf-8').splitlines()[0]
    assert 'not written by hand' in gen1.__doc__
    assert all(name in MAPS for name, *_ in gen1.SWAPS)


def test_the_facts_open_the_blocks_strategy_opened_by_hand():
    assert {name: opened_blocks(name) for name in MAPS if opened_blocks(name)} == FORMER_OPENED


def test_navigation_shuts_the_hideout_door_it_shut_by_hand():
    assert HIDEOUT_DOOR_FLAG == FORMER_DOOR_FLAG
    assert set(HIDEOUT_DOOR) == FORMER_DOOR and HIDEOUT_DOOR[0] == (MAPS['ROCKET_HIDEOUT_B1F'], 24, 16)
    nav = Navigator()
    others = ('EVENT_BEAT_ROCKET_HIDEOUT_1_TRAINER_0', 'EVENT_ENTERED_ROCKET_HIDEOUT')
    for beaten, other in itertools.product((False, True), (None, *others)):
        names = [name for name in (FORMER_DOOR_FLAG if beaten else None, other) if name]
        nav.update_story(snap(map=MAPS['ROCKET_HIDEOUT_B1F'], event_flags=flags(*names)))
        assert (FORMER_DOOR <= nav.story_blocks) == (not beaten)
        assert not beaten or not FORMER_DOOR & nav.story_blocks


@pytest.mark.parametrize('navigator', [Navigator, TravelNavigator])
@pytest.mark.parametrize('room', ['LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM'])
def test_an_elite_four_exit_is_shut_until_the_trainer_is_beaten(room, navigator):
    # Lorelei's map file draws her exit shut. Bruno's and Agatha's draw theirs open, and the scripts shut them.
    world, flag = WORLD[MAPS[room]], f'EVENT_BEAT_{room}_TRAINER_0'
    exits = [(4, 0), (5, 0)]
    assert set(exits) <= {(x, y) for x, y, *_ in world['warps']}
    nav = navigator()
    for beaten in (False, True):
        nav.update_story(snap(map=MAPS[room], event_flags=flags(*[flag][:beaten])))
        assert [nav.active_tile(world, x, y) in world['passable'] for x, y in exits] == [beaten, beaten]


@pytest.mark.parametrize('name, env, revision', SOURCES)
def test_the_facts_are_what_the_tool_generates_from_the_pinned_source(name, env, revision):
    src = pinned(name, env, revision)
    table = TABLE.read_text(encoding='utf-8')
    # Red and Yellow agree on every swap, so both give the same facts under the header.
    assert table.endswith(tool.body(src)), 'regenerate pokesim/mapfacts/gen1.py with tools/gen1_map_facts.py'
    if name == 'pokered':
        assert table == tool.render(src)


@pytest.mark.parametrize('name, env, revision', SOURCES)
def test_every_swap_on_a_flag_is_a_fact_or_allowed(name, env, revision):
    src = pinned(name, env, revision)
    assert tool.uncovered(src, gen1.SWAPS) == []


def test_the_check_names_the_hideout_door_without_its_fact():
    src = pinned(*SOURCES[0])
    rows = tuple(row for row in gen1.SWAPS if row[0] != 'ROCKET_HIDEOUT_B1F')
    assert tool.uncovered(src, rows) == ['ROCKET_HIDEOUT_B1F block (12, 8) swaps on a flag and has no fact']
