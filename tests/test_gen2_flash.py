import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import flash
from pokesim.gen2.menus import FieldMove

DARK, LIT_MAP = 1, 2
DATA = SimpleNamespace(maps={DARK: {'palette': 'PALETTE_DARK'}, LIT_MAP: {'palette': 'PALETTE_AUTO'}})


def mon(*moves, egg=False):
    return SimpleNamespace(species=152, egg=egg, moves=moves)


def policy(allowed=True):
    return SimpleNamespace(data=DATA, flash_map=None, allowed=lambda task, snapshot: allowed)


def snapshot(map_id=DARK, party=(mon(33, 45), mon(33, flash.FLASH)), badges=1, lit=False):
    return SimpleNamespace(map=map_id, party=party, badges=badges, flash=lit)


def test_flash_is_used_once_on_entering_a_dark_map():
    owner = policy()
    assert flash.task(owner, snapshot()) == FieldMove(1, 'FLASH')
    # A refusal or a menu that closed early is not retried on the same map, so the walk goes on dark.
    assert flash.task(owner, snapshot()) is None
    assert flash.task(owner, snapshot(LIT_MAP)) is None
    assert flash.task(owner, snapshot()) == FieldMove(1, 'FLASH')


def test_flash_is_not_used_where_it_is_lit_or_cannot_be_used():
    assert flash.task(policy(), snapshot(LIT_MAP)) is None
    # Flash already lights the cave, for example on a connected floor.
    assert flash.task(policy(), snapshot(lit=True)) is None
    # The game refuses Flash before the Zephyr Badge.
    assert flash.task(policy(), snapshot(badges=0)) is None
    assert flash.task(policy(allowed=False), snapshot()) is None


def test_a_party_without_flash_walks_the_cave_dark():
    assert flash.task(policy(), snapshot(party=(mon(33, 45),))) is None
    assert flash.task(policy(), snapshot(party=(mon(33), mon(flash.FLASH, egg=True)))) is None


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_dark_maps_come_from_the_map_palette(real_data):
    darks = {real_data.maps[number]['constant'] for number in real_data.maps if flash.dark(real_data, number)}
    assert {'DARK_CAVE_VIOLET_ENTRANCE', 'ROCK_TUNNEL_1F', 'SILVER_CAVE_ROOM_1', 'WHIRL_ISLAND_B1F'} <= darks
    assert not darks & {'VIOLET_CITY', 'SPROUT_TOWER_3F', 'UNION_CAVE_1F', 'SILVER_CAVE_ROOM_2', 'ICE_PATH_1F'}
    # Mount Mortar is dark in Gold and Silver only.
    assert ('MOUNT_MORTAR_1F_OUTSIDE' in darks) == (real_data.game != 'crystal')


def test_flash_is_fetched_after_falkner_only_while_the_road_is_in_violet(real_data):
    from pokesim.gen2.policy import Policy
    owner = Policy(real_data, starter='cyndaquil')
    owner.story_step = lambda snapshot, key, title, row=None: SimpleNamespace(key=key)
    before_story = {'EVENT_GOT_A_POKEMON_FROM_ELM', 'EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON', 'EVENT_GAVE_MYSTERY_EGG_TO_ELM'}

    def key(*events):
        state = SimpleNamespace(frame=100, badges=1, party=[], map=real_data.map_ids['VIOLET_CITY'],
                                hall_of_fame_count=0, event=lambda flag: flag in before_story | set(events))
        return owner.story(state, None).key

    assert key() == 'flash'
    assert key('EVENT_GOT_HM05_FLASH') == 'togepi'
    assert owner.completed['flash'] == 100
    # A game already past Violet City never walks back for Flash.
    assert key('EVENT_GOT_TOGEPI_EGG_FROM_ELMS_AIDE') != 'flash'


def test_the_flash_step_reaches_elder_li(real_data):
    from pokesim.story import row
    found = row(2, real_data.game, 'flash')
    assert (found['map'], found['object']) == ('SPROUT_TOWER_3F', 'SageLiScript')
