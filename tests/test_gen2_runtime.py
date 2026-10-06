"""Generation-specific contracts and optional real-cartridge regression checks."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pokesim.cartridges import by_version, validate_starter, unpack
from pokesim.gen2.data import GameData, constants, number
from pokesim.gen2.navigation import Navigator, blocked_side
from pokesim.gen2.ram import calculated_stats, experience_at, experience_progress
from pokesim.gen2.sprites import decompress, portrait
from pokesim.gen2.web import Reference


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_cartridge_starters_are_generation_specific(version):
    assert by_version(version).generation == 2
    for starter in ('random', 'chikorita', 'cyndaquil', 'totodile'):
        validate_starter(starter, version)
    with pytest.raises(ValueError):
        validate_starter('squirtle', version)
    with pytest.raises(ValueError):
        validate_starter('totodile', 'red')


def test_constant_parser_accounts_for_item_holes_and_hm_aliases(tmp_path):
    source = tmp_path / 'constants.asm'
    source.write_text('const_def $bf\nadd_tm DYNAMICPUNCH\nconst ITEM_C0\nadd_tm HEADBUTT\nadd_hm CUT\n')
    result = constants(source)
    assert result['TM01'] == result['TM_DYNAMICPUNCH'] == 191
    assert result['TM02'] == 193
    assert result['HM01'] == result['HM_CUT'] == 194


def test_integer_expression_parser_rejects_code():
    assert number('$10 | %11') == 19
    with pytest.raises(ValueError):
        number('__import__("os").system("exit")')


@pytest.mark.parametrize('growth,total', [('FAST', 800000), ('MEDIUM_FAST', 1000000),
                                          ('MEDIUM_SLOW', 1059860), ('SLOW', 1250000)])
def test_experience_curves(growth, total):
    assert experience_at(100, growth) == total
    assert experience_progress(total, 100, growth)['percent'] == 100
    assert experience_progress(total, 100, growth)['remaining'] == 0


def test_generation_two_special_stats_share_dv_and_training():
    stats = calculated_stats([100, 100, 100, 100, 120, 80], 100, (15,) * 5, (65535,) * 5)
    assert stats == (403, 298, 298, 298, 338, 258)


@pytest.mark.parametrize('tile,side', [(0xB0, 'right'), (0xB1, 'left'), (0xB2, 'up'), (0xB3, 'down')])
def test_directional_walls_block_the_declared_side(tile, side):
    assert blocked_side(tile, side)
    assert not blocked_side(0, side)


def test_sprite_decompressor_literals_runs_and_relative_copy():
    assert decompress(bytes([2, 1, 2, 3, 0x82, 0x82, 255]), 0) == bytes([1, 2, 3, 1, 2, 3])
    assert decompress(bytes([0x23, 42, 255]), 0) == bytes([42] * 4)
    with pytest.raises(ValueError):
        decompress(bytes([0x82, 0x80, 255]), 0)


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def test_real_reference_has_all_species_correct_types_and_versioned_encounters(real_data):
    data = real_data
    assert len(data.species) == len(data.moves) == 251
    assert data.type_names[9] == 'Steel'
    assert data.type_names[27] == 'Dark'
    assert data.species[208]['front_symbol'] == 'SteelixFrontpic'
    assert data.items['HM_CUT'] == data.items['HM01']
    reference = json.loads(Reference(data).json(data.game))
    assert reference['count'] == 251
    assert reference['entries'][154]['hms'] == ['Cut']
    assert reference['entries'][18]['locations']
    assert data.matchups[(data.types['DARK'], data.types['PSYCHIC_TYPE'])] == 2


def test_all_cartridge_portraits_decode(real_data):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    raw = (Path(directory) / (real_data.game + '.gbc')).read_bytes()
    assert unpack(raw) == raw
    for dex in range(1, 252):
        image = Image.open(io.BytesIO(portrait(raw, real_data, dex)))
        assert image.size == (56, 56)
        assert image.getbbox() is not None


def test_item_menu_matches_cut_without_spending_fury_cutter():
    from pokesim.gen2.menus import choose
    rows = (' 49▶FURY CUTTER   ', ' H1 CUT           ')
    assert choose(rows, 'CUT', exact=True) == 'down'


def test_routes_can_reenter_a_map_through_a_different_component():
    from types import SimpleNamespace
    from pokesim.gen2.routes import Regions
    maps = {
        1: {'width': 5, 'height': 3, 'collision': [0, 0, 7, 0, 0, 0, 0x72, 7, 0x72, 0, 0, 0, 7, 0, 0],
            'connections': [], 'objects': [], 'warps': [{'x': 1, 'y': 1, 'map': 2, 'warp': 1},
                                         {'x': 3, 'y': 1, 'map': 2, 'warp': 2}]},
        2: {'width': 3, 'height': 3, 'collision': [0, 0, 0, 0x72, 0, 0x72, 0, 0, 0],
            'connections': [], 'objects': [], 'warps': [{'x': 0, 'y': 1, 'map': 1, 'warp': 1},
                                         {'x': 2, 'y': 1, 'map': 1, 'warp': 2}]},
    }
    permissions = [0] * 256
    permissions[7] = 15
    routes = Regions(SimpleNamespace(maps=maps, permissions=permissions))
    result = routes.route(SimpleNamespace(map=1, x=0, y=1), 1, [(4, 1)])
    assert [edge[1][0] for edge in result] == [2, 1]
    assert result[-1][1][1] != result[0][0][1]


def test_battle_selects_an_available_move_after_disable(real_data):
    from types import SimpleNamespace
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    mon = SimpleNamespace(species=156, egg=False, moves=(15, 43, 108, 52), pp=(30, 30, 20, 20), stats=(90, 60, 50, 70, 70, 60))
    snapshot = SimpleNamespace(text='Disabled!', tiles=('Disabled!',), party=[mon], in_battle=2,
                               enemy_species=39, badges=0, owned=set(), can_catch=True, pockets={'balls': []})
    values = {'wCurBattleMon': 0, 'wMenuCursorY': 4, 'wPlayerDisableCount': 72, 'wDisabledMove': 52}
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: values.get(name, 0))).button == 'up'


def test_level_up_replacement_preserves_hm_moves(real_data):
    from types import SimpleNamespace
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    mon = SimpleNamespace(species=156, egg=False, moves=(15, 43, 108, 52), pp=(30, 30, 20, 20), stats=(90, 60, 50, 70, 70, 60))
    snapshot = SimpleNamespace(text='Which move should be forgotten?\n▶CUT\nLEER\nSMOKESCREEN\nEMBER',
                               tiles=(), party=[mon], in_battle=2, enemy_species=39, badges=0, owned=set(),
                               can_catch=True, pockets={'balls': []})
    values = {'wCurBattleMon': 0, 'wMenuCursorY': 1}
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: values.get(name, 0))).button == 'down'


def test_hm_pack_label_ignores_decorative_tiles():
    from pokesim.gen2.menus import choose
    rows = ('ヂヅデド H4 STRENGTH    ', '       ▶CANCEL      ')
    assert choose(rows, 'STRENGTH', exact=True) == 'up'


def test_teaching_uses_visible_party_selection_and_advances_learning_text():
    from pokesim.gen2.menus import Teach
    rows = [''] * 18
    rows[1], rows[2] = '   CROCONAW', 'Lv26 ABLE'
    rows[3], rows[4] = '▶  TOGEPI', 'Lv5 NOT ABLE'
    rows[13] = ' CANCEL'
    job = Teach(15, 0, 'confirm')
    mem = SimpleNamespace(byte=lambda name: 15 if name == 'wPutativeTMHMMove' else 0)
    snapshot = SimpleNamespace(tiles=rows, text='\n'.join(rows), party=[SimpleNamespace(moves=(10, 43, 55, 44))])
    assert job.step(snapshot, mem) == 'up'
    rows[3], rows[1], rows[16] = '   TOGEPI', '▷  CROCONAW', '1, 2 and… Poof!'
    snapshot.text = '\n'.join(rows)
    job.phase = 'learn'
    assert job.step(snapshot, mem) == 'a'
    assert job.phase == 'learn'


def test_policy_checkpoint_retains_active_menu(real_data):
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.menus import Teach
    policy = Policy(real_data, starter='totodile')
    policy.menu = Teach(70, 0, 'learn', 23)
    policy.learning = True
    policy.interaction = (263, 4, 3)
    restored = Policy(real_data, starter='cyndaquil')
    restored.load_state_dict(json.loads(json.dumps(policy.state_dict())))
    restored.on_restore()
    assert restored.menu == policy.menu
    assert restored.interaction == policy.interaction
    assert restored.learning


def test_lighthouse_route_does_not_walk_across_a_hole(real_data):
    from pokesim.gen2.routes import Regions
    source = real_data.map_ids['OLIVINE_LIGHTHOUSE_4F']
    target = real_data.map_ids['OLIVINE_LIGHTHOUSE_6F']
    route = Regions(real_data).route(SimpleNamespace(map=source, x=13, y=3), target, [(8, 9)], cut=True, surf=True)
    assert route
    assert len(route) >= 4
    assert route[-1][1][0] == target


def test_strength_plan_can_move_a_blocking_stone():
    from pokesim.gen2.puzzles import push_plan
    grid = [7] * 35
    for y in range(1, 4):
        for x in range(1, 6):
            grid[y * 7 + x] = 0
    grid[2 * 7 + 5] = 0x60
    permissions = [0] * 256
    permissions[7] = 15
    plan = push_plan(grid, 7, 5, permissions, (1, 2), [(3, 2), (4, 2)], 0, (5, 2))
    assert plan
    positions = [(3, 2), (4, 2)]
    directions = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
    moved_blocker = False
    for stand, direction in plan:
        dx, dy = directions[direction]
        stone = (stand[0] + dx, stand[1] + dy)
        index = positions.index(stone)
        moved_blocker |= index == 1
        positions[index] = (stone[0] + dx, stone[1] + dy)
    assert moved_blocker
    assert positions[0] == (5, 2)


def test_fishing_and_tree_encounters_are_versioned_reference_data(real_data):
    methods = {row['method'] for row in real_data.encounters}
    assert {'old rod', 'good rod', 'super rod', 'headbutt', 'rock smash'} <= methods
    olivine = real_data.map_ids['OLIVINE_CITY']
    assert any(row['map'] == olivine and row['species'] == 98 and row['method'] == 'good rod'
               for row in real_data.encounters)


def test_menu_labels_ignore_background_beside_dialogue_and_pack():
    from pokesim.gen2.menus import choose
    assert choose(('  ザザザ│▶Weak person │', 'ぷザザ  │ Anybody     │'), 'Anybody', exact=True) == 'down'
    assert choose(('グギガゲゴ   FULL RESTORE', '       ▶CANCEL'), 'FULL RESTORE', exact=True) == 'up'


def test_machine_search_scrolls_back_from_hms_to_an_earlier_tm(real_data):
    from pokesim.gen2.menus import Teach
    rows = ('     H3 SURF', '     H7 WATERFALL', '       ▶CANCEL')
    snapshot = SimpleNamespace(tiles=rows, text='\n'.join(rows), data=real_data,
                               party=[SimpleNamespace(moves=(15, 70, 76, 34))])
    job = Teach(231, 0, phase='pack')
    assert job.step(snapshot, SimpleNamespace(byte=lambda name: 3)) == 'up'


def test_kanto_objectives_use_scripts_available_in_every_version(real_data):
    from pathlib import Path
    import re
    from pokesim.gen2 import kanto
    text = Path(kanto.__file__).read_text()
    for event in re.findall(r"snapshot.event\('([^']+)'\)", text):
        assert event in real_data.events
    for name, script in re.findall(r"'([A-Z][A-Z_0-9]+)', '([A-Za-z0-9_]+)'\)", text):
        assert name in real_data.map_ids
        assert any(obj['script'] == script for obj in real_data.maps[real_data.map_ids[name]]['objects'])


def test_cave_exit_cannot_teleport_to_the_other_side_of_the_mountain(real_data):
    from pokesim.gen2.routes import Regions
    regions = Regions(real_data)
    route44 = real_data.map_ids['ROUTE_44']
    route = regions.route(SimpleNamespace(map=route44, x=56, y=8), real_data.map_ids['ELMS_LAB'],
                          [(5, 3)], cut=True, surf=True)
    assert route
    assert route[0][1][0] != real_data.map_ids['ICE_PATH_1F']
    memberships = regions.memberships(route44, (56, 7), True, True)
    assert memberships == regions.memberships(route44, (56, 8), True, True)


def test_visible_person_is_not_removed_by_stale_object_fallback():
    data = SimpleNamespace(maps={1: {'width': 3, 'height': 1, 'collision': [0, 0, 0],
                                     'objects': [], 'warps': []}}, permissions=[0] * 256)
    snapshot = SimpleNamespace(map=1, x=0, y=0, badges=0, party=[], objects=[(1, 1, 0)])
    assert Navigator(data).local(snapshot, [(2, 0)]) is None


def test_pokedex_number_is_not_mistaken_for_a_tm_menu(real_data):
    from pokesim.gen2.policy import Policy
    rows = [''] * 18
    rows[8] = '    161'
    rows[3] = 'SENTRET'
    rows[7] = 'HT  2 07'
    policy = Policy(real_data)
    policy.needed_move = lambda snapshot: 57
    snapshot = SimpleNamespace(text='\n'.join(rows), tiles=rows, party=[], in_battle=1,
                               enemy_species=161, owned=set(), can_catch=True,
                               pockets={'balls': [(1, 5)], 'key': []})
    action = policy.battle(snapshot, SimpleNamespace(byte=lambda name: 3))
    assert action.button == 'a'


def test_radio_can_open_when_the_pokegear_icon_is_not_text():
    from pokesim.gen2.menus import Radio
    rows = ('│▶PACK   │', '│   GEAR │', '│ SAVE   │')
    snapshot = SimpleNamespace(text='\n'.join(rows), tiles=rows)
    assert Radio().step(snapshot, None) == 'down'


def test_snorlax_blocks_its_whole_footprint_until_the_battle(real_data):
    from pokesim.gen2.world import travel_collision
    mid = real_data.map_ids['VERMILION_CITY']
    entry = real_data.maps[mid]
    original = list(entry['collision'])
    before = travel_collision(real_data, SimpleNamespace(event=lambda event: False), mid, original)
    for x, y in ((34, 8), (35, 8), (34, 9), (35, 9)):
        assert before[y * entry['width'] + x] == 7
    after = travel_collision(real_data, SimpleNamespace(event=lambda event: True), mid, original)
    assert after == original


@pytest.mark.parametrize('species,item,result', [(64, None, 65), (67, None, 68), (75, None, 76),
    (93, None, 94), (61, 'KINGS_ROCK', 186), (79, 'KINGS_ROCK', 199), (95, 'METAL_COAT', 208),
    (123, 'METAL_COAT', 212), (117, 'DRAGON_SCALE', 230), (137, 'UP_GRADE', 233),
    (64, 'EVERSTONE', 64), (95, None, 95)])
def test_gen2_trade_evolution_requirements(real_data, species, item, result):
    from pokesim.gen2.cable_verification import evolved_species
    assert evolved_species(bytes([species, real_data.items[item] if item else 0]), real_data) == result


def test_battle_transition_graphics_do_not_open_the_pack(real_data):
    from pokesim.gen2.policy import Policy
    rows = [''] * 18
    rows[0] = 'ぐげござじずぜぞだちづでど'
    rows[12] = '┌──────────────────┐'
    policy = Policy(real_data)
    policy.needed_move = lambda snapshot: 57
    snapshot = SimpleNamespace(text='\n'.join(rows), tiles=rows, party=[], in_battle=2,
                               enemy_species=161, owned=set(), can_catch=True,
                               pockets={'balls': [(1, 5)], 'key': []})
    action = policy.battle(snapshot, SimpleNamespace(byte=lambda name: 1))
    assert action.button == 'b' and action.gap >= 48


def test_walk_routes_do_not_treat_the_magnet_train_as_a_door(real_data):
    nav = Navigator(real_data)
    goldenrod = real_data.map_ids['GOLDENROD_MAGNET_TRAIN_STATION']
    saffron = real_data.map_ids['SAFFRON_MAGNET_TRAIN_STATION']
    assert saffron not in {mid for mid, _, _ in nav.edges(goldenrod)}


def test_level_goals_credit_ancestors_without_crediting_siblings(real_data):
    from pokesim.gen2.tracking import level_credit
    assert level_credit(real_data, 157) == {155, 156, 157}
    assert level_credit(real_data, 196) == {133, 196}
    assert 197 not in level_credit(real_data, 196)
    assert level_credit(real_data, 95) == {95}


def test_training_uses_matching_time_for_eevee(real_data):
    from pokesim.gen2.training import projects
    mon = SimpleNamespace(species=133, egg=False, level=20, experience=8000, friendship=220,
                          box=None, trainer_id=1, dvs=(10, 10, 10, 10, 10))
    snapshot = SimpleNamespace(items=[], party=(mon,), stored=(), owned={133})
    assert {row[4] for row in projects(real_data, snapshot, 'day')} == {196}
    assert {row[4] for row in projects(real_data, snapshot, 'night')} == {197}


def test_real_move_and_machine_names_do_not_shift_at_alias_constants(real_data):
    assert real_data.moves[19]['name'] == 'Fly'
    assert real_data.items['HM02'] == real_data.items['HM_FLY'] == 244
    assert real_data.items['TM23'] == real_data.items['TM_IRON_TAIL']
    assert real_data.item_names[real_data.items['EXP_SHARE']].upper() == 'EXP.SHARE'


def test_pack_labels_match_the_cartridge_poke_accent():
    from pokesim.gen2.menus import choose
    assert choose(('▶POKé BALL', ' CANCEL'), 'POKÉ BALL', exact=True) == 'a'


def test_battle_switch_submenu_is_not_the_party_slot_selector(real_data):
    from pokesim.gen2.policy import Policy
    rows = ('▷ MOPTAX', '│ SWITCH│', '│ STATS │', '│▶CANCEL│')
    snapshot = SimpleNamespace(text='\n'.join(rows), tiles=rows, party=[], in_battle=2,
                               enemy_species=161, owned=set(), can_catch=True, pockets={'balls': [], 'key': []})
    policy = Policy(real_data)
    policy.needed_move = lambda snapshot: 57
    policy.switching = 5
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: 1)).button == 'up'


def test_fainted_voluntary_switch_target_is_replanned(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    policy.needed_move = lambda snapshot: 57
    policy.switching = 1
    snapshot = SimpleNamespace(text='There is no will to battle!', tiles=(), party=[], in_battle=2,
                               enemy_species=161, owned=set(), can_catch=True, pockets={'balls': []})
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: 0)).button == 'b'
    assert policy.switching is None


def test_teaching_does_not_select_background_party_under_confirmation(real_data):
    from pokesim.gen2.menus import Teach
    rows = ('▷ PARTNER ABLE', 'CANCEL', '│▶YES│', '│ NO │', 'move to make room for SURF?') + ('',) * 13
    snapshot = SimpleNamespace(tiles=rows, text='\n'.join(rows), data=real_data,
                               party=[SimpleNamespace(moves=(64, 127, 48, 30))])
    menu = Teach(57, 0, phase='learn')
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 1)) == 'a'
    assert menu.phase == 'learn'


def test_tyrogue_training_selects_the_actual_stat_branch(real_data):
    from pokesim.gen2.training import projects
    mon = SimpleNamespace(species=236, egg=False, level=19, experience=6859, friendship=70,
                          box=None, trainer_id=1, dvs=(10,) * 5, stat_exp=(0,) * 5)
    snapshot = SimpleNamespace(items=[], party=(mon,), stored=(), owned={236})
    assert {row[4] for row in projects(real_data, snapshot, 'day')} == {237}
    mon.dvs = (10, 15, 0, 10, 10)
    assert {row[4] for row in projects(real_data, snapshot, 'day')} == {106}
    mon.dvs = (10, 0, 15, 10, 10)
    assert {row[4] for row in projects(real_data, snapshot, 'day')} == {107}


def test_breeding_observes_baby_groups_gender_and_related_dvs(real_data):
    from pokesim.gen2.breeding import offspring
    def mon(species, gender, defense, special):
        return SimpleNamespace(species=species, gender=gender, egg=False, dvs=(0, 0, defense, 0, special))
    ditto = mon(132, 'Genderless', 3, 4)
    pikachu = mon(25, 'Male', 2, 4)
    assert offspring(real_data, ditto, pikachu) == {172}
    assert not offspring(real_data, ditto, mon(25, 'Female', 3, 12))
    assert not offspring(real_data, ditto, mon(172, 'Female', 2, 4))
    assert not offspring(real_data, ditto, mon(30, 'Female', 2, 4))
    assert not offspring(real_data, ditto, mon(132, 'Genderless', 2, 4))
    assert offspring(real_data, mon(39, 'Female', 3, 4), pikachu) == {174}
    assert not offspring(real_data, mon(39, 'Male', 3, 4), pikachu)


def test_tree_rarity_uses_facing_coordinates_and_trainer_id():
    from pokesim.gen2.collection import tree_score
    assert tree_score(4, 8, 0) == 3
    assert tree_score(4, 8, 12343) == 0


def test_victory_road_guards_block_remote_routes_until_story_flags(real_data):
    from pokesim.gen2.world import travel_collision
    mid = real_data.map_ids['VICTORY_ROAD_GATE']
    entry = real_data.maps[mid]
    snapshot = SimpleNamespace(event=lambda name: False)
    grid = travel_collision(real_data, snapshot, mid, entry['collision'])
    assert grid[5 * entry['width'] + 7] == grid[5 * entry['width'] + 12] == 7
    snapshot.event = lambda name: True
    assert travel_collision(real_data, snapshot, mid, entry['collision']) == entry['collision']


def test_gen2_league_records_survive_evolution_and_replayed_return_trades(real_data, tmp_path):
    from pokesim.gen2 import league
    from pokesim.store import Store
    mon = {'species': 95, 'nick': 'ONIX', 'trainer_id': 123, 'dvs': [7, 3, 9, 5, 7], 'egg': False}
    party_mon = SimpleNamespace(egg=False, to_dict=lambda: dict(mon))
    source, target = Store(tmp_path / 'source'), Store(tmp_path / 'target')
    try:
        snapshot = SimpleNamespace(hall_of_fame_count=1, party=(party_mon,), stored=())
        league.record(source, real_data, snapshot)
        league.record(source, real_data, snapshot)
        incoming = league.export(source, real_data, mon)
        evolved = {**mon, 'species': 208, 'nick': 'STEELIX'}
        assert league.validate(incoming, real_data, evolved) == incoming
        with target.lock, target.db:
            league.merge(target.db, incoming)
            league.merge(target.db, incoming)
        payload = league.apply({'party': [evolved]}, target, real_data)
        assert payload['party'][0]['elite_four_wins'] == 1
        with pytest.raises(ValueError):
            league.validate({**incoming, 'counts': {'bad': -1}})
        with pytest.raises(ValueError):
            league.validate(incoming, real_data, {**evolved, 'trainer_id': 456})
    finally:
        source.close()
        target.close()


def test_gen2_league_does_not_merge_twins_with_different_nicknames(real_data):
    from pokesim.gen2 import league
    value = {'partners': {}}
    first = {'species': 95, 'nick': 'ROCK', 'trainer_id': 123, 'dvs': [7, 3, 9, 5, 7]}
    keys = league.resolve(real_data, value, [first, {**first, 'nick': 'STONE'}])
    assert keys[0] != keys[1]
    assert not any(row['ambiguous'] for row in value['partners'].values())
    keys = league.resolve(real_data, value, [first, first])
    assert value['partners'][keys[0]]['ambiguous']


def test_fighting_type_move_is_not_the_fight_command_menu(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=157, level=100, egg=False, hp=300, moves=(15, 53, 70, 249),
                          pp=(30, 0, 12, 15), stats=(350, 250, 220, 280, 310, 260))
    snapshot = SimpleNamespace(text='TYPE/FIGHTING\nCUT\nFLAMETHROWER\nSTRENGTH\n▶ROCK SMASH',
                               tiles=(), party=[mon], in_battle=1, enemy_species=74, badges=65535,
                               owned={74}, can_catch=True, pockets={'balls': []})
    mem = SimpleNamespace(byte=lambda name: 4 if name == 'wMenuCursorY' else 0)
    assert policy.battle(snapshot, mem).button == 'a'


def test_missed_legendary_retry_only_changes_unloaded_encounter_flags(real_data):
    from pokesim.gen2.legendary import Recovery
    class BankedMemory:
        def __init__(self):
            self.raw = bytearray(65536)

        def __getitem__(self, key):
            return self.raw[key[1] if isinstance(key, tuple) else key]

        def __setitem__(self, key, value):
            self.raw[key[1] if isinstance(key, tuple) else key] = value

    memory = BankedMemory()
    _, base = real_data.symbols['wEventFlags']
    flags = ('EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA')
    for flag in flags:
        index = real_data.events[flag]
        memory.raw[base + index // 8] |= 1 << (index % 8)
    memory.raw[real_data.symbols['wMoney'][1]] = 123
    before = bytes(memory.raw)
    snapshot = SimpleNamespace(data=real_data, frame=1, valid=True, started=True, in_battle=False,
        map=real_data.map_ids['WHIRL_ISLAND_LUGIA_CHAMBER'], owned=set(), tiles=('',) * 18,
        event=lambda name: bool(memory.raw[base + real_data.events[name] // 8] & (1 << (real_data.events[name] % 8))))
    recovery = Recovery({'pending': {'249': 0}, 'attempts': {'249': 1}})
    assert recovery.observe(snapshot, memory) == []
    assert bytes(memory.raw) == before
    snapshot.map = real_data.map_ids['ECRUTEAK_CITY']
    snapshot.owned = {249}
    assert recovery.observe(snapshot, memory) == []
    assert bytes(memory.raw) == before
    snapshot.owned = set()
    recovery.pending['249'] = 0
    assert recovery.observe(snapshot, memory) == [249]
    expected = bytearray(before)
    for flag in flags:
        index = real_data.events[flag]
        expected[base + index // 8] &= ~(1 << (index % 8))
    assert memory.raw == expected


def test_burned_tower_fall_finishes_the_beast_scene_before_supply_trips(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    snapshot = SimpleNamespace(map=real_data.map_ids['BURNED_TOWER_B1F'], event=lambda name: False)
    assert policy.healing(snapshot) is None
    assert policy.shop(snapshot) is None


def test_capture_weakening_rejects_a_lethal_lead_move(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='chikorita')
    lead = SimpleNamespace(species=154, level=57, moves=(34, 15, 0, 0), pp=(15, 30, 0, 0), stats=(191, 110, 110, 100, 100, 100))
    helper = SimpleNamespace(species=16, level=14, moves=(33, 0, 0, 0), pp=(30, 0, 0, 0), stats=(35, 20, 18, 25, 18, 18))
    snapshot = SimpleNamespace(party=(lead, helper), enemy_species=98, enemy_hp=47, enemy_max_hp=47,
                               pockets={'balls': [(real_data.items['POKE_BALL'], 2)]})
    mem = SimpleNamespace(byte=lambda name: 0, word=lambda name: 40)
    assert policy.capture_move(snapshot, mem) is None
    assert policy.capture_move(snapshot, mem, slot=1) == 0
    snapshot.enemy_hp = 15
    assert policy.capture_move(snapshot, mem, slot=1) is None


def test_full_party_makes_room_before_togepi_gift(real_data):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data, starter='cyndaquil')
    policy.storage_goal = lambda snapshot: Goal('storage', 'PC', 'VIOLET_POKECENTER_1F', 9, 2, 'up')
    snapshot = SimpleNamespace(frame=100, badges=1, party=[None] * 6,
                               event=lambda flag: flag != 'EVENT_GOT_TOGEPI_EGG_FROM_ELMS_AIDE')
    assert policy.journey(snapshot, None).key == 'collection_gift_room'


def test_replacement_field_partner_request_survives_checkpoint(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    policy.partner_move = 57
    restored = Policy(real_data, starter='cyndaquil')
    restored.load_state_dict(policy.state_dict())
    snapshot = SimpleNamespace(badges=65535, party=[SimpleNamespace(species=157, egg=False)])
    assert restored.needed_move(snapshot) == 57
    snapshot.party.append(SimpleNamespace(species=98, egg=False))
    assert restored.needed_move(snapshot) == 127
    assert restored.partner_move is None


def test_grandfather_selects_the_requested_partner():
    from pokesim.gen2.menus import ShowPartner
    menu = ShowPartner(3, 'reward')
    snapshot = SimpleNamespace(text='CANCEL 45/45', tiles=(), event=lambda flag: False)
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 1)) == 'down'
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 4)) == 'a'
    snapshot.event = lambda flag: True
    assert menu.step(snapshot, None) == 'b'


def test_trade_demand_collects_enough_spare_copies():
    from pokesim.gen2.collection import wanted
    policy = SimpleNamespace(demand={179: 1})
    mon = SimpleNamespace(species=179, egg=False)
    snapshot = SimpleNamespace(owned={179}, party=(mon,), stored=())
    assert wanted(policy, snapshot, 179)
    snapshot.stored = (mon,)
    assert not wanted(policy, snapshot, 179)
    assert wanted(policy, snapshot, 180)


def test_interrupted_preparation_aborts_instead_of_waiting_on_a_paused_worker():
    from pokesim.gen2.preparation import begin
    state = {'id': 'exchange', 'trade_key': 'partner', 'phase': 'travelling'}
    emu = SimpleNamespace(store=SimpleNamespace(get=lambda key: state), preparation=None)
    with pytest.raises(ValueError, match='interrupted'):
        begin(emu, 'partner', 'exchange')
    emu.preparation = object()
    assert begin(emu, 'partner', 'exchange') == state
    with pytest.raises(ValueError, match='another Pokémon'):
        begin(emu, 'another', 'exchange')
    state['phase'] = 'ready'
    emu.preparation = None
    assert begin(emu, 'partner', 'exchange') == state


def test_repeat_mew_requires_walking_then_a_later_win(tmp_path, monkeypatch):
    from pokesim import config, rewards
    from pokesim.gen2.steps import RETURNS, consume, observe_mew, ready
    from pokesim.store import Store
    monkeypatch.setattr(config, 'MEW_EVENT', True, raising=False)
    monkeypatch.setattr(config, 'MEW_RETURN_STEPS', 10)
    store = Store(tmp_path)
    try:
        rewards.initialize(store, 2)
        snapshot = SimpleNamespace(valid=True, started=True, hall_of_fame_count=2, owned={151})
        observe_mew(store, snapshot, 100)
        assert store.get(RETURNS)['next_at'] == 110
        observe_mew(store, snapshot, 109)
        assert not ready(store.get(RETURNS), 2)
        observe_mew(store, snapshot, 110)
        assert not ready(store.get(RETURNS), 2)
        rewards.earn(store, 3, enabled=False)
        assert ready(store.get(RETURNS), 3)
        with store.lock, store.db:
            consume(store.db, 112)
        assert not ready(store.get(RETURNS), 3)
        assert store.get(RETURNS)['next_at'] == 122
        monkeypatch.setattr(config, 'MEW_RETURN_STEPS', 0)
        observe_mew(store, snapshot, 200)
        assert not ready(store.get(RETURNS), 4)
        monkeypatch.setattr(config, 'MEW_RETURN_STEPS', 10)
        observe_mew(store, snapshot, 200)
        assert store.get(RETURNS)['next_at'] == 210
    finally:
        store.close()
