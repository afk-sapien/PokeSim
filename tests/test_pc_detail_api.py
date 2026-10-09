"""The PC detail popup reads moves, experience and Gen II extras from /api/pokedex/status."""
import os
from types import SimpleNamespace

import pytest

from pokesim.ram import PartyMon, Snapshot, StoredMon
from pokesim.web.pokedex import live_status


def gen1_snapshot():
    party = (PartyMon(153, 12, 30, 15, 'LEAF', moves=(22, 33, 0, 0), pp=(3, 35, 0, 0), max_pp=(16, 35, 0, 0),
                      experience=2300, dvs=(8,) * 5, stat_exp=(0,) * 5, trainer_id=100),)
    boxed = (StoredMon(0, 0, 153, 20, 'BUD', (33, 45, 0, 0), 6000, (1,) * 5, (0,) * 5, 100,
                       hp=31, status=0, pp=(20, 0, 0, 0), max_pp=(35, 40, 0, 0)),)
    return Snapshot(frame=1, map=1, x=1, y=1, badges=0, party=party, owned=frozenset(), seen=frozenset(),
                    money=0, items=(), in_battle=0, battle_type=0, enemy_species=0, enemy_level=0, opponent=0,
                    player_name='RED', rival_name='BLUE', playtime=(0, 0, 0), textbox=False, start_menu=False,
                    stored_details=boxed, stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in boxed),
                    box_counts=(1,) + (0,) * 11)


def test_gen1_party_and_boxes_carry_move_details_and_level_progress():
    status = live_status(gen1_snapshot().to_dict())
    lead = status['party'][0]
    assert lead['move_details'][0] == {'name': 'Vine Whip', 'type': 'Grass', 'power': 35, 'accuracy': 100,
                                       'pp': 3, 'max_pp': 16}
    assert lead['experience'] == 2300
    assert lead['experience_progress']['remaining'] == 235
    boxed = status['storage']['pokemon'][0]
    assert [move['name'] for move in boxed['move_details']] == ['Tackle', 'Growl']
    assert boxed['move_details'][0]['pp'] == 20 and boxed['move_details'][0]['max_pp'] == 35
    assert boxed['move_details'][1] == {'name': 'Growl', 'type': 'Normal', 'power': 0, 'accuracy': 100,
                                        'pp': 0, 'max_pp': 40}
    # Bulbasaur 45 base HP, HP DV 1, no stat exp, level 20: (46 * 2) * 20 // 100 + 30.
    assert boxed['max_hp'] == 48 and boxed['hp'] == 31 and boxed['status_label'] == 'Healthy'
    assert boxed['experience'] == 6000
    assert boxed['experience_progress']['total'] == 6000 and not boxed['experience_progress']['max_level']


def test_gen1_box_records_decode_current_hp_status_and_pp_ups():
    from pokesim.ram import _decode_box
    raw = bytearray(33)
    raw[0], raw[3], raw[4] = 153, 20, 8          # Bulbasaur (internal 153), level 20, poisoned
    raw[1:3] = (12).to_bytes(2, 'big')
    raw[8:10] = bytes((33, 45))                 # Tackle, Growl
    raw[27:29] = bytes((0x11, 0x11))           # HP DV 15: (60 * 2) * 20 // 100 + 30 = 54
    raw[29], raw[30] = 0x80 | 30, 0x40 | 7      # two PP Ups on Tackle, one on Growl
    _decode_box.cache_clear()
    mon = _decode_box(0, bytes(raw), bytes([0x50] * 11))[0]
    assert mon.hp == 12 and mon.status == 8 and mon.pp == (30, 7, 0, 0)
    assert mon.max_pp == (35 + 7 * 2, 40 + 7, 0, 0)  # each PP Up adds at most 7
    row = live_status(Snapshot(**{**gen1_snapshot().__dict__, 'stored_details': (mon,),
                                  'stored_pokemon': ((0, 153, 20, mon.nick),)}).to_dict())['storage']['pokemon'][0]
    assert row['hp'] == 12 and row['max_hp'] == 54 and row['status_label'] == 'Poisoned'
    assert [(move['pp'], move['max_pp']) for move in row['move_details']] == [(30, 49), (7, 47)]


def test_crystal_caught_data_names_events_gifts_and_unknown_places():
    from pokesim.gen2.ram import caught_details
    data = SimpleNamespace(maps={1: {'landmark': 4, 'environment': 'INDOOR', 'name': 'Route 30 Berry House'},
                                 2: {'landmark': 4, 'environment': 'ROUTE', 'name': 'Route 30'},
                                 3: {'landmark': 10, 'environment': 'CAVE', 'name': 'Union Cave B1F'}})
    assert caught_details((3 << 14) | (7 << 8) | 4, data) == {'level': 7, 'time': 'Night', 'location': 'Route 30'}
    assert caught_details((1 << 14) | (2 << 8) | 0x80 | 10, data)['location'] == 'Union Cave'
    assert caught_details(0x7F, data) == {'level': None, 'time': None, 'location': 'Event'}
    assert caught_details(0x7E, data)['location'] == 'Gift'


@pytest.fixture
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'crystal')


def raw_mon(species, level, *, pokerus=0, caught=0, friendship=70):
    raw = bytearray(32)
    raw[0], raw[2], raw[3], raw[31] = species, 237, 33, level
    raw[6:8] = (4321).to_bytes(2, 'big')
    raw[8:11] = (level ** 3).to_bytes(3, 'big')
    raw[21], raw[22] = 0xDA, 0xBC
    raw[23], raw[24] = 15, 35
    raw[27], raw[28] = friendship, pokerus
    raw[29:31] = caught.to_bytes(2, 'big')
    return bytes(raw)


def test_gen2_status_adds_hidden_power_pokerus_caught_data_and_egg_cycles(crystal):
    from pokesim.gen2.ram import decode_mon
    from pokesim.gen2.web import live_status as gen2_status
    name = [0x50] * 11
    partner = decode_mon(raw_mon(121, 30, pokerus=0x21, caught=(2 << 14) | (12 << 8) | 4), name, crystal, box=0, position=0)
    egg = decode_mon(raw_mon(215, 5, friendship=20), name, crystal, egg=True, box=0, position=1)
    rows = gen2_status({'party': [partner.to_dict(), egg.to_dict()]}, data=crystal)['party']
    mon = rows[0]
    assert mon['pokerus'] == 'infected' and mon['caught'] == {'level': 12, 'time': 'Day', 'location': 'Route 30'}
    assert mon['hidden_power']['type'] in {name.title() for name in crystal.types} | set(crystal.type_names.values())
    assert 31 <= mon['hidden_power']['power'] <= 70
    assert mon['move_details'][0]['name'] == 'Hidden Power' and mon['move_details'][1]['power'] == 35
    assert mon['friendship'] == 70 and mon['trainer_id'] == 4321
    assert rows[1]['egg_cycles'] == 20 and 'hidden_power' not in rows[1]
    cured = decode_mon(raw_mon(121, 30, pokerus=0x20), name, crystal).to_dict()
    assert cured['pokerus'] == 'cured' and 'caught' not in cured
