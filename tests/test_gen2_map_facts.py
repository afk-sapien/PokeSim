"""The Gen II map facts are generated from the disassemblies, and they swap the same blocks as before."""
import importlib.util
import itertools
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokecore.gen2 import mapfacts, maps
from pokesim.gen2 import routes
from pokesim.gen2.data import SOURCES as PINS

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / 'packages' / 'pokecore' / 'src' / 'pokecore' / 'gen2' / 'mapfacts.py'
_spec = importlib.util.spec_from_file_location('gen2_map_facts_tool', ROOT / 'tools' / 'gen2_map_facts.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)
SOURCES = [('pokecrystal', 'POKECRYSTAL_SOURCE', PINS['crystal'][1]),
           ('pokegold', 'POKEGOLD_SOURCE', PINS['gold'][1])]

# The tables pokecore.gen2.maps held by hand before the facts: flag, map and the blocks set while the flag is.
FORMER_CHANGES = (
    ('EVENT_LANCES_ROOM_ENTRANCE_CLOSED', 'LANCES_ROOM', ((4, 22, 0x34),)),
    ('EVENT_LANCES_ROOM_EXIT_OPEN', 'LANCES_ROOM', ((4, 0, 0x0B),)),
    ('EVENT_USED_BASEMENT_KEY', 'GOLDENROD_UNDERGROUND', ((18, 6, 0x2E),)),
    ('EVENT_USED_THE_CARD_KEY_IN_THE_RADIO_TOWER', 'RADIO_TOWER_3F', ((14, 2, 0x2A), (14, 4, 1))),
    ('EVENT_UNCOVERED_STAIRCASE_IN_MAHOGANY_MART', 'MAHOGANY_MART_1F', ((6, 2, 0x1E),)),
    ('EVENT_OPENED_DOOR_TO_GIOVANNIS_OFFICE', 'TEAM_ROCKET_BASE_B3F', ((10, 8, 7),)),
    ('EVENT_OPENED_DOOR_TO_ROCKET_HIDEOUT_TRANSMITTER', 'TEAM_ROCKET_BASE_B2F', ((14, 12, 7),)),
    ('EVENT_RECEIVED_CARD_KEY', 'GOLDENROD_DEPT_STORE_B1F', ((16, 4, 0x0D),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_1', 'BLACKTHORN_GYM_1F', ((8, 2, 0x3B),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_2', 'BLACKTHORN_GYM_1F', ((2, 4, 0x3A),)),
    ('EVENT_BOULDER_IN_BLACKTHORN_GYM_3', 'BLACKTHORN_GYM_1F', ((8, 6, 0x3B),)),
)
FORMER_DOORS = (
    ((16, 6, 0x2D),), ((10, 6, 0x2D),), ((2, 6, 0x2D),),
    ((2, 10, 0x2D),), ((10, 10, 0x2D),), ((16, 10, 0x2D),),
    ((12, 6, 0x2A), (12, 8, 0x2D)), ((6, 6, 0x2A), (6, 8, 0x2D)),
    ((12, 10, 0x2A), (12, 12, 0x2D)), ((6, 10, 0x2A), (6, 12, 0x2D)),
    ((18, 10, 0x2A), (18, 12, 0x2D)),
)
FORMER_LEAGUE = tuple((f'EVENT_{name}_ROOM_{event}', f'{name}_ROOM', ((4, y, block),))
                      for name in ('WILLS', 'KOGAS', 'BRUNOS', 'KARENS')
                      for event, y, block in [('ENTRANCE_CLOSED', 14, 0x2A), ('EXIT_OPEN', 2, 0x16)])
FORMER = FORMER_CHANGES + FORMER_LEAGUE + tuple(
    (f'EVENT_DOOR_{i}_OPEN', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', blocks)
    for i, blocks in enumerate(FORMER_DOORS, 1))
FORMER_CARPETS = {0x70: 'down', 0x76: 'left', 0x78: 'up', 0x7E: 'right'}
# The basement door. The hand table set block 0x2E with the key, which the map file already draws, so the
# door read as open before the key. The callback draws the wall block 0x3D until the key is used.
BASEMENT = ('GOLDENROD_UNDERGROUND', 18, 6, 'EVENT_USED_BASEMENT_KEY')


def former_changes(data, snapshot, live=None):
    """event_changes as it was before the facts, for the swapped maps only."""
    live = live or {}
    edits = {}
    for event, name, blocks in FORMER:
        if event not in data.events:
            continue
        mid = data.map_ids[name]
        if mid == snapshot.map:
            continue
        entry = data.maps[mid]
        grid = edits.setdefault(mid, list(live.get(mid, entry['collision'])))
        opened = snapshot.event(event)
        for x, y, block in blocks:
            for dy in range(2):
                for dx in range(2):
                    offset = (y + dy) * entry['width'] + x + dx
                    grid[offset] = entry['block_collision'][block][dy * 2 + dx] if opened else entry['collision'][offset]
    return edits


def pinned(name, env, revision):
    src = Path(os.environ.get(env) or ROOT / '.reference' / name)
    if not (src / 'maps').is_dir():
        pytest.skip(f'no {name} checkout, set {env} or fill .reference/{name}')
    if tool.source(src) != (name, revision):
        pytest.skip(f'{name} checkout is not at the pinned commit')
    return src


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_the_facts_name_the_commits_they_came_from():
    header = TABLE.read_text(encoding='utf-8').split('\n\n', 1)[0]
    assert f'pret/pokecrystal {PINS["crystal"][1]}' in header
    assert f'pret/pokegold {PINS["gold"][1]}' in header
    assert 'not written by hand' in mapfacts.__doc__


def test_the_facts_hold_every_former_row_and_fix_the_basement_door():
    former = {(name, x, y, event, block, None) for event, name, blocks in FORMER for x, y, block in blocks}
    former.remove((*BASEMENT, 0x2E, None))
    former.add((*BASEMENT, None, 0x3D))
    assert len(mapfacts.SWAPS) == len(former)
    assert set(mapfacts.SWAPS) == former


def test_the_carpets_come_from_the_facts():
    assert mapfacts.CARPETS == FORMER_CARPETS
    assert routes.CARPETS is mapfacts.CARPETS


def test_unloaded_maps_change_as_before_except_the_basement_door(data):
    events = sorted({event for _, _, _, event, *_ in mapfacts.SWAPS if event in data.events})
    away = data.map_ids['NEW_BARK_TOWN']
    basement = data.maps[data.map_ids['GOLDENROD_UNDERGROUND']]
    door = [(6 + dy) * basement['width'] + 18 + dx for dy in range(2) for dx in range(2)]
    states = [set(), set(events), *({event} for event in events), *(set(events) - {event} for event in events)]
    lives = [None, {mid: [0xFF] * len(data.maps[mid]['collision']) for mid in data.maps}]
    for on, live in itertools.product(states, lives):
        snapshot = SimpleNamespace(map=away, items=(), event=on.__contains__)
        new, old = maps.event_changes(data, snapshot, live), former_changes(data, snapshot, live)
        assert set(old) <= set(new)
        for mid, grid in old.items():
            if mid != data.map_ids['GOLDENROD_UNDERGROUND'] or 'EVENT_USED_BASEMENT_KEY' in on:
                assert new[mid] == grid, (data.maps[mid]['constant'], sorted(on))
                continue
            changed = [i for i, (a, b) in enumerate(zip(new[mid], grid)) if a != b]
            assert set(changed) <= set(door)
            assert [grid[i] for i in door] == [basement['collision'][i] for i in door]
            assert [new[mid][i] for i in door] == basement['block_collision'][0x3D]


def test_the_basement_door_is_a_wall_until_the_key_is_used(data):
    mid = data.map_ids['GOLDENROD_UNDERGROUND']
    entry = data.maps[mid]
    door = [(6 + dy) * entry['width'] + 18 + dx for dy in range(2) for dx in range(2)]
    for used in (False, True):
        snapshot = SimpleNamespace(map=data.map_ids['NEW_BARK_TOWN'], items=(),
                                   event=lambda name, used=used: used and name == 'EVENT_USED_BASEMENT_KEY')
        tile = maps.event_changes(data, snapshot)[mid][door[0]]
        assert maps.passable(data, tile) == used, hex(tile)


def test_the_loaded_map_is_left_to_its_live_blocks(data):
    mid = data.map_ids['LANCES_ROOM']
    snapshot = SimpleNamespace(map=mid, items=(), event=lambda name: True)
    assert mid not in maps.event_changes(data, snapshot)


@pytest.mark.parametrize('name, env, revision', SOURCES)
def test_the_facts_are_what_the_tool_generates_from_the_pinned_source(name, env, revision):
    src = pinned(name, env, revision)
    table = TABLE.read_text(encoding='utf-8')
    assert table.endswith(tool.body(src)), 'regenerate pokecore/gen2/mapfacts.py with tools/gen2_map_facts.py'


def test_the_facts_are_the_whole_generated_file():
    crystal, gold = (pinned(*source) for source in SOURCES)
    assert TABLE.read_text(encoding='utf-8') == tool.render(crystal, gold)


@pytest.mark.parametrize('name, env, revision', SOURCES)
def test_every_swap_on_a_flag_is_a_fact_or_allowed(name, env, revision):
    src = pinned(name, env, revision)
    assert tool.uncovered(src, mapfacts.SWAPS) == []


def test_the_check_names_a_swap_without_its_fact():
    src = pinned(*SOURCES[0])
    rows = tuple(row for row in mapfacts.SWAPS if row[0] != 'MAHOGANY_MART_1F')
    assert tool.uncovered(src, rows) == ['MAHOGANY_MART_1F block (6, 2) swaps on a flag and has no fact']


def test_every_allowed_swap_has_a_reason():
    for key, reason in tool.ALLOWED.items():
        assert isinstance(key, str) or len(key) == 3, key
        assert reason.strip().endswith('.'), key
    assert tool.CRYSTAL_ONLY <= {key if isinstance(key, str) else key[0] for key in tool.ALLOWED}
