"""The typed game state on synthetic memory for all six games."""
from collections import defaultdict
from dataclasses import FrozenInstanceError, fields, is_dataclass
from types import SimpleNamespace

import pytest

from pokecore import gen1, yellow
from pokecore.gen2 import memory_map
from pokecore.state import ABSENT, GENERATIONS, GameState, Party, read_state

GEN1_MOVES = {84: {'pp': 30}, 45: {'pp': 40}}
GEN2_MOVES = {33: {'pp': 35}, 45: {'pp': 40}}


def text(value):
    return bytes(0x80 + ord(c) - ord('A') for c in value) + b'\x50'


def gen1_memory(game):
    """Raw memory of ``game`` with Red-layout fields written through the Yellow translation."""
    raw = bytearray(65536)
    mem = yellow.red_layout(raw, game)

    def put(address, data):
        mem[address:address + len(data)] = bytes(data)

    block = bytearray(44)
    block[0], block[1:3] = 84, (28).to_bytes(2, 'big')
    block[5:7] = bytes((23, 23))
    block[8:12] = bytes((84, 45, 0, 0))
    block[12:14] = (1234).to_bytes(2, 'big')
    block[14:17] = (1000).to_bytes(3, 'big')
    block[17:19] = (256).to_bytes(2, 'big')
    block[27:29] = bytes((0xAB, 0xCD))
    block[29:33] = bytes((0xC5, 12, 0, 0))
    block[33], block[34:36] = 10, (35).to_bytes(2, 'big')
    block[36:44] = bytes((0, 15, 0, 18, 0, 20, 0, 22))
    put(gen1.W_PARTY_COUNT, [1, 84, 0xFF])
    put(gen1.W_PARTY_MONS, block)
    put(gen1.W_PARTY_NICKS, text('PIKA'))
    put(gen1.W_PARTY_OT, text('ASH'))
    put(gen1.W_PLAYER_NAME, text('RED'))
    put(gen1.W_RIVAL_NAME, text('BLUE'))
    put(gen1.W_PLAYER_ID, (1234).to_bytes(2, 'big'))
    put(gen1.W_MONEY, [0x01, 0x23, 0x45])
    put(gen1.W_COINS, [0x09, 0x99])
    put(gen1.W_BADGES, [0b101])
    put(gen1.W_PLAYTIME_H, [12, 0, 34, 56])
    put(gen1.W_HALL_OF_FAME_COUNT, [2])
    put(gen1.W_CUR_MAP, [1])
    put(gen1.W_Y, [7, 5])
    put(gen1.W_NUM_BAG_ITEMS, [2, 4, 5, 0x14, 1, 0xFF])
    put(gen1.W_NUM_BOX_ITEMS, [1, 20, 1, 0xFF])
    put(gen1.W_DEX_SEEN, [0b011])
    put(gen1.W_DEX_OWNED, [0b111])
    return raw


class BankedMemory:
    def __init__(self, version):
        self.banks = defaultdict(lambda: bytearray(65536))
        self.symbols = memory_map.symbols(version)

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def put(self, name, data):
        bank, address = self.symbols[name]
        self.banks[bank][address:address + len(data)] = bytes(data)


def struct(species, level, *, item=0, pokerus=0, friendship=70):
    raw = bytearray(48)
    raw[0], raw[1], raw[2:6] = species, item, bytes((33, 45, 0, 0))
    raw[6:8] = (12345).to_bytes(2, 'big')
    raw[8:11] = (level ** 3).to_bytes(3, 'big')
    raw[11:13] = (500).to_bytes(2, 'big')
    raw[21], raw[22] = 0xAA, 0xAA
    raw[23:27] = bytes((35 | 0x40, 40, 0, 0))
    raw[27], raw[28], raw[31] = friendship, pokerus, level
    raw[34:36] = (20).to_bytes(2, 'big')
    raw[36:48] = b''.join(value.to_bytes(2, 'big') for value in (21, 11, 12, 13, 14, 15))
    return bytes(raw)


def gen2_memory(game):
    memory = BankedMemory(game)
    memory.put('wPartyCount', [2])
    memory.put('wPartySpecies', [152, 0xFD, 0xFF])
    memory.put('wPartyMons', struct(152, 5, item=7, pokerus=0x23) + struct(175, 1, friendship=10))
    memory.put('wPartyMonNicknames', text('CHIKO').ljust(11, b'\x50') + text('EGG').ljust(11, b'\x50'))
    memory.put('wPartyMonOTs', text('KRIS').ljust(22, b'\x50'))
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
    memory.put('wGameTimeHours', (12).to_bytes(2, 'big'))
    memory.put('wGameTimeMinutes', [34])
    memory.put('wHallOfFameCount', [1])
    memory.put('wNumItems', [2, 18, 3, 0x20, 1, 0xFF])
    memory.put('wNumBalls', [1, 5, 10, 0xFF])
    memory.put('wNumKeyItems', [2, 7, 9, 0xFF])
    memory.put('wNumPCItems', [1, 18, 99, 0xFF])
    memory.put('wTMsHMs', [1] + [0] * 55 + [1])
    memory.put('wPokedexSeen', [0b11])
    memory.put('wPokedexCaught', [0b10])
    if game == 'crystal':
        memory.put('wPlayerGender', [1])
    return memory


def memory_for(game):
    return gen1_memory(game) if GENERATIONS[game] == 1 else gen2_memory(game)


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow'])
def test_gen1_state(game):
    raw = gen1_memory(game)
    state = read_state(raw, game, GEN1_MOVES)
    assert (state.game, state.generation) == (game, 1)
    (pika,) = state.party
    assert (pika.species, pika.dex, pika.nick, pika.ot_name, pika.level) == (84, 25, 'PIKA', 'ASH', 10)
    assert pika.hp == 28 and pika.max_hp == 35 and pika.stats == (35, 15, 18, 20, 22)
    assert pika.moves == (84, 45, 0, 0) and pika.pp == (5, 12, 0, 0) and pika.pp_ups == (3, 0, 0, 0)
    assert pika.max_pp == (48, 40, 0, 0) and pika.types == (23, 23)
    assert pika.dvs == (5, 10, 11, 12, 13) and pika.stat_exp == (256, 0, 0, 0, 0)
    assert pika.trainer_id == 1234 and pika.experience == 1000 and not pika.egg and not pika.shiny
    player = state.player
    assert (player.name, player.rival_name, player.trainer_id) == ('RED', 'BLUE', 1234)
    assert player.money == 12345 and player.coins == 999 and player.hall_of_fame_count == 2
    assert player.badges == 0b101 and player.badge_names == ('Boulder', 'Thunder')
    assert player.playtime == (12, 34, 56)
    assert (state.map.map, state.map.number, state.map.x, state.map.y) == (1, 1, 5, 7)
    assert state.bag.items == ((4, 5), (0x14, 1)) and state.bag.pc_items == ((20, 1),)
    # An owned flag without its seen flag is dropped.
    assert state.seen == {1, 2} and state.owned == {1, 2}
    assert read_state(raw, game).party[0].max_pp is None


def test_yellow_reads_raw_memory_and_the_red_layout_view_alike():
    raw = gen1_memory('yellow')
    assert yellow.address(gen1.W_PARTY_COUNT) != gen1.W_PARTY_COUNT
    assert raw[yellow.address(gen1.W_PARTY_COUNT)] == 1
    assert read_state(raw, 'yellow') == read_state(yellow.red_layout(raw, 'yellow'), 'yellow')


@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_gen2_state(game):
    state = read_state(gen2_memory(game), game, GEN2_MOVES)
    assert (state.game, state.generation) == (game, 2)
    chiko, egg = state.party
    assert (chiko.species, chiko.dex, chiko.nick, chiko.ot_name, chiko.level) == (152, 152, 'CHIKO', 'KRIS', 5)
    assert chiko.held_item == 7 and chiko.pokerus == 0x23 and chiko.friendship == 70 and chiko.types is None
    assert chiko.hp == 20 and chiko.max_hp == 21 and chiko.stats == (21, 11, 12, 13, 14, 15)
    assert chiko.pp == (35, 40, 0, 0) and chiko.pp_ups == (1, 0, 0, 0) and chiko.max_pp == (42, 40, 0, 0)
    assert chiko.dvs == (0, 10, 10, 10, 10) and chiko.shiny and chiko.trainer_id == 12345
    assert egg.egg and egg.species == 175 and egg.friendship == 10 and not chiko.egg
    player = state.player
    assert (player.name, player.rival_name, player.trainer_id) == ('KRIS', 'SILVER', 54321)
    assert player.badges == 0b101 | 1 << 8 and player.badge_names == ('Zephyr', 'Plain', 'Boulder')
    assert player.money == 123456 and player.moms_money == 2000 and player.coins == 99
    assert player.playtime == (12, 34, 0) and player.hall_of_fame_count == 1
    assert player.gender == ('Female' if game == 'crystal' else 'Male')
    assert (state.map.map, state.map.group, state.map.number) == (24 * 256 + 4, 24, 4)
    assert (state.map.x, state.map.y) == (3, 7)
    bag = state.bag
    assert bag.items == ((18, 3), (0x20, 1)) and bag.balls == ((5, 10),) and bag.key_items == (7, 9)
    assert bag.pc_items == ((18, 99),) and len(bag.tms_hms) == 57 and bag.tms_hms[56] == 1
    assert state.seen == {1, 2} and state.owned == {2}
    assert read_state(gen2_memory(game), game).party[0].max_pp is None


def walk(value):
    for field in fields(value):
        name, inner = f'{type(value).__name__}.{field.name}', getattr(value, field.name)
        yield name, inner
        if isinstance(inner, Party):
            yield from walk(inner.mons[0])
        elif is_dataclass(inner):
            yield from walk(inner)


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'])
def test_every_field_is_filled_or_absent_by_design(game):
    state = read_state(memory_for(game), game, GEN1_MOVES if GENERATIONS[game] == 1 else GEN2_MOVES)
    names = dict(walk(state))
    absent = ABSENT[state.generation]
    assert set(absent) <= set(names)
    for name, value in names.items():
        assert (value is None) == (name in absent), name


def test_state_is_frozen_and_names_its_game():
    state = read_state(gen1_memory('red'), SimpleNamespace(version='red'))
    assert isinstance(state, GameState) and state.game == 'red'
    with pytest.raises(FrozenInstanceError):
        state.party = None
    with pytest.raises(ValueError):
        read_state(gen1_memory('red'), 'green')


def test_pc_items_are_bounded_to_fifty_slots():
    raw = bytearray(65536)
    raw[gen1.W_NUM_BOX_ITEMS] = 255
    raw[gen1.W_BOX_ITEMS:gen1.W_BOX_ITEMS + 120] = bytes((1, 1)) * 60
    assert len(gen1.read_pc_items(raw)) == 50
