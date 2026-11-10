"""Table-free Gen II reads on synthetic memory laid out by Core's own memory maps."""
from collections import defaultdict

import pytest

from pokecore.gen2 import memory_map, state


class BankedMemory:
    def __init__(self, version):
        self.banks = defaultdict(lambda: bytearray(65536))
        self.symbols = memory_map.symbols(version)

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def put(self, name, data, offset=0):
        bank, address = self.symbols[name]
        self.banks[bank][address + offset:address + offset + len(data)] = bytes(data)


def text(value):
    return bytes(0x80 + ord(c) - ord('A') for c in value) + b'\x50'


def struct(species, level, *, party=True, item=0, dvs=(0xAA, 0xAA), pokerus=0, caught=(0, 0), friendship=70):
    raw = bytearray(48 if party else 32)
    raw[0], raw[1], raw[2:6] = species, item, bytes((33, 45, 0, 0))
    raw[6:8] = (12345).to_bytes(2, 'big')
    raw[8:11] = (level ** 3).to_bytes(3, 'big')
    raw[11:13] = (500).to_bytes(2, 'big')
    raw[21], raw[22] = dvs
    raw[23:27] = bytes((35 | 0x40, 40, 0, 0))
    raw[27], raw[28] = friendship, pokerus
    raw[29], raw[30] = caught
    raw[31] = level
    if party:
        raw[32], raw[34:36] = 0, (20).to_bytes(2, 'big')
        raw[36:48] = b''.join(value.to_bytes(2, 'big') for value in (21, 11, 12, 13, 14, 15))
    return bytes(raw)


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_party_and_boxes(version):
    memory = BankedMemory(version)
    memory.put('wPartyCount', [2])
    memory.put('wPartySpecies', [152, 0xFD, 0xFF])
    memory.put('wPartyMons', struct(152, 5, item=7, pokerus=0x23, caught=(0x85, 0x83))
               + struct(175, 1, dvs=(0x12, 0x34), friendship=10))
    memory.put('wPartyMonNicknames', text('CHIKO').ljust(11, b'\x50') + text('EGG').ljust(11, b'\x50'))
    memory.put('wPartyMonOTs', text('KRIS').ljust(22, b'\x50'))
    party = state.read_party_structs(memory, version)
    first, egg = party
    assert first['species'] == 152 and first['level'] == 5 and first['held_item'] == 7
    assert first['nickname'] == 'CHIKO' and first['ot_name'] == 'KRIS' and first['trainer_id'] == 12345
    assert first['shiny'] and first['dvs'] == (0, 10, 10, 10, 10) and first['stat_exp'][0] == 500
    assert first['pp'] == (35, 40, 0, 0) and first['pp_ups'] == (1, 0, 0, 0)
    assert first['pokerus'] == {'strain': 2, 'days': 3, 'infected': True, 'cured': False}
    assert first['hp'] == 20 and first['stats'] == (21, 11, 12, 13, 14, 15)
    if version == 'crystal':
        assert first['caught'] == {'time': 'day', 'level': 5, 'trainer_gender': 'Female', 'location': 3}
    else:
        assert first['caught'] is None
    assert egg['egg'] and egg['egg_cycles'] == 10 and not egg['shiny'] and egg['dvs'] == (10, 1, 2, 3, 4)

    memory.put('wCurBox', [3])
    box = bytearray(1102)
    box[0], box[1:3] = 1, bytes((19, 0xFF))
    box[22:54] = struct(19, 9, party=False)
    box[22 + 32 * 20:22 + 32 * 20 + 6] = text('GOLD')
    box[22 + 43 * 20:22 + 43 * 20 + 6] = text('RAT')
    memory.put('sBox', box)
    memory.put('sBox1', [4])
    (rat,) = state.read_box_structs(memory, version)
    assert rat['species'] == 19 and rat['nickname'] == 'RAT' and rat['ot_name'] == 'GOLD' and 'hp' not in rat
    assert [mon['species'] for mon in state.read_box_structs(memory, version, 0)] == [0] * 4
    assert state.read_box_counts(memory, version) == ((4, 0, 0, 1) + (0,) * 10, 3)
    with pytest.raises(ValueError):
        state.read_box_structs(memory, version, 14)
    with pytest.raises(ValueError):
        state.decode_struct(b'\x00' * 31, version)


@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_items_player_dex_clock_daycare(version):
    memory = BankedMemory(version)
    memory.put('wNumItems', [2, 18, 3, 0x20, 1, 0xFF])
    memory.put('wNumBalls', [1, 5, 10, 0xFF])
    memory.put('wNumKeyItems', [2, 7, 9, 0xFF])
    memory.put('wNumPCItems', [1, 18, 99, 0xFF])
    memory.put('wTMsHMs', [1] + [0] * 55 + [1])
    items = state.read_items(memory, version)
    assert items['items'] == ((18, 3), (0x20, 1)) and items['balls'] == ((5, 10),)
    assert items['key'] == ((7, 1), (9, 1)) and items['pc'] == ((18, 99),)
    assert items['tms_hms'][0] == 1 and items['tms_hms'][56] == 1 and len(items['tms_hms']) == 57

    memory.put('wPlayerName', text('KRIS'))
    memory.put('wRivalName', text('SILVER'))
    memory.put('wPlayerID', (54321).to_bytes(2, 'big'))
    memory.put('wJohtoBadges', [0b101])
    memory.put('wKantoBadges', [0b1])
    memory.put('wMoney', (123456).to_bytes(3, 'big'))
    memory.put('wMomsMoney', (2000).to_bytes(3, 'big'))
    memory.put('wCoins', (99).to_bytes(2, 'big'))
    memory.put('wMapGroup', [24])
    memory.put('wMapNumber', [4])
    memory.put('wXCoord', [3])
    memory.put('wYCoord', [7])
    memory.put('wPlayerDirection', [4])
    memory.put('wPlayerState', [1])
    memory.put('wGameTimeHours', (12).to_bytes(2, 'big'))
    memory.put('wGameTimeMinutes', [34])
    if version == 'crystal':
        memory.put('wPlayerGender', [1])
    player = state.read_player(memory, version)
    assert player['name'] == 'KRIS' and player['rival_name'] == 'SILVER' and player['trainer_id'] == 54321
    assert player['gender'] == ('Female' if version == 'crystal' else 'Male')
    assert player['badges'] == ['Zephyr', 'Plain', 'Boulder'] and player['money'] == 123456
    assert player['moms_money'] == 2000 and player['coins'] == 99
    assert player['map'] == 24 * 256 + 4 and (player['x'], player['y']) == (3, 7)
    assert player['facing'] == 'up' and player['state'] == 'bike' and player['playtime'] == (12, 34, 0)

    memory.put('wPokedexSeen', [0b11] + [0] * 30 + [0x04])
    memory.put('wPokedexCaught', [0b10])
    memory.put('wUnownDex', [1, 5, 0])
    dex = state.read_pokedex(memory, version)
    assert dex == {'seen': frozenset({1, 2, 251}), 'caught': frozenset({2}), 'unown': (1, 5)}

    memory.put('wCurDay', [9])
    memory.put('hHours', [13])
    memory.put('hMinutes', [5])
    memory.put('wTimeOfDay', [1])
    memory.put('wStartDay', [2])
    memory.put('wDST', [0x80])
    clock = state.read_clock(memory, version)
    assert clock['weekday'] == 'Tuesday' and clock['hours'] == 13 and clock['minutes'] == 5
    assert clock['time_of_day'] == 'day' and clock['start']['day'] == 2 and clock['daylight_saving']

    memory.put('wDayCareMan', [1 | 64 | 32])
    memory.put('wBreedMon1', struct(133, 20, party=False))
    memory.put('wBreedMon1Nickname', text('EEVEE'))
    memory.put('wEggMon', struct(133, 5, party=False, friendship=20))
    memory.put('wStepsToEgg', [180])
    daycare = state.read_daycare(memory, version)
    assert daycare['parents'][0]['nickname'] == 'EEVEE' and daycare['parents'][1] is None
    assert daycare['egg_ready'] and daycare['compatible'] and daycare['steps_to_egg'] == 180
    assert daycare['egg']['egg'] and daycare['egg']['egg_cycles'] == 20

    memory.put('wRoamMon1', [243, 40, 10, 2, 150])
    assert state.read_roamers(memory, version) == ({'species': 243, 'level': 40, 'map': 10 * 256 + 2, 'hp': 150},)


def test_pokerus_states():
    assert state.pokerus(0) == {'strain': 0, 'days': 0, 'infected': False, 'cured': False}
    assert state.pokerus(0x30)['cured']
