"""The typed game state on synthetic memory for all six games."""
from collections import defaultdict
from dataclasses import FrozenInstanceError, fields, is_dataclass
from types import SimpleNamespace

import pytest

from pokecore import gen1, yellow
from pokecore.gen2 import memory_map
from pokecore.identity import GEN1_DEX
from pokecore.state import ABSENT, BATTLE_KINDS, GENERATIONS, GameState, Party, read_battle, read_state

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


def gen1_battler(species, level, hp, dvs):
    block = bytearray(gen1.BATTLE_STRUCT)
    block[0], block[1:3], block[4] = species, hp.to_bytes(2, 'big'), 0x40
    block[5:7], block[8:12], block[12:14] = bytes((23, 0)), bytes((84, 45, 0, 0)), bytes(dvs)
    block[14] = level
    block[15:25] = b''.join(value.to_bytes(2, 'big') for value in (35, 15, 18, 20, 22))
    block[25:29] = bytes((0xC5, 12, 0, 0))
    return bytes(block)


def gen1_battle(raw, game, *, mode=1, battle_type=0, link=0, status1=0, player_status3=0, enemy_status3=0):
    """A battle in ``raw``: the party's Pikachu, slot 0, against a level 3 Rattata."""
    mem = yellow.red_layout(raw, game)

    def put(address, data):
        mem[address:address + len(data)] = bytes(data)

    put(gen1.W_IS_IN_BATTLE, [mode])
    put(gen1.W_BATTLE_TYPE, [battle_type])
    put(gen1.W_LINK_STATE, [link])
    put(gen1.W_PLAYER_MON_NUMBER, [0])
    put(gen1.W_BATTLE_MON, gen1_battler(84, 10, 28, (0x11, 0x11)))
    put(gen1.W_BATTLE_MON_NICK, text('PIKA'))
    put(gen1.W_ENEMY_MON, gen1_battler(165, 3, 9, (0xFE, 0xDC)))
    put(gen1.W_ENEMY_MON_NICK, text('RATTATA'))
    put(gen1.W_TRANSFORMED_ENEMY_DVS, [0x98, 0x76])
    put(gen1.W_PLAYER_BATTLE_STATUS3, [player_status3])
    put(gen1.W_ENEMY_BATTLE_STATUS1, [status1])
    put(gen1.W_ENEMY_BATTLE_STATUS3, [enemy_status3])
    return raw


def gen2_battler(species, level, hp, dvs, item=0):
    raw = bytearray(32)
    raw[0], raw[1], raw[2:6], raw[6:8] = species, item, bytes((33, 45, 0, 0)), bytes(dvs)
    raw[8:12], raw[13], raw[14] = bytes((35 | 0x40, 40, 0, 0)), level, 0x08
    raw[16:18] = hp.to_bytes(2, 'big')
    raw[18:30] = b''.join(value.to_bytes(2, 'big') for value in (21, 11, 12, 13, 14, 15))
    raw[30:32] = bytes((22, 0))
    return bytes(raw)


def gen2_battle(memory, *, mode=1, battle_type=0, link=0, player_sub5=0, enemy_sub5=0, wrap=0):
    """A battle in ``memory``: the party's Chikorita, slot 0, against a level 3 Sentret."""
    memory.put('wBattleMode', [mode])
    memory.put('wBattleType', [battle_type])
    memory.put('wLinkMode', [link])
    memory.put('wCurBattleMon', [0])
    memory.put('wBattleMon', gen2_battler(152, 5, 20, (0x11, 0x11), item=7))
    memory.put('wBattleMonNickname', text('CHIKO'))
    memory.put('wEnemyMon', gen2_battler(161, 3, 9, (0xFE, 0xDC), item=3))
    memory.put('wEnemyMonNickname', text('SENTRET'))
    memory.put('wEnemyBackupDVs', [0x98, 0x76])
    memory.put('wPlayerSubStatus5', [player_sub5])
    memory.put('wEnemySubStatus5', [enemy_sub5])
    memory.put('wPlayerWrapCount', [wrap])
    return memory


def memory_for(game, battle=False):
    if GENERATIONS[game] == 1:
        raw = gen1_memory(game)
        return gen1_battle(raw, game) if battle else raw
    memory = gen2_memory(game)
    return gen2_battle(memory) if battle else memory


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
    """In a battle, so the battle fields count too."""
    state = read_state(memory_for(game, battle=True), game, GEN1_MOVES if GENERATIONS[game] == 1 else GEN2_MOVES)
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


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'])
def test_outside_a_battle_there_is_no_battle(game):
    battle = read_state(memory_for(game), game).battle
    assert battle.kind == 'none' and not battle.active
    assert battle.player is battle.enemy is battle.player_slot is battle.enemy_hp is None
    assert not (battle.trapped or battle.can_run or battle.link)


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow'])
def test_gen1_battle(game):
    raw = gen1_battle(gen1_memory(game), game)
    battle = read_state(raw, game).battle
    assert battle == read_battle(raw, game) == read_battle(yellow.red_layout(raw, game), game)
    assert (battle.kind, battle.battle_type, battle.player_slot) == ('wild', 0, 0) and battle.active
    assert battle.can_run and not battle.trapped and not battle.link
    pika, rattata = battle.player, battle.enemy
    assert (pika.species, pika.dex, pika.nick, pika.level, pika.hp, pika.max_hp) == (84, 25, 'PIKA', 10, 28, 35)
    assert pika.stats == (35, 15, 18, 20, 22) and pika.types == (23, 0) and pika.status == 0x40
    assert pika.moves == (84, 45, 0, 0) and pika.pp == (5, 12, 0, 0) and pika.held_item is None
    assert pika.dvs == (15, 1, 1, 1, 1) and not pika.transformed
    assert (rattata.species, rattata.dex, rattata.nick, rattata.level) == (165, GEN1_DEX[165], 'RATTATA', 3)
    assert rattata.dvs == (10, 15, 14, 13, 12) and battle.enemy_hp == rattata.hp == 9


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_transform_keeps_each_side_s_own_dvs(game):
    raw = gen1_battle(gen1_memory(game), game, player_status3=0x08, enemy_status3=0x08)
    battle = read_battle(raw, game)
    assert battle.player.transformed and battle.enemy.transformed
    # The player's from the party structure, the enemy's from the backup Transform keeps.
    assert battle.player.dvs == (5, 10, 11, 12, 13) and battle.enemy.dvs == (10, 9, 8, 7, 6)


@pytest.mark.parametrize('mode, battle_type, link, status1, expected', [
    (0, 0, 0, 0, ('none', False, False, False)),
    (0xFF, 0, 0, 0, ('none', False, False, False)),
    (1, 0, 0, 0, ('wild', True, False, False)),
    (1, gen1.BATTLE_TYPE_SAFARI, 0, 0, ('wild', True, False, False)),
    (1, 0, 0, 0x20, ('wild', True, True, False)),
    (2, 0, 0, 0, ('trainer', False, False, False)),
    (2, 0, 4, 0, ('trainer', True, False, True)),
    (1, gen1.BATTLE_TYPE_OLD_MAN, 0, 0, ('tutorial', False, False, False)),
    (1, gen1.BATTLE_TYPE_PIKACHU, 0, 0, ('scripted', False, False, False)),
])
def test_gen1_battle_kinds_and_flags(mode, battle_type, link, status1, expected):
    raw = gen1_battle(gen1_memory('yellow'), 'yellow', mode=mode, battle_type=battle_type, link=link,
                      status1=status1)
    battle = read_battle(raw, 'yellow')
    assert (battle.kind, battle.can_run, battle.trapped, battle.link) == expected
    assert battle.kind in BATTLE_KINDS and battle.battle_type == battle_type


@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_gen2_battle(game):
    memory = gen2_battle(gen2_memory(game))
    battle = read_state(memory, game).battle
    assert battle == read_battle(memory, game)
    assert (battle.kind, battle.battle_type, battle.player_slot) == ('wild', 0, 0) and battle.active
    assert battle.can_run and not battle.trapped and not battle.link
    chiko, sentret = battle.player, battle.enemy
    assert (chiko.species, chiko.dex, chiko.nick, chiko.level, chiko.hp, chiko.max_hp) == (152, 152, 'CHIKO', 5, 20, 21)
    assert chiko.stats == (21, 11, 12, 13, 14, 15) and chiko.types == (22, 0) and chiko.status == 0x08
    assert chiko.moves == (33, 45, 0, 0) and chiko.pp == (35, 40, 0, 0) and chiko.held_item == 7
    assert chiko.dvs == (15, 1, 1, 1, 1) and not chiko.transformed
    assert (sentret.species, sentret.dex, sentret.nick, sentret.level, sentret.held_item) == (161, 161, 'SENTRET', 3, 3)
    assert sentret.dvs == (10, 15, 14, 13, 12) and battle.enemy_hp == sentret.hp == 9


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_transform_keeps_each_side_s_own_dvs(game):
    battle = read_battle(gen2_battle(gen2_memory(game), player_sub5=0x08, enemy_sub5=0x08), game)
    assert battle.player.transformed and battle.enemy.transformed
    assert battle.player.dvs == (0, 10, 10, 10, 10) and battle.enemy.dvs == (10, 9, 8, 7, 6)


@pytest.mark.parametrize('mode, battle_type, flags, expected', [
    (0, 0, {}, ('none', False, False, False)),
    (1, 0, {}, ('wild', True, False, False)),
    (1, 4, {}, ('wild', True, False, False)),
    (1, 0, {'enemy_sub5': 0x80}, ('wild', False, True, False)),
    (1, 0, {'wrap': 2}, ('wild', False, True, False)),
    (1, 2, {'enemy_sub5': 0x80}, ('wild', True, True, False)),
    (1, 6, {'wrap': 2}, ('wild', True, True, False)),
    (1, 0, {'link': 1, 'wrap': 2}, ('wild', True, True, True)),
    (2, 0, {}, ('trainer', False, False, False)),
    (2, 1, {}, ('trainer', False, False, False)),
    (2, 0, {'link': 1}, ('trainer', True, False, True)),
    (1, 3, {}, ('tutorial', False, False, False)),
    (1, 7, {}, ('scripted', False, False, False)),
    (1, 8, {}, ('scripted', True, False, False)),
    (1, 9, {'link': 1}, ('scripted', False, False, True)),
    (1, 11, {}, ('scripted', False, False, False)),
    (1, 12, {}, ('scripted', False, False, False)),
])
def test_gen2_battle_kinds_and_flags(mode, battle_type, flags, expected):
    battle = read_battle(gen2_battle(gen2_memory('crystal'), mode=mode, battle_type=battle_type, **flags), 'crystal')
    assert (battle.kind, battle.can_run, battle.trapped, battle.link) == expected
    assert battle.kind in BATTLE_KINDS and battle.battle_type == battle_type


def test_pc_items_are_bounded_to_fifty_slots():
    raw = bytearray(65536)
    raw[gen1.W_NUM_BOX_ITEMS] = 255
    raw[gen1.W_BOX_ITEMS:gen1.W_BOX_ITEMS + 120] = bytes((1, 1)) * 60
    assert len(gen1.read_pc_items(raw)) == 50
