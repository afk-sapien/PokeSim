"""Gen II decoding on synthetic banked memory. No cartridge data is used."""
import copy
import random
from collections import defaultdict
from types import SimpleNamespace

from pokecore import gen2
from pokecore.gen2 import charmap, memory_map, ram
from pokecore.gen2.ram import read_snapshot

# A synthetic Gen II layout: every symbol read_snapshot reads, placed in fake banked memory.
SYMBOLS = {'wPartyCount': 1, 'wPartySpecies': 7, 'wPartyMons': 288, 'wPartyMonNicknames': 66, 'wCurBox': 1,
           'wNumItems': 41, 'wNumBalls': 25, 'wNumKeyItems': 27, 'wTMsHMs': 57, 'wObjectStructs': 520,
           'wMapGroup': 1, 'wMapNumber': 1, 'wEventFlags': 256, 'wMapObjects': 256, 'wPokedexSeen': 32,
           'wPokedexCaught': 32, 'wDayCareMan': 1, 'wDayCareLady': 1, 'wBreedMon1': 32, 'wBreedMon1Nickname': 11,
           'wBreedMon2': 32, 'wBreedMon2Nickname': 11, 'wRoamMon1': 7, 'wRoamMon2': 7, 'wRoamMon3': 7,
           'wBattleMode': 1, 'wTilemap': 360, 'wXCoord': 1, 'wYCoord': 1, 'wPlayerName': 11, 'wRivalName': 11,
           'wJohtoBadges': 1, 'wKantoBadges': 1, 'wMoney': 3, 'wCoins': 2, 'wEnemyMonSpecies': 1,
           'wEnemyMonLevel': 1, 'wEnemyMonHP': 2, 'wEnemyMonMaxHP': 2, 'wTrainerClass': 1, 'wBattleType': 1,
           'wGameTimeHours': 2, 'wGameTimeMinutes': 1, 'wGameTimeSeconds': 1, 'wHallOfFameCount': 1,
           'wStepCount': 1, 'wHappinessStepCount': 1, 'wEnemyMonDVs': 2, 'wEnemyBackupDVs': 2, 'wEnemySubStatus5': 1}


def synthetic_data():
    symbols, address = {}, 0xD000
    for name, size in SYMBOLS.items():
        symbols[name] = (1, address)
        address += size
    assert address <= 0xE000
    symbols['sBox'] = (1, 0xA000)
    for box in range(14):
        symbols[f'sBox{box + 1}'] = (2 + box // 7, 0xA000 + box % 7 * 1102)
    species = {str(i): {'name': f'Species {i}', 'stats': [40 + i % 60] * 6, 'types': [i % 17],
                        'gender_ratio': i % 256, 'growth': 'MEDIUM_FAST'} for i in range(1, 252)}
    moves = {str(i): {'name': f'Move {i}', 'pp': 5 + i % 35, 'type': i % 17} for i in range(1, 252)}
    table = {str(i): chr(0x41 + i % 26) for i in range(0x80, 0xFA)}
    return gen2.GameTables({'game': 'gold', 'species': species, 'moves': moves, 'maps': {}, 'charmap': table,
                            'item_attributes': {}, 'items': {}, 'types': {f'T{i}': i for i in range(17)},
                            'events': {}, 'map_ids': {}, 'symbols': symbols, 'collisions': {}, 'permissions': {}})


class BankedMemory:
    def __init__(self):
        self.banks = defaultdict(lambda: bytearray(65536))

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def __setitem__(self, key, value):
        bank, address = key if isinstance(key, tuple) else (0, key)
        self.banks[bank][address] = value


def fill(memory, data, rng):
    for name, (bank, address) in data.symbols.items():
        size = 1102 if name.startswith('sBox') else SYMBOLS[name]
        memory.banks[bank][address:address + size] = rng.randbytes(size)
    memory.banks[1][data.symbols['wPartyCount'][1]] = rng.randrange(7)
    memory.banks[1][data.symbols['wCurBox'][1]] = rng.randrange(14)
    for name, (bank, address) in data.symbols.items():
        if name.startswith('sBox'):
            memory.banks[bank][address] = rng.randrange(21)
    bank, address = data.symbols['wPartyMons']
    for slot in range(6):
        memory.banks[bank][address + slot * 48] = rng.randrange(1, 252)
        memory.banks[bank][address + slot * 48 + 31] = rng.randrange(1, 101)


def test_cached_regions_equal_a_fresh_decode():
    data, rng, memory = synthetic_data(), random.Random(21), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, rng)
    for step in range(40):
        cached = read_snapshot(memory, data, step)
        assert cached == read_snapshot(memory, data, step, cache=False)
        assert cached.to_dict() == read_snapshot(memory, data, step, cache=False).to_dict()
        assert repr(cached) == repr(read_snapshot(memory, data, step, cache=False))
        bank, address = data.symbols[rng.choice(list(data.symbols))]
        for _ in range(rng.randrange(1, 4)):
            memory.banks[bank][address + rng.randrange(64)] = rng.randrange(256)
        if step % 10 == 9:
            fill(memory, data, rng)


def test_unchanged_regions_reuse_their_decoded_objects():
    data, memory = synthetic_data(), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, random.Random(4))
    first, second = read_snapshot(memory, data), read_snapshot(memory, data)
    assert first.party and first.stored
    assert all(a is b for a, b in zip(first.party + first.stored, second.party + second.stored))
    assert first.tiles is second.tiles and first.seen is second.seen
    bank, address = data.symbols['sBox5']
    memory.banks[bank][address + 22 + 31] ^= 1
    third = read_snapshot(memory, data)
    assert third == read_snapshot(memory, data, cache=False)
    assert [mon for mon in third.stored if mon.box != 4] == [mon for mon in first.stored if mon.box != 4]
    assert all(a is b for a, b in zip(first.party, third.party))


def test_region_cache_is_keyed_on_the_game_data():
    data, other, memory = synthetic_data(), synthetic_data(), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, random.Random(8))
    first = read_snapshot(memory, data)
    second = read_snapshot(memory, other)
    assert all(mon.data is other for mon in second.party + second.stored)
    assert second == read_snapshot(memory, other, cache=False)
    assert first.party and first.party[0] is not second.party[0]


def test_memory_maps_place_known_symbols():
    gold, crystal = memory_map.symbols('gold'), memory_map.symbols('crystal')
    assert memory_map.symbols('silver') is gold
    assert gold['wPlayerName'] == (1, 0xD1A3) and gold['wPartyCount'] == (1, 0xDA22)
    assert crystal['wPlayerName'] == (1, 0xD47D) and crystal['wPartyCount'] == (1, 0xDCD7)
    assert 'wPlayerGender' in memory_map.CRYSTAL_ONLY and 'wPlayerGender' not in gold
    assert gold['sBox1'] == crystal['sBox1'] == (2, 0xA000)
    for table in (gold, crystal):
        assert all(name in table for name in SYMBOLS)
        assert all(0 <= bank < 8 and 0x8000 <= address <= 0xFFFF for bank, address in table.values())
    try:
        memory_map.symbols('red')
    except ValueError:
        pass
    else:
        raise AssertionError('unknown versions are rejected')


def test_charmaps_and_text():
    assert charmap.charmap('gold')[0x80] == 'A' and charmap.charmap('crystal')[0x80] == 'A'
    assert set(charmap.CRYSTAL_DIFFERENCES) == {0x14, 0x15}
    name = bytes((0x87, 0x88, 0x50, 0x80))
    assert gen2.decode_text(name, 'gold') == 'HI' == gen2.GameTables({'game': 'crystal'}).text(name)


def test_game_tables_default_to_core_maps():
    tables = gen2.GameTables({'game': 'crystal', 'items': {'POTION': 18, 'TM_FOCUS_PUNCH': 191},
                              'types': {'PSYCHIC_TYPE': 24}})
    assert tables.symbols['wPartyCount'] == (1, 0xDCD7)
    assert tables.item_names == {18: 'Potion'} and tables.type_names == {24: 'Psychic'}
    assert gen2.pretty('POKECENTER_2F') == 'Pokémon Center 2F'


def test_live_status_without_data():
    status = gen2.live_status({'party': [{'species': 1}], 'player_name': 'GOLD'}, {'version': 'gold'})
    assert status['started'] and status['version'] == 'gold' and status['generation'] == 2
    assert status['party'] == [{'species': 1, 'battle_power': None, 'slot': 1}]
    assert gen2.live_status(None)['started'] is False and gen2.live_status(None)['version'] == 'crystal'


def test_screens():
    assert gen2.has_word('Wild PIDGEY appeared', 'PIDGEY')
    assert not gen2.has_word('PIDGEYOTTO', 'PIDGEY')
    assert 'CANCEL' not in gen2.ScreenText('CANCELLA') and 'CANCEL' in gen2.ScreenText('▶CANCEL')
    rows = tuple(' ' * 20 for _ in range(18))
    assert gen2.mask_hud(rows) == rows


def test_mon_shiny_and_gender():
    data = SimpleNamespace(species={1: {'stats': [45] * 6, 'gender_ratio': 31}}, moves={}, text=lambda raw: '')
    raw = bytearray(32)
    raw[0], raw[31] = 1, 5
    raw[21], raw[22] = 0xAA, 0xAA
    mon = gen2.decode_mon(bytes(raw), b'', data)
    assert mon.shiny and mon.dvs == (0, 10, 10, 10, 10) and mon.gender == 'Male'
    assert gen2.decode_mon(bytes(32), b'', data) is None


def test_mon_keeps_the_stored_nickname_bytes():
    # WETFUND<CONT>ll: a traded nickname holding 0x55 stays visible to callers.
    data = SimpleNamespace(species={1: {'stats': [45] * 6, 'gender_ratio': 31}}, moves={}, text=lambda raw: '')
    name = bytes([0x96, 0x84, 0x93, 0x85, 0x94, 0x8D, 0x83, 0x55, 0x8B, 0x8B, 0x50])
    raw = bytearray(32)
    raw[0], raw[31] = 1, 5
    mon = gen2.decode_mon(bytes(raw), name, data)
    assert mon.nick_bytes == name and 'nick_bytes' not in mon.to_dict()


def test_version_of_rejects_unknown_roms():
    try:
        gen2.version_of(bytes(32 * 16384))
    except ValueError:
        pass
    else:
        raise AssertionError('unknown ROMs are rejected')


# Ported from PokeSim's PC detail, shiny and Day Care tests.

ROUTE_30_MAPS = {1: {'landmark': 4, 'environment': 'INDOOR', 'name': 'Route 30 Berry House'},
                 2: {'landmark': 4, 'environment': 'ROUTE', 'name': 'Route 30'},
                 3: {'landmark': 10, 'environment': 'CAVE', 'name': 'Union Cave B1F'}}


def test_crystal_caught_data_names_events_gifts_and_unknown_places():
    data = SimpleNamespace(maps=ROUTE_30_MAPS)
    assert gen2.caught_details((3 << 14) | (7 << 8) | 4, data) == {'level': 7, 'time': 'Night', 'location': 'Route 30'}
    assert gen2.caught_details((1 << 14) | (2 << 8) | 0x80 | 10, data)['location'] == 'Union Cave'
    assert gen2.caught_details(0x7F, data) == {'level': None, 'time': None, 'location': 'Event'}
    assert gen2.caught_details(0x7E, data)['location'] == 'Gift'
    assert gen2.caught_details(0, data) == {'level': None, 'time': None, 'location': None}
    assert gen2.landmark_name(data, 10) == 'Union Cave' and gen2.landmark_name(data, 99) is None
    assert gen2.landmark_name(SimpleNamespace(), 4) is None


def tables(game):
    species = {str(i): {'name': f'Species {i}', 'stats': [50] * 6, 'types': [i % 17], 'gender_ratio': 127,
                        'growth': 'MEDIUM_FAST'} for i in range(1, 252)}
    moves = {'33': {'name': 'Tackle', 'pp': 35, 'type': 0, 'power': 35, 'accuracy': 95},
             '237': {'name': 'Hidden Power', 'pp': 15, 'type': 0, 'power': 1, 'accuracy': 100}}
    return gen2.GameTables({'game': game, 'species': species, 'moves': moves, 'types': {'NORMAL': 0},
                            'maps': {str(key): value for key, value in ROUTE_30_MAPS.items()}})


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


def test_decoded_mons_carry_pokerus_caught_data_move_power_and_egg_cycles():
    crystal, name = tables('crystal'), bytes([0x50] * 11)
    partner = gen2.decode_mon(raw_mon(121, 30, pokerus=0x21, caught=(2 << 14) | (12 << 8) | 4), name, crystal,
                              box=0, position=0)
    assert (partner.pokerus, partner.caught) == (0x21, (2 << 14) | (12 << 8) | 4)
    view = partner.to_dict()
    assert view['pokerus'] == 'infected' and view['caught'] == {'level': 12, 'time': 'Day', 'location': 'Route 30'}
    assert view['move_details'][0] == {'id': 237, 'name': 'Hidden Power', 'type': 'Normal', 'pp': 15, 'max_pp': 15,
                                       'power': 1, 'accuracy': 100}
    assert view['move_details'][1]['power'] == 35 and 'egg_cycles' not in view
    cured = gen2.decode_mon(raw_mon(121, 30, pokerus=0x20), name, crystal).to_dict()
    assert cured['pokerus'] == 'cured' and 'caught' not in cured
    assert gen2.decode_mon(raw_mon(121, 30), name, crystal).to_dict()['pokerus'] is None
    # Gold and Silver have no caught data, so the bytes are never read as such.
    gold = gen2.decode_mon(raw_mon(121, 30, caught=(2 << 14) | (12 << 8) | 4), name, tables('gold')).to_dict()
    assert 'caught' not in gold
    egg = gen2.decode_mon(raw_mon(215, 5, friendship=20), name, crystal, egg=True, box=0, position=1).to_dict()
    assert egg['egg_cycles'] == 20


def test_the_egg_view_is_opt_in():
    crystal, name = tables('crystal'), bytes([0x50] * 11)
    egg = gen2.decode_mon(raw_mon(215, 5, friendship=20), name, crystal, egg=True)
    # The default keeps Core 0.6.0 values: an egg reports the species inside it.
    plain = egg.to_dict()
    assert (plain['dex'], plain['name'], plain['types'], plain['type_names']) == (215, 'Species 215', [215 % 17], ['Normal'])
    masked = egg.to_dict(egg_view=True)
    assert (masked['dex'], masked['name'], masked['types'], masked['type_names']) == (None, 'Egg', [], [])
    assert masked['species'] == 215 and masked['egg'] and masked['egg_cycles'] == 20
    assert {key: value for key, value in masked.items() if key not in ('dex', 'name', 'types', 'type_names')} == {
        key: value for key, value in plain.items() if key not in ('dex', 'name', 'types', 'type_names')}
    hatched = gen2.decode_mon(raw_mon(215, 5), name, crystal)
    assert hatched.to_dict(egg_view=True) == hatched.to_dict()


def test_the_snapshot_egg_view_reaches_party_and_storage():
    data, memory = synthetic_data(), BankedMemory()
    ram.clear_region_cache()
    fill(memory, data, random.Random(3))
    bank, address = data.symbols['wPartyCount']
    memory.banks[bank][address] = 2
    bank, address = data.symbols['wPartySpecies']
    memory.banks[bank][address + 1] = 0xFD
    bank, address = data.symbols['sBox']
    memory.banks[bank][address], memory.banks[bank][address + 1] = 1, 0xFD
    memory.banks[bank][address + 22] = 9
    memory.banks[bank][address + 22 + 31] = 5
    snapshot = read_snapshot(memory, data)
    assert snapshot.party[1].egg and any(mon.egg for mon in snapshot.stored)
    plain, masked = snapshot.to_dict(), snapshot.to_dict(egg_view=True)
    assert plain['party'][1]['dex'] == snapshot.party[1].species and masked['party'][1]['dex'] is None
    assert [mon['name'] for mon in masked['storage']['pokemon'] if mon['egg']] == ['Egg']
    assert masked['party'][0] == plain['party'][0]


SHINY, PLAIN = b'\x2a\xaa', b'\xff\xff'


def put(memory, data, name, value):
    bank, address = data.symbols[name]
    value = bytes([value]) if isinstance(value, int) else value
    memory.banks[bank][address:address + len(value)] = value


def battle(data, *, mode=1, dvs=SHINY):
    memory = BankedMemory()
    for name, value in (('wBattleMode', mode), ('wBattleType', 7), ('wEnemyMonSpecies', 132), ('wEnemyMonDVs', dvs)):
        put(memory, data, name, value)
    return memory


def test_a_wild_shiny_is_reported_and_trainer_pokemon_are_not():
    data = synthetic_data()
    assert read_snapshot(battle(data), data, cache=False).enemy_shiny
    assert read_snapshot(battle(data), data, cache=False).to_dict()['enemy_shiny'] is True
    assert not read_snapshot(battle(data, dvs=PLAIN), data, cache=False).enemy_shiny
    assert not read_snapshot(battle(data, mode=2), data, cache=False).enemy_shiny
    assert not read_snapshot(battle(data, mode=0), data, cache=False).enemy_shiny


def test_transformed_ditto_reports_its_own_dvs():
    data = synthetic_data()
    memory = battle(data, dvs=PLAIN)
    put(memory, data, 'wEnemyBackupDVs', SHINY)
    assert not read_snapshot(memory, data, cache=False).enemy_shiny
    put(memory, data, 'wEnemySubStatus5', 8)
    assert read_snapshot(memory, data, cache=False).enemy_shiny
    # A shiny target seen through Transform does not make a plain Ditto shiny.
    put(memory, data, 'wEnemyMonDVs', SHINY)
    put(memory, data, 'wEnemyBackupDVs', PLAIN)
    assert not read_snapshot(memory, data, cache=False).enemy_shiny
    put(memory, data, 'wBattleMode', 2)
    assert not read_snapshot(memory, data, cache=False).enemy_shiny


def test_memory_maps_place_the_transform_backup_dvs():
    assert memory_map.symbols('gold')['wEnemyBackupDVs'] == (0, 0xCBD0)
    assert memory_map.symbols('crystal')['wEnemyBackupDVs'] == (0, 0xC6F2)


def test_enemy_shiny_falls_back_when_the_symbol_table_lacks_transform_symbols():
    data = synthetic_data()
    memory = battle(data)
    put(memory, data, 'wEnemySubStatus5', 8)
    put(memory, data, 'wEnemyBackupDVs', PLAIN)
    for missing in ('wEnemyBackupDVs', 'wEnemySubStatus5'):
        symbols = {name: value for name, value in data.symbols.items() if name != missing}
        partial = copy.copy(data)
        partial.symbols = symbols
        # Without the backup or the substatus, the DVs on show decide.
        assert read_snapshot(memory, partial, cache=False).enemy_shiny is True


def test_enemy_shiny_is_unknown_without_any_enemy_dvs():
    data = synthetic_data()
    memory = battle(data)
    symbols = {name: value for name, value in data.symbols.items()
               if name not in {'wEnemyMonDVs', 'wEnemyBackupDVs', 'wEnemySubStatus5'}}
    partial = copy.copy(data)
    partial.symbols = symbols
    snapshot = read_snapshot(memory, partial, cache=False)
    assert snapshot.enemy_shiny is None and snapshot.to_dict()['enemy_shiny'] is None
    # Outside a wild battle there is nothing to judge, so the answer stays False.
    put(memory, data, 'wBattleMode', 2)
    assert read_snapshot(memory, partial, cache=False).enemy_shiny is False
