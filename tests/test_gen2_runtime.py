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


@pytest.mark.parametrize('game,species,price', [('gold', 27, 700), ('silver', 23, 700), ('crystal', 202, 1500)])
def test_game_corner_prizes_follow_cartridge_versions(game, species, price):
    from pokesim.gen2.gamecorner import prizes
    assert (species, price, 'GOLDENROD') in prizes(game)
    assert (137, 5555 if game == 'crystal' else 9999, 'CELADON') in prizes(game)


@pytest.mark.parametrize('coins,money,target,button', [
    (0, 20000, 100, 'a'), (0, 20000, 5555, 'down'),
    (9500, 20000, 9999, 'a'), (9950, 20000, 9999, 'b'),
    (100, 20000, 100, 'b'), (0, 999, 100, 'b')])
def test_game_corner_coin_menu_respects_price_balance_and_case_capacity(coins, money, target, button):
    from pokesim.gen2.gamecorner import Coins
    rows = [''] * 18
    rows[6], rows[8], rows[10], rows[12] = '▶ 50 :  ¥1000', ' 500 : ¥10000', 'CANCEL', '┌'
    snapshot = SimpleNamespace(coins=coins, money=money, text='\n'.join(rows), tiles=rows)
    assert Coins(target).step(snapshot, None) == button


def test_game_corner_prize_stops_after_native_receipt():
    from pokesim.gen2.gamecorner import Prize
    snapshot = SimpleNamespace(owned={137}, text='CANCEL', tiles=[''] * 18)
    menu = Prize(137)
    assert menu.step(snapshot, None) == 'b'
    snapshot.text = ''
    assert menu.step(snapshot, None) is None


def test_game_corner_waits_for_earned_money(real_data):
    from pokesim.gen2.gamecorner import journey
    snapshot = SimpleNamespace(owned=set(), coins=0, money=0, hall_of_fame_count=2,
                               items=((real_data.items['COIN_CASE'], 1),))
    policy = SimpleNamespace(data=real_data, collection={})
    assert journey(policy, snapshot, None) is None
    assert policy.collection['funding'] == 3


def test_game_corner_menu_survives_policy_reload(real_data):
    from pokesim.gen2.gamecorner import Coins
    from pokesim.gen2.policy import Policy
    first = Policy(real_data)
    first.menu = Coins(5555)
    second = Policy(real_data)
    second.load_state_dict(first.state_dict())
    assert second.menu == first.menu


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


def test_full_box_gift_preserves_existing_native_names(real_data):
    from collections import defaultdict
    from pokesim.gen2.ram import Memory, read_snapshot
    from pokesim.gen2.rewards import gift
    class BankedMemory:
        def __init__(self):
            self.banks = defaultdict(lambda: bytearray(65536))

        def __getitem__(self, key):
            bank, address = key if isinstance(key, tuple) else (0, key)
            return self.banks[bank][address]

        def __setitem__(self, key, value):
            bank, address = key if isinstance(key, tuple) else (0, key)
            self.banks[bank][address] = value

    memory = BankedMemory()
    mem = Memory(memory, real_data)
    for slot in range(19):
        gift(memory, real_data, 161, str(slot), 1, slot)
    before = read_snapshot(memory, real_data)
    for slot, mon in enumerate(before.stored):
        assert mon.nick == real_data.text(mem.read('sBox2MonNicknames', 11, slot * 11))
    originals = mem.read('sBox2MonOTs', 19 * 11)
    gift(memory, real_data, 151, 'final slot', 1, 19)
    after = read_snapshot(memory, real_data)
    assert after.stored[:-1] == before.stored
    assert after.stored[-1].species == 151
    assert mem.read('sBox2MonOTs', 19 * 11) == originals
    assert real_data.text(mem.read('sBox2MonOTs', 11, 19 * 11)) == 'POKESIM'


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
    mon = SimpleNamespace(species=156, level=25, egg=False, moves=(15, 43, 108, 52), pp=(30, 30, 20, 20), stats=(90, 60, 50, 70, 70, 60))
    snapshot = SimpleNamespace(text='Disabled!', tiles=('Disabled!',), party=[mon], in_battle=2,
                               enemy_species=39, badges=0, owned=set(), can_catch=True, pockets={'balls': []})
    values = {'wCurBattleMon': 0, 'wMenuCursorY': 4, 'wPlayerDisableCount': 72, 'wDisabledMove': 52}
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: values.get(name, 0))).button == 'up'


def test_level_up_replacement_preserves_hm_moves(real_data):
    from types import SimpleNamespace
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    mon = SimpleNamespace(species=156, level=25, egg=False, moves=(15, 43, 108, 52), pp=(30, 30, 20, 20), stats=(90, 60, 50, 70, 70, 60))
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


@pytest.mark.parametrize('species,button', [(185, 'a'), (143, 'a'), (19, 'b')])
def test_last_balls_are_available_for_one_time_encounters(real_data, species, button):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    policy.needed_move = lambda snapshot: 0
    policy.capture_move = lambda *args: None
    rows = [''] * 18
    rows[4], rows[5], rows[6] = '▶POKé BALL', '× 1', 'CANCEL'
    snapshot = SimpleNamespace(party=(), stored=(), text='\n'.join(rows), tiles=rows,
        in_battle=1, enemy_species=species, owned=set(), can_catch=True, badges=4, money=0,
        pockets={'balls': [(real_data.items['POKE_BALL'], 1)]})
    assert policy.battle(snapshot, SimpleNamespace(byte=lambda name: 1)).button == button


def test_slot_machine_leaves_when_the_prize_budget_is_reached():
    from pokesim.gen2.gamecorner import Slots
    rows = [''] * 18
    rows[12], rows[13], rows[14], rows[15] = '┌', '▶YES', 'Play again?', 'NO'
    snapshot = SimpleNamespace(coins=9999, text='\n'.join(rows), tiles=rows)
    assert Slots(9999).step(snapshot, SimpleNamespace(byte=lambda name: 1)) == 'down'


def test_full_party_makes_room_before_togepi_gift(real_data):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data, starter='cyndaquil')
    policy.storage_goal = lambda snapshot: Goal('storage', 'PC', 'VIOLET_POKECENTER_1F', 9, 2, 'up')
    snapshot = SimpleNamespace(frame=100, badges=1, party=[None] * 6, map=real_data.map_ids['VIOLET_POKECENTER_1F'],
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


def test_ruins_solver_completes_shuffled_boards_without_losing_pieces():
    import random
    from pokesim.gen2.ruins import CELLS, DESTINATIONS, puzzle_button
    for seed in range(50):
        rng = random.Random(seed)
        board = [0] * 36
        for piece, cell in enumerate(rng.sample(sorted(CELLS), 16), 1):
            board[cell] = piece
        cursor, held = 0, 0
        for _ in range(2000):
            if all(board[cell] == piece for piece, cell in DESTINATIONS.items()):
                break
            button = puzzle_button(board, cursor, held)
            assert button is not None
            if button == 'a':
                board[cursor], held = held, board[cursor]
            elif cursor == 30 and button == 'right':
                cursor = 35
            elif cursor == 35 and button == 'left':
                cursor = 30
            else:
                cursor += {'up': -6, 'down': 6, 'left': -1, 'right': 1}[button]
            assert cursor in CELLS
            assert sorted([n for n in board if n] + ([held] if held else [])) == list(range(1, 17))
        assert all(board[cell] == piece for piece, cell in DESTINATIONS.items())
        assert not held


def test_time_capsule_rejects_eggs_johto_moves_and_mail(real_data):
    from pokesim.gen2.timecapsule import compatible
    mon = SimpleNamespace(egg=False, species=95, moves=(20, 88, 106, 99), held_item=0)
    assert compatible(mon, real_data)
    for change in ({'egg': True}, {'species': 152}, {'moves': (166, 0, 0, 0)},
                   {'held_item': real_data.items['FLOWER_MAIL']}):
        assert not compatible(SimpleNamespace(**(vars(mon) | change)), real_data)
    assert compatible(SimpleNamespace(**(vars(mon) | {'held_item': real_data.items['METAL_COAT']})), real_data)


def test_time_capsule_conversion_matches_retail_exchange(real_data):
    from pokesim.gen2.timecapsule_conversion import to_gen1, to_gen2
    old = bytes.fromhex('85002306001515ff9621000051a1001c0a0410061e052f065603d2a6f728230000110024000d001b0027000f')
    modern = bytes.fromhex('5f0014586a630d3b008c6100000000000000000000804f140f1e144600a158210000004200420027006e00350022002c')
    row = {'struct': modern, 'nickname': b'\x50' * 11, 'trainer': b'\x50' * 11}
    result = to_gen1(row, real_data)
    assert result['struct'].hex() == '220042000005040014586a630d3b008c6100000000000000000000804f140f1e142100420027006e00350022'
    result = to_gen2({**row, 'struct': old}, real_data)['struct']
    assert result[0:8] == bytes.fromhex('81ad9621000051a1')
    assert result[27:33] == bytes.fromhex('460000001100')
    assert result[34:] == bytes.fromhex('00230024000d001b0027000d000f')


def test_tower_team_has_three_distinct_legal_species():
    from pokesim.gen2.tower import select_team
    def mon(species, level, strength, egg=False):
        return SimpleNamespace(species=species, level=level, stats=(strength,) * 6, egg=egg)
    snapshot = SimpleNamespace(party=(mon(150, 30, 200), mon(25, 30, 90), mon(25, 30, 100)),
        stored=(mon(26, 30, 80), mon(81, 29, 70), mon(250, 20, 150), mon(82, 30, 100, True)))
    cap, team = select_team(snapshot)
    assert cap == 30
    assert [m.species for m in team] == [25, 26, 81]


def test_time_capsule_team_restoration_takes_priority_over_story(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.collection['time_capsule_restore'] = ['original']
    from pokesim.gen2.policy import Goal
    policy.storage_goal = lambda _: Goal('pc', 'PC', 'NEW_BARK_TOWN', 1, 1, 'up')
    snapshot = SimpleNamespace(party=(), stored=(), map=real_data.map_ids['NEW_BARK_TOWN'])
    goal = policy.journey(snapshot, None)
    assert goal.key == 'collection_activity_team'


def test_daycare_selects_the_requested_parent_on_gender_list():
    from pokesim.gen2.menus import DayCare
    menu = DayCare(0, 3)
    snapshot = SimpleNamespace(daycare=(None, None), text='CANCEL\nChoose a POKéMON.', tiles=())
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 1)) == 'down'
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 4)) == 'a'


def test_time_capsule_waits_for_bill_and_next_day():
    from pokesim.gen2.timecapsule import unlocked
    snapshot = SimpleNamespace(started=True, event=lambda name: True)
    assert not unlocked(snapshot, SimpleNamespace(byte=lambda name: 0))
    snapshot.event = lambda name: False
    assert not unlocked(snapshot, SimpleNamespace(byte=lambda name: 8))
    assert unlocked(snapshot, SimpleNamespace(byte=lambda name: 0))
    assert not unlocked(None, None)


def test_celebi_quest_respects_the_overnight_wait(real_data):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2.celebi import journey
    from pokesim.gen2.policy import Policy, Goal
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    memory = {}
    class Ram:
        def __getitem__(self, key):
            bank, address = key
            return bytes(memory.get((bank, i), 0) for i in range(address.start, address.stop))
    policy.memory = Ram()
    policy.person = lambda snapshot, key, label, room, script: Goal(key, label, room, 3, 3, 'up')
    bank, address = real_data.symbols['wDailyFlags1']
    memory[bank, address] = 1
    flags = {'EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', 'EVENT_CAN_GIVE_GS_BALL_TO_KURT', 'EVENT_GAVE_GS_BALL_TO_KURT'}
    snapshot = SimpleNamespace(owned=set(), event=flags.__contains__, map=real_data.map_ids['KURTS_HOUSE'],
                               x=3, y=3, objects=())
    assert journey(policy, snapshot, Goal) is None
    memory[bank, address] = 0
    assert journey(policy, snapshot, Goal).key == 'celebi_kurt'
    flags.add('EVENT_FOREST_IS_RESTLESS')
    snapshot.items = ()
    assert journey(policy, snapshot, Goal).key == 'celebi_kurt_returns'
    snapshot.items = ((real_data.items['GS_BALL'], 1),)
    snapshot.can_catch = True
    goal = journey(policy, snapshot, Goal)
    assert (goal.map_name, goal.x, goal.y, goal.face) == ('ILEX_FOREST', 8, 23, 'up')


def test_time_capsule_preserves_league_counts_across_return_trade(real_data):
    from pokesim.gen2 import league
    from pokesim.gen2.ram import decode_mon
    from pokesim.gen2.timecapsule_conversion import to_gen1
    from pokesim.gen2.timecapsule_records import to_gen1 as old_record, to_gen2 as new_record
    from pokesim.trade.preferences import identity
    raw = bytes.fromhex('5f0014586a630d3b008c6100000000000000000000804f140f1e144600a158210000004200420027006e00350022002c')
    row = {'struct': raw, 'nickname': b'\x8e\x8d\x88\x97' + b'\x50' * 7, 'trainer': b'\x50' * 11}
    mon = decode_mon(raw, row['nickname'], real_data).to_dict()
    signature, name = league.signature(real_data, mon)
    record = {'key': identity(mon), 'version': 'gen2-1', 'individual': 'a' * 24, 'signature': signature,
              'names': [name], 'counts': {'b' * 32: 3}, 'ambiguous': False, 'incomplete': False}
    encoded = {key: value.hex() for key, value in row.items()}
    converted = old_record(record, encoded, real_data)
    assert converted['counts'] == record['counts']
    encoded_old = {key: value.hex() for key, value in to_gen1(row, real_data).items()}
    returned = new_record(converted, encoded_old, real_data)
    league.validate(returned, real_data, mon)
    assert returned['counts'] == record['counts']
    assert returned['signature'] == signature


def test_contest_uses_park_balls_and_runs_from_low_scores():
    from pokesim.gen2.contest import control
    policy = SimpleNamespace(collection={'contest': {'entered': True}})
    snapshot = SimpleNamespace(in_battle=1, text='FIGHT POKéMON PACK RUN', tiles=())
    values = {'wEnemyMonSpecies': 123, 'wEnemyMonMaxHP': 55, 'wEnemyMonHP': 55,
              'wContestMonSpecies': 0, 'wParkBallsRemaining': 20, 'wMenuCursorX': 1, 'wMenuCursorY': 1}
    mem = SimpleNamespace(byte=lambda name: values.get(name, 0),
                          word=lambda name: values.get(name, 40), read=lambda name, size: bytes([0xff, 0xff]))
    assert control(policy, snapshot, mem) == 'down'
    values['wMenuCursorY'] = 2
    assert control(policy, snapshot, mem) == 'a'
    values['wParkBallsRemaining'] = 0
    assert control(policy, snapshot, mem) == 'right'
    values['wMenuCursorX'] = 2
    assert control(policy, snapshot, mem) == 'a'


def test_contest_respects_days_and_completed_daily_entry(real_data):
    from pokesim.gen2.contest import journey
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data, starter='cyndaquil')
    memory = {}
    class Ram:
        def __getitem__(self, key):
            bank, address = key
            return bytes(memory.get((bank, i), 0) for i in range(address.start, address.stop))
    policy.memory = Ram()
    snapshot = SimpleNamespace(owned=set(), items=(), can_catch=True,
        map=real_data.map_ids['GOLDENROD_CITY'], x=20, y=20)
    assert journey(policy, snapshot, Goal) is None
    memory[tuple(real_data.symbols['wCurDay'])] = 2
    assert journey(policy, snapshot, Goal).key == 'contest_enter'
    policy.collection.pop('contest')
    memory[tuple(real_data.symbols['wDailyFlags1'])] = 2
    assert journey(policy, snapshot, Goal) is None


def test_active_tower_preempts_campaign_field_partner_recruitment(real_data, monkeypatch):
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2 import tower
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.collection['tower'] = {'entered': False}
    expected = Goal('tower_enter', 'Tower', 'BATTLE_TOWER_1F', 7, 7, 'up')
    monkeypatch.setattr(tower, 'journey', lambda *args: expected)
    snapshot = SimpleNamespace(map=real_data.map_ids['SILVER_CAVE_POKECENTER_1F'])
    assert policy.journey(snapshot, None) == expected


def test_tower_prepares_near_entrance_before_removing_field_partners(real_data):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2.tower import journey
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.memory = None
    policy.collection['tower'] = {'team': ['target'], 'original': [], 'cap': 30,
                                  'entered': False, 'returning': False}
    snapshot = SimpleNamespace(map=real_data.map_ids['SILVER_CAVE_POKECENTER_1F'], party=(), stored=())
    goal = journey(policy, snapshot, Goal)
    assert goal.map_name == 'OLIVINE_POKECENTER_1F'
    assert goal.key == 'tower_travel'
    assert 'activity_team' not in policy.collection


def test_fixed_damage_moves_beat_weak_attacks_and_respect_immunity(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    dragonair = SimpleNamespace(species=148, level=30, stats=(88, 60, 50, 50, 50, 50))
    enemy = SimpleNamespace(enemy_species=73, enemy_level=30)
    assert policy.move_score(82, dragonair, enemy) == 40
    assert policy.move_score(82, dragonair, enemy) > policy.move_score(21, dragonair, enemy)
    assert policy.move_score(69, dragonair, enemy) == 30
    assert policy.move_score(69, dragonair, SimpleNamespace(enemy_species=94, enemy_level=30)) == 0


@pytest.mark.parametrize('result,entered,expected', [(1, 1, 0), (1, 4, 3), (0, 7, 7)])
def test_tower_win_count_excludes_the_opponent_that_defeated_the_player(real_data, monkeypatch, result, entered, expected):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.memory = None
    policy.collection['tower'] = {'entered': True, 'returning': False, 'cap': 30, 'original': []}
    values = {'sNrOfBeatenBattleTowerTrainers': entered, 'wBattleResult': result}
    monkeypatch.setattr(tower, 'Memory', lambda *args: SimpleNamespace(byte=lambda name: values[name]))
    snapshot = SimpleNamespace(map=real_data.map_ids['BATTLE_TOWER_1F'], party=(), frame=100)
    assert tower.journey(policy, snapshot, Goal) is None
    assert policy.collection['tower_result']['wins'] == expected


def test_weekly_red_reset_does_not_interrupt_completed_collection(real_data, monkeypatch):
    from pokesim.gen2 import kanto, collection
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.completed['red'] = 10
    false_events = {'EVENT_TRAINERS_IN_CERULEAN_GYM', 'EVENT_VIRIDIAN_GYM_BLUE', 'EVENT_RED_IN_MT_SILVER'}
    snapshot = SimpleNamespace(map=real_data.map_ids['NEW_BARK_TOWN'], badges=65535, frame=100,
                               event=lambda name: name not in false_events)
    expected = Goal('collection', 'Collect', 'NEW_BARK_TOWN', 1, 1)
    monkeypatch.setattr(collection, 'journey', lambda *args: expected)
    assert kanto.journey(policy, snapshot, SimpleNamespace(byte=lambda name: 10), Goal) == expected


def test_daycare_cost_accounts_for_unapplied_levels(real_data):
    from pokesim.gen2.breeding import retrieval_cost
    parent = SimpleNamespace(species=220, level=21, experience=29816)
    assert retrieval_cost(real_data, SimpleNamespace(daycare=(parent, None))) == 800
    assert retrieval_cost(real_data, SimpleNamespace(daycare=(None, None))) == 0


def test_tyrogue_branches_need_viable_stats_not_just_spare_copies(real_data):
    from pokesim.gen2.breeding import branch_parents
    hitmonlee = SimpleNamespace(species=236, level=5, dvs=(8, 15, 0, 0, 0), stat_exp=(0,) * 5)
    hitmontop = SimpleNamespace(species=236, level=5, dvs=(0,) * 5, stat_exp=(0,) * 5)
    snapshot = SimpleNamespace(party=(hitmonlee, hitmonlee), stored=())
    assert not branch_parents(real_data, snapshot, 236, {106, 237})
    snapshot.party = (hitmonlee, hitmontop)
    assert branch_parents(real_data, snapshot, 236, {106, 237})


def test_trade_item_quests_use_versioned_cartridge_objects(real_data):
    from pokesim.gen2.quests import trade_items
    from pokesim.gen2.policy import Goal
    finished = set()
    def person(snapshot, key, label, area, script):
        assert any(obj['script'] == script for obj in real_data.maps[real_data.map_ids[area]]['objects'])
        return area
    policy = SimpleNamespace(person=person, data=real_data)
    snapshot = SimpleNamespace(map=real_data.map_ids['NEW_BARK_TOWN'], event=lambda name: name in finished)
    for flag, area in [('EVENT_GOT_UP_GRADE', 'SILPH_CO_1F'),
                       ('EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL', 'SLOWPOKE_WELL_B2F'),
                       ('EVENT_MOUNT_MORTAR_2F_INSIDE_DRAGON_SCALE', 'MOUNT_MORTAR_2F_INSIDE')]:
        assert trade_items(policy, snapshot, Goal) == area
        finished.add(flag)
    assert trade_items(policy, snapshot, Goal) is None


def test_slowking_branch_breeds_another_slowpoke(real_data):
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    slowbro = SimpleNamespace(species=80, moves=(33,), egg=False, box=None, gender='Female', trainer_id=1, dvs=(0, 2, 4, 6, 8))
    ditto = SimpleNamespace(species=132, moves=(144,), egg=False, box=None, gender='Genderless', trainer_id=1, dvs=(0, 1, 3, 5, 7))
    snapshot = SimpleNamespace(party=(slowbro, slowbro, ditto), stored=(), daycare=(None, None),
                               owned={79, 80, 132}, money=10000, egg_ready=False)
    policy = SimpleNamespace(data=real_data, collection={}, demand={}, person=lambda *args: 'deposit')
    assert journey(policy, snapshot, Goal) == 'deposit'
    assert policy.collection['breeding']['target'] == 79
    assert policy.collection['breeding']['duplicate']


def test_level_100_chansey_breeds_a_partner_that_can_evolve(real_data):
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    chansey = SimpleNamespace(species=113, moves=(1,), egg=False, box=None, gender='Female',
        trainer_id=1, dvs=(0, 2, 4, 6, 8), level=100)
    ditto = SimpleNamespace(species=132, moves=(144,), egg=False, box=None, gender='Genderless',
        trainer_id=1, dvs=(0, 1, 3, 5, 7), level=20)
    snapshot = SimpleNamespace(party=(chansey, chansey, ditto), stored=(), daycare=(None, None),
        owned={113, 132}, money=10000, egg_ready=False)
    policy = SimpleNamespace(data=real_data, collection={}, demand={}, person=lambda *args: 'deposit')
    assert journey(policy, snapshot, Goal) == 'deposit'
    assert policy.collection['breeding']['target'] == 113
    assert policy.collection['breeding']['duplicate']


def test_full_pc_box_does_not_interrupt_an_active_league_attempt(real_data):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.collection['funding'] = 2
    policy.person = lambda snapshot, key, *args: key
    snapshot = SimpleNamespace(map=real_data.map_ids['KOGAS_ROOM'], can_catch=False,
        box_counts=(20, 0), hall_of_fame_count=1, money=10000, daycare=(),
        owned={152, 155, 158}, event=lambda name: name != 'EVENT_BEAT_ELITE_4_KOGA')
    assert journey(policy, snapshot, None, Goal) == 'funds_koga'


def test_roamer_search_cycles_a_border_until_a_beast_is_on_the_current_route(real_data, monkeypatch):
    from pokesim.gen2 import collection
    from pokesim.gen2.quests import roamers
    from pokesim.gen2.policy import Goal
    policy = SimpleNamespace(data=real_data, collection={}, decisions=0, memory=None,
        nav=SimpleNamespace(regions=SimpleNamespace(route=lambda *args, **kwargs: []),
                            local=lambda *args, **kwargs: ['left'], visits={}))
    snapshot = SimpleNamespace(map=real_data.map_ids['VIOLET_CITY'], x=1, y=8, owned=set(),
        roamers=[{'species': 243, 'map': real_data.map_ids['ROUTE_42']}])
    assert roamers(policy, snapshot, Goal).map_name == 'ROUTE_36'
    snapshot.map, snapshot.x = real_data.map_ids['ROUTE_36'], 58
    assert roamers(policy, snapshot, Goal).map_name == 'RUINS_OF_ALPH_OUTSIDE'
    snapshot.map = real_data.map_ids['ROUTE_36_RUINS_OF_ALPH_GATE']
    assert roamers(policy, snapshot, Goal).map_name == 'RUINS_OF_ALPH_OUTSIDE'
    snapshot.map = real_data.map_ids['RUINS_OF_ALPH_OUTSIDE']
    assert roamers(policy, snapshot, Goal).map_name == 'ROUTE_36'
    snapshot.map = real_data.map_ids['ROUTE_36']
    snapshot.roamers[0]['map'] = snapshot.map
    monkeypatch.setattr(collection, 'encounter_points', lambda *args: [(58, 8, None), (57, 8, None)])
    goal = roamers(policy, snapshot, Goal)
    assert (goal.key, goal.map_name, goal.x, goal.y) == ('collection_hunt', 'ROUTE_36', 57, 8)


def test_tower_training_does_not_finish_during_held_item_transfer(real_data, monkeypatch):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower, training
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.memory = None
    policy.menu = object()
    mon = SimpleNamespace(species=101, level=23, trainer_id=1, dvs=(0,) * 5,
                           to_dict=lambda: {'trainer_id': 1, 'dvs': [0] * 5})
    state = policy.collection['tower'] = {'team': [tower.key(mon)], 'original': [], 'cap': 30,
        'entered': False, 'returning': False, 'previous_training': None}
    snapshot = SimpleNamespace(map=real_data.map_ids['SILVER_CAVE_POKECENTER_1F'], party=(mon,), stored=(), x=9, y=2)
    monkeypatch.setattr(training, 'journey', lambda *args: None)
    assert tower.journey(policy, snapshot, Goal).key == 'tower_training_menu'
    assert not state.get('trained')


def test_training_stops_at_requested_tower_cap(real_data):
    from pokesim.gen2.training import journey
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=101, level=30, trainer_id=1, dvs=(0,) * 5,
                           held_item=real_data.items['EXP_SHARE'])
    policy.collection['training'] = {'identity': [1, [0] * 5], 'target': 101, 'species': 101,
                                     'terminal': True, 'level_goal': 30}
    snapshot = SimpleNamespace(party=(mon,), stored=(), items=())
    assert journey(policy, snapshot, SimpleNamespace(byte=lambda name: 1), Goal) is None
    assert policy.collection['training'] is None


def test_idle_training_yields_to_new_collection_opportunities(real_data):
    from pokesim.gen2.training import journey
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=184, level=40, trainer_id=1, dvs=(0,) * 5,
                           held_item=real_data.items['EXP_SHARE'], egg=False)
    policy.collection['training'] = {'identity': [1, [0] * 5], 'target': 184, 'species': 184,
                                     'terminal': True, 'item': None}
    snapshot = SimpleNamespace(party=(mon,), stored=(), items=(), owned={184})
    assert journey(policy, snapshot, SimpleNamespace(byte=lambda name: 1), Goal) is None
    assert policy.collection['training'] is None


def test_checkpoint_clock_export_preserves_elapsed_days(real_data):
    import struct
    from pyboy import PyBoy
    from pokesim.gen2.cable_verification import checkpoint_clock
    from tools.advance_gen2_clock import advance
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    rom = (Path(directory) / (real_data.game + '.gbc')).read_bytes()
    pb = PyBoy(io.BytesIO(rom), ram_file=io.BytesIO(bytes(32768)), window='null', cgb=True, sound_emulated=False)
    try:
        state = io.BytesIO()
        pb.save_state(state)
        raw = state.getvalue()
        changed = advance(raw, 48)
        assert raw[:-48] == changed[:-48]
        assert raw[-40:] == changed[-40:]
        clock = checkpoint_clock(rom, changed)
        assert len(clock) == 10
        assert struct.unpack('d', clock[:8])[0] == struct.unpack('d', raw[-48:-40])[0] - 48 * 3600
    finally:
        pb.stop(save=False)


@pytest.mark.parametrize('steps,cycle,gain', [(2, 0, 1), (2, 1, 0), (253, 0, 0)])
def test_cable_verification_allows_only_native_walking_friendship(steps, cycle, gain):
    from pokesim.gen2.cable_verification import untraded_party
    raw = bytearray(48)
    raw[27] = 172
    row = {'struct': bytes(raw), 'nickname': b'PARTNER', 'trainer': b'OWNER'}
    source = SimpleNamespace(step_count=250, happiness_cycle=1, party=[SimpleNamespace(egg=False)] * 2)
    current = SimpleNamespace(step_count=steps, happiness_cycle=cycle)
    expected = untraded_party([row, row], 1, source, current)
    assert expected[0]['struct'][27] == 172 + gain
    assert expected[0]['struct'][:27] == row['struct'][:27]
    assert expected[0]['struct'][28:] == row['struct'][28:]
    assert expected[0]['nickname'] == row['nickname']


def test_training_waits_for_transient_collision_map(real_data, monkeypatch):
    from pokesim.gen2 import collection, training
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=101, level=20, trainer_id=1, dvs=(0,) * 5,
                           held_item=real_data.items['EXP_SHARE'], box=None)
    policy.collection['training'] = {'identity': [1, [0] * 5], 'target': 101, 'species': 101,
                                     'terminal': True, 'level_goal': 30, 'item': None}
    snapshot = SimpleNamespace(party=(mon,), stored=(), items=(), map=real_data.map_ids['SILVER_CAVE_ROOM_1'], x=11, y=32)
    monkeypatch.setattr(collection, 'encounter_points', lambda *args: [])
    goal = training.journey(policy, snapshot, SimpleNamespace(byte=lambda name: 1), Goal)
    assert goal.key == 'collection_train'
    assert (goal.x, goal.y) == (11, 32)


def test_slowpoke_well_boulder_uses_the_reachable_side(real_data):
    from pokesim.gen2.quests import trade_items
    from pokesim.gen2.policy import Goal
    well = real_data.map_ids['SLOWPOKE_WELL_B1F']
    index = next(i for i, obj in enumerate(real_data.maps[well]['objects'], 1) if obj['sprite'] == 'SPRITE_BOULDER')
    events = {'EVENT_GOT_UP_GRADE'}
    reachable = set()
    nav = SimpleNamespace(objects={}, local=lambda snapshot, points, *args, **kwargs: [] if points[0] in reachable else None)
    policy = SimpleNamespace(data=real_data, nav=nav, memory=None, person=lambda *args: 'visit')
    snapshot = SimpleNamespace(map=well, objects=((index, 3, 2),), event=lambda name: name in events)
    goal = trade_items(policy, snapshot, Goal)
    assert goal.face == 'left' and goal.x == 4
    reachable.add((7, 11))
    assert trade_items(policy, snapshot, Goal) == 'visit'
    events.add('EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL')
    goal = trade_items(policy, snapshot, Goal)
    assert goal.face == 'right' and goal.x == 2
    reachable.add((17, 15))
    assert trade_items(policy, snapshot, Goal) == 'visit'


def test_tower_strength_preparation_preserves_the_active_menu(real_data):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower
    from pokesim.gen2.menus import Teach
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.memory = None
    mon = SimpleNamespace(species=99, level=50, moves=(23, 57, 182, 250), stats=(138, 160, 120, 90, 60, 65),
                           held_item=0, to_dict=lambda: {'trainer_id': 1, 'dvs': [0] * 5})
    policy.collection['tower'] = {'team': [tower.key(mon)], 'original': [], 'cap': 50,
                                  'entered': False, 'returning': False, 'trained': True, 'preparation_center': True}
    snapshot = SimpleNamespace(map=real_data.map_ids['OLIVINE_POKECENTER_1F'], party=(mon,),
                               items=((real_data.items['HM04'], 1),), x=9, y=2)
    assert tower.journey(policy, snapshot, Goal).key == 'tower_move'
    menu = policy.menu
    assert isinstance(menu, Teach) and menu.move == 70
    assert tower.journey(policy, snapshot, Goal).key == 'tower_move'
    assert policy.menu is menu


def test_teaching_a_move_closes_leftover_pc_dialogue():
    from pokesim.gen2.menus import Teach
    menu = Teach(70, 0)
    snapshot = SimpleNamespace(party=(SimpleNamespace(moves=(23, 57, 182, 250)),),
        text='The PC turned on.', tiles=(' ',) * 12 + ('┌──────────────────┐',) + (' ',) * 5)
    assert menu.step(snapshot, None) == 'b'
    assert menu.phase == 'open'


def test_item_approach_can_cross_an_internal_cave_warp(real_data):
    from dataclasses import dataclass
    from pokesim.gen2.policy import Policy
    @dataclass
    class Position:
        map: int
        x: int = 5
        y: int = 4
        badges: int = 65535
        party: tuple = ()
        objects: tuple = ()
        def event(self, name):
            return False
    policy = Policy(real_data)
    policy.memory = None
    snapshot = Position(real_data.map_ids['MR_PSYCHICS_HOUSE'])
    goal = policy.person(snapshot, 'earthquake', 'Collect Earthquake', 'VICTORY_ROAD', 'VictoryRoadTMEarthquake')
    mid = real_data.map_ids[goal.map_name]
    assert (goal.x, goal.y) != (3, 29)
    assert policy.nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=True, surf=True) is not None
    snapshot = Position(mid, 13, 6)
    goal = policy.person(snapshot, 'earthquake', 'Collect Earthquake', 'VICTORY_ROAD', 'VictoryRoadTMEarthquake')
    assert (goal.x, goal.y) != (3, 29)
    assert policy.nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=True, surf=True) is not None


def test_tower_recovers_only_when_healing_can_outpace_damage(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=249, level=70, moves=(105, 57, 19, 94), pp=(20, 15, 15, 10))
    snapshot = SimpleNamespace(enemy_species=19, enemy_level=50, enemy_hp=150)
    values = {'wBattleMonHP': 100, 'wBattleMonMaxHP': 300}
    moves = bytearray([33, 0, 0, 0])
    mem = SimpleNamespace(byte=lambda name: 0, word=lambda name: values.get(name, 30), read=lambda *args: bytes(moves))
    assert policy.recovery_move(snapshot, mem, mon, [(40, 1)]) == 0
    disabled = SimpleNamespace(byte=lambda name: {'wPlayerDisableCount': 1, 'wDisabledMove': 105}.get(name, 0))
    assert policy.recovery_move(snapshot, disabled, mon, [(40, 1)]) is None
    assert policy.recovery_move(snapshot, mem, mon, [(200, 1)]) is None
    values['wEnemyMonAttack'] = 999
    snapshot.enemy_level = 100
    moves[0] = 38
    assert policy.recovery_move(snapshot, mem, mon, [(40, 1)]) is None
    values['wBattleMonHP'] = 290
    assert policy.recovery_move(snapshot, mem, mon, [(40, 1)]) is None


def test_exp_share_goes_to_training_partner_after_storage_retrieval(real_data):
    from pokesim.gen2.training import arrive
    from pokesim.gen2.menus import Give
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    partner = SimpleNamespace(trainer_id=1, dvs=(1,) * 5, box=None)
    holder = SimpleNamespace(trainer_id=1, dvs=(2,) * 5, box=None)
    policy.collection.update(training={'identity': [1, [1] * 5]}, share_holder=[1, [2] * 5])
    policy.goal = Goal('collection_equip', 'Equip the training partner', 'OLIVINE_POKECENTER_1F', 5, 6)
    assert arrive(policy, SimpleNamespace(party=(partner, holder), stored=())) == 'wait'
    assert isinstance(policy.menu, Give)
    assert policy.menu.slot == 0


def test_tower_attack_replacement_keeps_recover(real_data):
    from pokesim.gen2.menus import Teach
    menu = Teach(89, 0, phase='learn', replace_move=240)
    snapshot = SimpleNamespace(data=real_data, party=(SimpleNamespace(moves=(105, 56, 240, 129)),),
        text='TYPE/GROUND', tiles=(' ',) * 18)
    assert menu.step(snapshot, SimpleNamespace(byte=lambda name: 3)) == 'a'


def test_tower_teaches_psychic_to_the_stronger_special_attacker(real_data):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    policy.memory = None
    lugia = SimpleNamespace(species=249, level=70, moves=(105, 56, 240, 129), stats=(245, 151, 195, 170, 133, 235),
        held_item=0, to_dict=lambda: {'trainer_id': 1, 'dvs': [1] * 5})
    espeon = SimpleNamespace(species=196, level=70, moves=(33, 98, 44, 36), stats=(220, 125, 123, 208, 220, 179),
        held_item=0, to_dict=lambda: {'trainer_id': 1, 'dvs': [2] * 5})
    policy.collection['tower'] = {'team': [tower.key(lugia), tower.key(espeon)], 'original': [], 'cap': 70,
        'entered': False, 'returning': False, 'trained': True, 'preparation_center': True}
    snapshot = SimpleNamespace(map=real_data.map_ids['OLIVINE_POKECENTER_1F'], party=(lugia, espeon),
        items=((real_data.items['TM29'], 1),), x=9, y=2)
    assert tower.journey(policy, snapshot, Goal).key == 'tower_move'
    assert policy.menu.move == 94 and policy.menu.slot == 1


def test_box_change_opens_the_pc_from_the_overworld():
    from pokesim.gen2.menus import ChangeBox
    menu = ChangeBox(3)
    snapshot = SimpleNamespace(active_box=0, text='', tiles=(' ',) * 18)
    assert menu.step(snapshot, None) == 'a'
    snapshot.text = 'The PC turned on.'
    assert menu.step(snapshot, None) == 'a'
    snapshot.text = 'Choose a POKéMON. CANCEL'
    assert menu.step(snapshot, None) == 'b'


def test_psychic_tm_selection_uses_machine_number(real_data):
    from pokesim.gen2.menus import Teach
    menu = Teach(94, 0, phase='pack')
    rows = [' '] * 18
    rows[2], rows[4] = '     29 PSYCHIC', '     30▶SHADOW BALL'
    snapshot = SimpleNamespace(data=real_data, party=(SimpleNamespace(moves=(33,)),),
        text='\n'.join(rows), tiles=rows)
    mem = SimpleNamespace(byte=lambda name: 3)
    assert menu.step(snapshot, mem) == 'up'
    rows[2], rows[4] = '     29▶PSYCHIC', '     30 SHADOW BALL'
    snapshot.text = '\n'.join(rows)
    assert menu.step(snapshot, mem) == 'a'
    assert menu.phase == 'use'


def test_held_item_menus_close_leftover_pc_dialogue():
    from pokesim.gen2.menus import Give, Take
    snapshot = SimpleNamespace(party=(SimpleNamespace(held_item=57),),
        text='The PC turned on.', tiles=(' ',) * 12 + ('┌──────────────────┐',) + (' ',) * 5)
    assert Give(146, 0).step(snapshot, None) == 'b'
    assert Take(0).step(snapshot, None) == 'b'


def test_tower_toxic_targets_healthy_bulky_opponents(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(moves=(105, 92, 89, 70), pp=(20, 10, 10, 15))
    snapshot = SimpleNamespace(enemy_species=143, enemy_hp=365)
    mem = SimpleNamespace(byte=lambda name: 0)
    options = [(0, 1), (60, 2)]
    assert policy.poison_move(snapshot, mem, mon, options) == 1
    snapshot.enemy_species = 208
    assert policy.poison_move(snapshot, mem, mon, options) is None
    snapshot.enemy_species = 89
    assert policy.poison_move(snapshot, mem, mon, options) is None
    snapshot.enemy_species, snapshot.enemy_hp = 143, 60
    assert policy.poison_move(snapshot, mem, mon, options) is None
    snapshot.enemy_hp = 365
    assert policy.poison_move(snapshot, SimpleNamespace(byte=lambda name: 8), mon, options) is None
    assert policy.poison_move(snapshot, mem, mon, [(60, 2)]) is None


def test_tower_trains_an_evolution_to_cover_shared_weaknesses(real_data):
    from pokesim.gen2.ram import calculated_stats
    from pokesim.gen2.tower import forecast, select_team
    mons = []
    for species, level, moves in [(249, 70, (105, 92, 89, 70)), (196, 70, (94, 247, 44, 36)),
                                  (169, 70, (141, 17, 44, 19)), (247, 53, (44, 157, 37, 242))]:
        dvs, training = (8,) * 5, (5000,) * 5
        mons.append(SimpleNamespace(data=real_data, species=species, level=level, moves=moves, egg=False,
            dvs=dvs, stat_exp=training, stats=calculated_stats(real_data.species[species]['stats'], level, dvs, training)))
    cap, team = select_team(SimpleNamespace(party=tuple(mons), stored=(), items=()))
    assert cap == 70
    assert {mon.species for mon in team} == {249, 196, 247}
    assert forecast(mons[-1], cap).species == 248
    assert mons[-1].species == 247 and mons[-1].level == 53


def test_recover_can_outpace_damage_between_two_fifths_and_half_hp(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=249, level=70, moves=(105, 92, 89, 70), pp=(20, 10, 10, 15))
    snapshot = SimpleNamespace(enemy_species=143, enemy_level=70, enemy_hp=365)
    values = {'wBattleMonHP': 100, 'wBattleMonMaxHP': 245, 'wBattleMonDefense': 205, 'wEnemyMonAttack': 217}
    mem = SimpleNamespace(byte=lambda name: 0, word=lambda name: values.get(name, 30), read=lambda *args: bytes([157, 0, 0, 0]))
    assert policy.recovery_move(snapshot, mem, mon, [(50, 2)]) == 0


def test_evolution_item_closes_leftover_pc_dialogue():
    from pokesim.gen2.menus import Remedy
    snapshot = SimpleNamespace(items=((8, 1),), in_battle=0,
        text='The PC turned on.', tiles=(' ',) * 12 + ('┌──────────────────┐',) + (' ',) * 5)
    assert Remedy(8, 0, 1).step(snapshot, None) == 'b'


def test_evolution_stone_selects_the_compatible_party_member():
    from pokesim.gen2.menus import Remedy
    menu = Remedy(8, 5, 1, phase='party')
    rows = [' '] * 18
    rows[1], rows[2], rows[11], rows[12], rows[13] = '▶FERALIGATR', 'NOT ABLE', 'NIDORINA', 'ABLE', 'CANCEL'
    snapshot = SimpleNamespace(items=((8, 1),), text='\n'.join(rows), tiles=rows)
    assert menu.step(snapshot, None) == 'down'
    rows[1], rows[11] = 'FERALIGATR', '▶NIDORINA'
    snapshot.text = '\n'.join(rows)
    assert menu.step(snapshot, None) == 'a'


def test_tower_switches_away_from_a_lethal_fighting_matchup(real_data):
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.ram import calculated_stats
    policy = Policy(real_data)
    party = []
    for species, moves in [(248, (89, 157, 37, 242)), (249, (105, 92, 89, 70)), (196, (94, 247, 44, 36))]:
        stats = calculated_stats(real_data.species[species]['stats'], 70, (8,) * 5, (5000,) * 5)
        party.append(SimpleNamespace(species=species, level=70, moves=moves, pp=(10,) * 4, hp=stats[0], stats=stats, egg=False))
    snapshot = SimpleNamespace(enemy_species=68, enemy_level=70, enemy_hp=230, party=party)
    stats = {'wEnemyMonMaxHP': 230, 'wEnemyMonAttack': 250, 'wEnemyMonDefense': 170,
             'wEnemyMonSpeed': 140, 'wEnemyMonSpclAtk': 110, 'wEnemyMonSpclDef': 160}
    mem = SimpleNamespace(byte=lambda name: 0, word=stats.__getitem__, read=lambda *args: bytes([238, 0, 0, 0]))
    assert policy.tower_switch(snapshot, mem, 0) == 2
    assert policy.tower_switch(snapshot, mem, 2) is None
    snapshot.enemy_hp = 40
    party[0].stats = (*party[0].stats[:3], 150, *party[0].stats[4:])
    assert policy.tower_switch(snapshot, mem, 0) is None
    party[0].status = 64
    assert policy.tower_switch(snapshot, mem, 0) == 2
    party[1].hp = party[2].hp = 1
    assert policy.tower_switch(snapshot, mem, 0) is None


def test_boxed_tower_partner_with_an_hm_can_breed_its_missing_baby(real_data):
    from pokesim.gen2.breeding import journey
    from pokesim.gen2.policy import Goal
    magmar = SimpleNamespace(species=126, moves=(70, 94, 53, 7), egg=False, box=0, gender='Male',
        trainer_id=1, dvs=(0, 2, 4, 6, 8))
    ditto = SimpleNamespace(species=132, moves=(144,), egg=False, box=1, gender='Genderless',
        trainer_id=1, dvs=(0, 1, 3, 5, 7))
    lead = SimpleNamespace(species=157, egg=False, trainer_id=2, dvs=(1,) * 5)
    snapshot = SimpleNamespace(party=(lead,), stored=(magmar, ditto), daycare=(None, None),
        owned={126, 132, 157}, money=10000, egg_ready=False)
    policy = SimpleNamespace(data=real_data, collection={}, demand={},
        storage_goal=lambda snapshot: Goal('pc', 'Use the PC', 'OLIVINE_POKECENTER_1F', 9, 2, 'up'))
    assert journey(policy, snapshot, Goal).key == 'collection_breed_pc'
    assert policy.collection['breeding']['target'] == 240


def test_tower_uses_poison_against_counter_and_recovery(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    attacker = SimpleNamespace(species=248, level=70, moves=(89, 157, 37, 242), pp=(10,) * 4,
        hp=268, stats=(268, 250, 205, 150, 190, 190), egg=False)
    lugia = SimpleNamespace(species=249, level=70, moves=(105, 92, 89, 70), pp=(20, 10, 10, 15),
        hp=245, stats=(245, 143, 205, 170, 145, 234), egg=False)
    snapshot = SimpleNamespace(enemy_species=242, enemy_level=70, enemy_hp=495, party=(attacker, lugia))
    stats = {'wEnemyMonMaxHP': 495, 'wEnemyMonAttack': 77, 'wEnemyMonDefense': 80,
             'wEnemyMonSpeed': 143, 'wEnemyMonSpclAtk': 166, 'wEnemyMonSpclDef': 250}
    status = [0]
    mem = SimpleNamespace(byte=lambda name: status[0], word=stats.__getitem__, read=lambda *args: bytes([68, 135, 247, 85]))
    assert policy.tower_switch(snapshot, mem, 0) == 1
    status[0] = 8
    assert policy.recovery_move(snapshot, mem, lugia, [(15, 2)]) == 0


def test_tower_damage_estimate_uses_the_opponents_actual_defense(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=248, level=70, stats=(268, 250, 205, 150, 190, 190))
    snapshot = SimpleNamespace(enemy_species=242, enemy_level=70, enemy_hp=495)
    values = {'wEnemyMonDefense': 80, 'wEnemyMonSpclDef': 250}
    observed = policy.battle_target(snapshot, SimpleNamespace(word=values.__getitem__))
    assert policy.move_score(157, mon, observed) < policy.move_score(157, mon, snapshot) / 2


def test_burn_reduces_physical_but_not_special_attack_estimates(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data)
    mon = SimpleNamespace(species=248, level=70, stats=(268, 250, 205, 150, 190, 190), status=0)
    target = SimpleNamespace(enemy_species=242, enemy_level=70, enemy_hp=495)
    physical = policy.move_score(157, mon, target)
    special = policy.move_score(242, mon, target)
    mon.status = 16
    assert policy.move_score(157, mon, target) < physical * 0.6
    assert policy.move_score(242, mon, target) == special


def test_tower_leads_with_its_poison_and_recovery_partner(real_data):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2.menus import Lead
    policy = Policy(real_data)
    policy.memory = None
    party = []
    for index, (species, moves, stats) in enumerate([
        (248, (89, 157, 37, 242), (268, 250, 205, 150, 190, 190)),
        (249, (105, 92, 89, 70), (245, 143, 205, 170, 145, 234)),
        (196, (94, 247, 44, 36), (212, 150, 140, 194, 215, 166))]):
        party.append(SimpleNamespace(species=species, level=70, moves=moves, stats=stats, held_item=0,
            trainer_id=1, dvs=(index,) * 5, to_dict=lambda index=index: {'trainer_id': 1, 'dvs': [index] * 5}))
    policy.collection['tower'] = {'team': [tower.key(mon) for mon in party], 'original': [], 'cap': 70,
        'entered': False, 'returning': False, 'trained': True, 'preparation_center': True}
    snapshot = SimpleNamespace(map=real_data.map_ids['OLIVINE_POKECENTER_1F'], party=tuple(party), items=(), x=9, y=2)
    assert tower.journey(policy, snapshot, Goal).key == 'tower_lead'
    assert isinstance(policy.menu, Lead) and policy.menu.slot == 1


def test_tower_berry_respects_native_daily_flags_and_bag_capacity(real_data, monkeypatch):
    if real_data.game != 'crystal':
        return
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal
    values = {'wDailyFlags1': 16, 'wFruitTreeFlags': 0}
    monkeypatch.setattr(tower, 'Memory', lambda *args: SimpleNamespace(byte=lambda name, *args: values[name]))
    policy = SimpleNamespace(data=real_data, collection={}, decisions=0, memory=None, person=lambda *args: 'berry')
    snapshot = SimpleNamespace(event=lambda name: True, items=(), pockets={'items': ()}, party=(), stored=())
    assert tower.journey(policy, snapshot, Goal, force=True) == 'berry'
    values['wFruitTreeFlags'] = 1
    assert tower.journey(policy, snapshot, Goal, force=True) is None
    values['wDailyFlags1'] = 0
    assert tower.journey(policy, snapshot, Goal, force=True) == 'berry'
    snapshot.pockets['items'] = tuple(range(20))
    assert tower.journey(policy, snapshot, Goal, force=True) is None
