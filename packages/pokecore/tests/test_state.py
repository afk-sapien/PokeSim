"""The typed game state on synthetic memory for all six games."""
from collections import defaultdict
from dataclasses import FrozenInstanceError, fields, is_dataclass
from types import SimpleNamespace

import pytest

from pokecore import gen1, yellow
from pokecore.gen2 import state as gen2_state
from pokecore.identity import GEN1_DEX
from pokecore.shortcuts import gen2ui
from pokecore.shortcuts.screens import W_STATUS_FLAGS_6
from pokecore.state import (ABSENT, BATTLE_KINDS, GENERATIONS, LIST_SCREENS, POCKETS, SCREENS, Boxes, GameState, Party,
                            read_battle, read_battlers, read_state, read_ui)
from pokecore.storage import box_location

GEN1_MOVES = {84: {'pp': 30}, 45: {'pp': 40}}
GEN2_MOVES = {33: {'pp': 35}, 45: {'pp': 40}}
# Gen I wListMenuID, 2 for a mart's item list.
W_LIST_MENU_ID = 0xCF94
CURSOR, BOX_TL, BOX_H, BOX_TR, BOX_V, BOX_BL, BOX_BR, BLANK = 0xED, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F


def text(value):
    return bytes(0x80 + ord(c) - ord('A') for c in value) + b'\x50'


def tiles(data):
    """Tile bytes, with a string drawn in capital letters."""
    return text(data)[:-1] if isinstance(data, str) else bytes(data)


def gen1_put(raw, game, address, data):
    mem = yellow.red_layout(raw, game)
    mem[address:address + len(data)] = bytes(data)


def gen1_draw(raw, game, x, y, data):
    gen1_put(raw, game, gen1.W_TILEMAP + y * 20 + x, tiles(data))


def battle_menu(draw, item):
    """The battle menu with its cursor on FIGHT. ``item`` is the bag's label."""
    draw(9, 14, [CURSOR])
    for x, y, label in ((10, 14, 'FIGHT'), (16, 14, 'PKMN'), (10, 16, item), (16, 16, 'RUN')):
        draw(x, y, label)


def name(value):
    return text(value).ljust(11, b'\x50')


def gen1_box_record(species, level):
    """A 33-byte box record with Thundershock and Growl and one PP Up on Thundershock."""
    block = bytearray(33)
    block[0], block[1:3], block[3], block[4] = species, (30).to_bytes(2, 'big'), level, 0x08
    block[8:12] = bytes((84, 45, 0, 0))
    block[12:14], block[14:17] = (4321).to_bytes(2, 'big'), (2000).to_bytes(3, 'big')
    block[27:29], block[29:33] = bytes((0xAB, 0xCD)), bytes((0x45, 40, 0, 0))
    return bytes(block)


def gen1_box(*entries):
    """One box's data from (species, level, nickname, original trainer) entries."""
    raw = bytearray(gen1.BOX_DATA_SIZE)
    raw[0], raw[1 + len(entries)] = len(entries), 0xFF
    for i, (species, level, nick, ot) in enumerate(entries):
        raw[1 + i] = species
        raw[gen1.BOX_MONS_OFFSET + i * 33:gen1.BOX_MONS_OFFSET + (i + 1) * 33] = gen1_box_record(species, level)
        raw[gen1.BOX_OTS_OFFSET + i * 11:gen1.BOX_OTS_OFFSET + (i + 1) * 11] = name(ot)
        raw[gen1.BOX_NICKS_OFFSET + i * 11:gen1.BOX_NICKS_OFFSET + (i + 1) * 11] = name(nick)
    return bytes(raw)


class Gen1Banked:
    """Flat memory plus the cartridge RAM banks that hold the inactive boxes."""

    def __init__(self, raw):
        self.raw = raw
        self.banks = {2: bytearray(0x2000), 3: bytearray(0x2000)}

    def __getitem__(self, key):
        if not isinstance(key, tuple):
            return self.raw[key]
        bank, inner = key
        if isinstance(inner, slice):
            return self.banks[bank][inner.start - gen1.S_BOXES:inner.stop - gen1.S_BOXES]
        return self.banks[bank][inner - gen1.S_BOXES]

    def put_box(self, box, data):
        bank, base = box_location(box, None)
        self.banks[bank][base - gen1.S_BOXES:base - gen1.S_BOXES + len(data)] = data


def gen1_memory(game):
    """Raw memory of a started ``game`` on the overworld, Red-layout fields written through the Yellow translation."""
    raw = bytearray(65536)
    mem = yellow.red_layout(raw, game)

    def put(address, data):
        mem[address:address + len(data)] = bytes(data)

    # The LCD is on, with the normal palette, and play time counts.
    put(0xFF40, [0x91])
    put(0xFF47, [0xE4])
    put(W_STATUS_FLAGS_6, [1])

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
    # Box 1 is active and holds a Rattata. The game has not initialized the other boxes.
    put(gen1.W_BOX_COUNT, gen1_box((165, 3, 'RATTATA', 'ASH')))
    put(gen1.W_EVENT_FLAGS, [0b1, 0, 0x80])
    put(gen1.W_EVENT_FLAGS + gen1.NUM_EVENTS // 8 - 1, [0x80])
    return raw


class BankedMemory:
    def __init__(self, version):
        self.banks = defaultdict(lambda: bytearray(65536))
        # Core's memory map and the menu symbols the screen reader adds.
        self.symbols = gen2ui.tables(version).symbols

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def put(self, name, data):
        bank, address = self.symbols[name]
        self.banks[bank][address:address + len(data)] = bytes(data)

    def draw(self, x, y, data):
        bank, address = self.symbols['wTilemap']
        start = address + y * 20 + x
        self.banks[bank][start:start + len(tiles(data))] = tiles(data)

    def box(self, left, top, right, bottom):
        """A menu frame with a blank inside."""
        inner = right - left - 1
        self.draw(left, top, [BOX_TL] + [BOX_H] * inner + [BOX_TR])
        for y in range(top + 1, bottom):
            self.draw(left, y, [BOX_V] + [BLANK] * inner + [BOX_V])
        self.draw(left, bottom, [BOX_BL] + [BOX_H] * inner + [BOX_BR])


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


def gen2_box(*entries):
    """One box's data from (structure, nickname, original trainer, egg) entries."""
    raw = bytearray(gen2_state.BOX_SIZE)
    raw[0], raw[1 + len(entries)] = len(entries), 0xFF
    records, trainers = 22, 22 + gen2_state.BOX_STRUCT * gen2_state.BOX_CAPACITY
    names = trainers + 11 * gen2_state.BOX_CAPACITY
    for i, (record, nick, ot, egg) in enumerate(entries):
        raw[1 + i] = gen2_state.EGG if egg else record[0]
        raw[records + i * 32:records + (i + 1) * 32] = record[:32]
        raw[trainers + i * 11:trainers + (i + 1) * 11] = name(ot)
        raw[names + i * 11:names + (i + 1) * 11] = name(nick)
    return bytes(raw)


def gen2_memory(game):
    """A started ``game`` on the overworld."""
    memory = BankedMemory(game)
    memory.banks[0][gen2ui.LCDC] = 0x91
    memory.put('wGameTimerPaused', [1])
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
    # Box 1 is active and holds a Sentret. Box 3 holds a Chikorita and an egg.
    memory.put('sBox', gen2_box((struct(161, 3, item=3), 'SENTRET', 'KRIS', False)))
    memory.put('sBox3', gen2_box((struct(152, 9, pokerus=0x10), 'LEAF', 'GOLD', False),
                                 (struct(175, 1, friendship=5), 'EGG', 'KRIS', True)))
    memory.put('wEventFlags', [0b1, 0, 0x80] + [0] * (gen2_state.NUM_EVENTS // 8 - 4) + [0x80])
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
    """A battle in ``raw``: the party's Pikachu, slot 0, against a level 3 Rattata.

    Disable holds the Rattata's Growl. The Pikachu's Disable has run out, with its old move left behind.
    """
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
    put(gen1.W_PLAYER_DISABLED_MOVE, [0])
    put(gen1.W_PLAYER_DISABLED_MOVE_NUMBER, [84])
    put(gen1.W_ENEMY_DISABLED_MOVE, [0x23])
    put(gen1.W_ENEMY_DISABLED_MOVE_NUMBER, [45])
    put(gen1.W_PLAYER_USED_MOVE, [84])
    put(gen1.W_ENEMY_USED_MOVE, [45])
    put(gen1.W_TRANSFORMED_ENEMY_DVS, [0x98, 0x76])
    put(gen1.W_PLAYER_BATTLE_STATUS3, [player_status3])
    put(gen1.W_ENEMY_BATTLE_STATUS1, [status1])
    put(gen1.W_ENEMY_BATTLE_STATUS3, [enemy_status3])
    put(gen1.W_TOP_MENU_ITEM_Y, [14])
    put(gen1.W_TOP_MENU_ITEM_X, [9])
    put(gen1.W_CURRENT_MENU_ITEM, [0])
    battle_menu(lambda x, y, data: gen1_draw(raw, game, x, y, data), 'ITEM')
    return raw


def gen2_battler(species, level, hp, dvs, item=0):
    raw = bytearray(32)
    raw[0], raw[1], raw[2:6], raw[6:8] = species, item, bytes((33, 45, 0, 0)), bytes(dvs)
    raw[8:12], raw[13], raw[14] = bytes((35 | 0x40, 40, 0, 0)), level, 0x08
    raw[16:18] = hp.to_bytes(2, 'big')
    raw[18:30] = b''.join(value.to_bytes(2, 'big') for value in (21, 11, 12, 13, 14, 15))
    raw[30:32] = bytes((22, 0))
    return bytes(raw)


def gen2_battle(memory, *, mode=1, battle_type=0, link=0, player_sub5=0, enemy_sub5=0, wrap=0, script_flags=0):
    """A battle in ``memory``: the party's Chikorita, slot 0, against a level 3 Sentret.

    Disable holds the Sentret's Growl. The Chikorita's Disable has run out, with its old move left behind.
    Light Screen and Reflect guard the player's side, and Safeguard and Spikes the enemy's.
    """
    memory.put('wPlayerDisableCount', [0])
    memory.put('wDisabledMove', [33])
    memory.put('wEnemyDisableCount', [0x13])
    memory.put('wEnemyDisabledMove', [45])
    memory.put('wLastPlayerMove', [33])
    memory.put('wLastEnemyMove', [45])
    memory.put('wPlayerScreens', [0b11000])
    memory.put('wEnemyScreens', [0b00101])
    memory.put('wBattleScriptFlags', [script_flags])
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
    memory.put('wMenuCursorY', [1])
    battle_menu(memory.draw, 'PACK')
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


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow'])
def test_gen1_boxes_and_events(game):
    state = read_state(gen1_memory(game), game, GEN1_MOVES)
    boxes = state.boxes
    assert boxes.active == 0 and boxes.counts == (1,) + (0,) * 11
    (rattata,) = boxes.mons
    assert boxes.box(0) == (rattata,) and boxes.box(1) == ()
    assert (rattata.box, rattata.position, rattata.species, rattata.dex) == (0, 0, 165, 19)
    assert (rattata.nick, rattata.ot_name, rattata.level) == ('RATTATA', 'ASH', 3)
    assert rattata.hp == 30 and rattata.status == 0x08 and rattata.types == (0, 0)
    assert rattata.moves == (84, 45, 0, 0) and rattata.pp == (5, 40, 0, 0) and rattata.pp_ups == (1, 0, 0, 0)
    assert rattata.max_pp == (36, 40, 0, 0) and rattata.dvs == (5, 10, 11, 12, 13) and not rattata.shiny
    assert rattata.trainer_id == 4321 and rattata.experience == 2000 and not rattata.egg
    assert rattata.held_item is rattata.friendship is rattata.pokerus is None
    assert state.events == {0, 23, gen1.NUM_EVENTS - 1}
    assert read_state(gen1_memory(game), game).boxes.mons[0].max_pp is None


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_inactive_boxes_come_from_cartridge_ram(game):
    raw = gen1_memory(game)
    gen1_put(raw, game, gen1.W_CURRENT_BOX, [0x80])
    flat = read_state(raw, game).boxes
    assert flat.counts == (1,) + (None,) * 11 and len(flat.mons) == 1
    memory = Gen1Banked(raw)
    memory.put_box(0, gen1_box((84, 50, 'STALE', 'OLD')))
    memory.put_box(7, gen1_box((84, 12, 'PIKA', 'RED'), (165, 4, 'RAT', 'BLUE')))
    boxes = read_state(memory, game).boxes
    assert boxes.counts == (1,) + (0,) * 6 + (2,) + (0,) * 4
    assert [(mon.box, mon.position, mon.species, mon.level, mon.nick, mon.ot_name) for mon in boxes.mons] == [
        (0, 0, 165, 3, 'RATTATA', 'ASH'), (7, 0, 84, 12, 'PIKA', 'RED'), (7, 1, 165, 4, 'RAT', 'BLUE')]
    gen1_put(raw, game, gen1.W_CURRENT_BOX, [12])
    assert read_state(raw, game).boxes == Boxes(active=None, counts=(), mons=())


@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_gen2_boxes_and_events(game):
    state = read_state(gen2_memory(game), game, GEN2_MOVES)
    boxes = state.boxes
    assert boxes.active == 0 and boxes.counts == (1, 0, 2) + (0,) * 11
    sentret, leaf, egg = boxes.mons
    assert boxes.box(0) == (sentret,) and boxes.box(2) == (leaf, egg)
    assert (sentret.box, sentret.position, sentret.species, sentret.dex) == (0, 0, 161, 161)
    assert (sentret.nick, sentret.ot_name, sentret.level, sentret.held_item) == ('SENTRET', 'KRIS', 3, 3)
    assert sentret.hp is sentret.status is sentret.types is None
    assert (leaf.box, leaf.position, leaf.nick, leaf.ot_name, leaf.level) == (2, 0, 'LEAF', 'GOLD', 9)
    assert leaf.pokerus == 0x10 and leaf.friendship == 70 and leaf.experience == 729 and leaf.trainer_id == 12345
    assert leaf.pp == (35, 40, 0, 0) and leaf.pp_ups == (1, 0, 0, 0) and leaf.max_pp == (42, 40, 0, 0)
    assert leaf.dvs == (0, 10, 10, 10, 10) and leaf.shiny and not leaf.egg
    assert (egg.box, egg.position, egg.species, egg.friendship) == (2, 1, 175, 5) and egg.egg
    assert state.events == {0, 23, gen2_state.NUM_EVENTS - 1}
    assert read_state(gen2_memory(game), game).boxes.mons[0].max_pp is None


def walk(value):
    for field in fields(value):
        name, inner = f'{type(value).__name__}.{field.name}', getattr(value, field.name)
        yield name, inner
        if isinstance(inner, Party):
            yield from walk(inner.mons[0])
        elif is_dataclass(inner):
            yield from walk(inner)
            if isinstance(inner, Boxes):
                yield from walk(inner.mons[0])


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
    assert not (battle.trapped or battle.can_run or battle.link or battle.from_script)
    assert battle.player_screens == battle.enemy_screens == frozenset()


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
    # The DVs on show stay the structure's own bytes.
    assert (battle.player.shown_dvs, battle.enemy.shown_dvs) == (b'\x11\x11', b'\xfe\xdc')


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_disable_screens_and_last_moves(game):
    raw = gen1_battle(gen1_memory(game), game, player_status3=0b110, enemy_status3=0b010)
    battle = read_battle(raw, game)
    pika, rattata = battle.player, battle.enemy
    # The Pikachu's Disable count ran out, so the move byte left behind holds nothing.
    assert pika.disabled_move is None and rattata.disabled_move == 45
    assert (pika.last_move, rattata.last_move) == (84, 45)
    assert (pika.shown_dvs, rattata.shown_dvs) == (b'\x11\x11', b'\xfe\xdc')
    assert battle.player_screens == {'light_screen', 'reflect'} and battle.enemy_screens == {'light_screen'}
    assert battle.player_screens <= set(SCREENS)
    assert pika.holds_foe is rattata.holds_foe is battle.from_script is None
    assert not (pika.transformed or rattata.transformed)


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
    assert (battle.player.shown_dvs, battle.enemy.shown_dvs) == (b'\x11\x11', b'\xfe\xdc')


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_disable_screens_and_last_moves(game):
    battle = read_battle(gen2_battle(gen2_memory(game)), game)
    chiko, sentret = battle.player, battle.enemy
    # The Chikorita's Disable count ran out, so the move byte left behind holds nothing.
    assert chiko.disabled_move is None and sentret.disabled_move == 45
    assert (chiko.last_move, sentret.last_move) == (33, 45)
    assert (chiko.shown_dvs, sentret.shown_dvs) == (b'\x11\x11', b'\xfe\xdc')
    assert battle.player_screens == {'light_screen', 'reflect'} and battle.enemy_screens == {'safeguard', 'spikes'}
    assert battle.player_screens | battle.enemy_screens == set(SCREENS)
    assert not (chiko.holds_foe or sentret.holds_foe or battle.from_script)


@pytest.mark.parametrize('player_sub5, enemy_sub5, holds', [
    (0x80, 0, (True, False)), (0, 0x80, (False, True)), (0x88, 0x88, (True, True)),
])
def test_gen2_mean_look_holds_the_other_side(player_sub5, enemy_sub5, holds):
    battle = read_battle(gen2_battle(gen2_memory('crystal'), player_sub5=player_sub5, enemy_sub5=enemy_sub5),
                         'crystal')
    assert (battle.player.holds_foe, battle.enemy.holds_foe) == holds
    # The enemy's hold is what traps the player.
    assert battle.trapped == holds[1]


@pytest.mark.parametrize('flags, expected', [(0, False), (0x80, True), (0x7F, False), (0xFF, True)])
@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_battle_a_map_script_started(game, flags, expected):
    assert read_battle(gen2_battle(gen2_memory(game), script_flags=flags), game).from_script is expected


@pytest.mark.parametrize('game', ['red', 'yellow', 'gold', 'crystal'])
def test_battlers_are_read_whatever_the_battle_mode_says(game):
    """After a press the mode can say no battle for a few frames while both structures still hold it."""
    if GENERATIONS[game] == 1:
        memory = gen1_battle(gen1_memory(game), game, mode=0)
    else:
        memory = gen2_battle(gen2_memory(game), mode=0)
    battle = read_battle(memory, game)
    assert battle.kind == 'none' and battle.player is battle.enemy is None
    player, enemy = read_battlers(memory, game)
    assert (player.species, enemy.species) in ((84, 165), (152, 161)) and enemy.disabled_move == 45
    if GENERATIONS[game] == 1:
        gen1_put(memory, game, gen1.W_IS_IN_BATTLE, [1])
    else:
        memory.put('wBattleMode', [1])
    battle = read_battle(memory, game)
    assert read_battlers(memory, game) == (battle.player, battle.enemy) == (player, enemy)
    # A side whose structure is empty has no battler.
    if GENERATIONS[game] == 1:
        gen1_put(memory, game, gen1.W_ENEMY_MON, [0])
    else:
        memory.put('wEnemyMon', [0])
    assert read_battlers(memory, game) == (player, None)


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


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'])
def test_overworld_ui(game):
    memory = memory_for(game)
    ui = read_state(memory, game).ui
    assert ui == read_ui(memory, game)
    assert (ui.screen, ui.text_box, ui.start_menu, ui.cursor, ui.menu_item, ui.scroll) == (
        'overworld', False, False, None, 0, 0)
    assert (ui.facing, ui.movement, ui.movement_state) == ('down', 'walking', 0)


@pytest.mark.parametrize('game', ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'])
def test_battle_menu_ui(game):
    memory = memory_for(game, battle=True)
    ui = read_state(memory, game).ui
    assert ui == read_ui(memory, game)
    assert (ui.screen, ui.cursor, ui.menu_item, ui.scroll) == ('battle_menu', (9, 14), 0, 0)
    assert not ui.text_box and not ui.start_menu


def test_yellow_ui_reads_raw_memory_and_the_red_layout_view_alike():
    raw = gen1_memory('yellow')
    gen1_put(raw, 'yellow', gen1.W_WALK_BIKE_SURF_STATE, [1])
    assert read_ui(raw, 'yellow') == read_ui(yellow.red_layout(raw, 'yellow'), 'yellow')
    assert read_ui(raw, 'yellow').movement == 'biking'


@pytest.mark.parametrize('facing, walk_bike_surf, expected', [
    (4, 1, ('up', 'biking')), (8, 2, ('left', 'surfing')), (12, 0, ('right', 'walking')), (0, 7, ('down', None)),
])
@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_facing_and_movement(game, facing, walk_bike_surf, expected):
    raw = gen1_memory(game)
    gen1_put(raw, game, gen1.W_FACING, [facing])
    gen1_put(raw, game, gen1.W_WALK_BIKE_SURF_STATE, [walk_bike_surf])
    ui = read_ui(raw, game)
    assert (ui.facing, ui.movement) == expected and ui.movement_state == walk_bike_surf


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_start_menu(game):
    raw = gen1_memory(game)
    gen1_draw(raw, game, 10, 0, [BOX_TL])
    for row, label in zip((2, 4, 6, 8), ('ITEM', 'RED', 'SAVE', 'EXIT')):
        gen1_draw(raw, game, 12, row, label)
    gen1_draw(raw, game, 11, 8, [CURSOR])
    gen1_put(raw, game, gen1.W_TOP_MENU_ITEM_Y, [2])
    gen1_put(raw, game, gen1.W_TOP_MENU_ITEM_X, [11])
    gen1_put(raw, game, gen1.W_CURRENT_MENU_ITEM, [3])
    gen1_put(raw, game, gen1.W_MAX_MENU_ITEM, [3])
    # A list's old scroll offset is not this menu's.
    gen1_put(raw, game, gen1.W_LIST_SCROLL_OFFSET, [5])
    ui = read_ui(raw, game)
    assert (ui.screen, ui.start_menu, ui.cursor, ui.menu_item, ui.scroll) == ('pause', True, (11, 8), 3, 0)
    gen1_put(raw, game, gen1.W_IS_IN_BATTLE, [1])
    assert not read_ui(raw, game).start_menu


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_list_scroll(game):
    raw = gen1_memory(game)
    gen1_put(raw, game, W_LIST_MENU_ID, [2])
    gen1_draw(raw, game, 5, 6, [CURSOR])
    gen1_put(raw, game, gen1.W_TOP_MENU_ITEM_Y, [4])
    gen1_put(raw, game, gen1.W_TOP_MENU_ITEM_X, [5])
    gen1_put(raw, game, gen1.W_CURRENT_MENU_ITEM, [1])
    gen1_put(raw, game, gen1.W_LIST_SCROLL_OFFSET, [3])
    ui = read_ui(raw, game)
    assert ui.screen in LIST_SCREENS
    assert (ui.screen, ui.cursor, ui.menu_item, ui.scroll) == ('mart_list', (5, 6), 1, 3)


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_text_box(game):
    raw = gen1_memory(game)
    gen1_draw(raw, game, 0, 12, [BOX_TL])
    ui = read_ui(raw, game)
    assert ui.text_box and ui.screen == 'dialogue' and not ui.start_menu


@pytest.mark.parametrize('direction, player_state, expected', [
    (4, 1, ('up', 'biking')), (8, 4, ('left', 'surfing')), (12, 8, ('right', 'surfing')), (0, 2, ('down', None)),
])
@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_facing_and_movement(game, direction, player_state, expected):
    memory = gen2_memory(game)
    memory.put('wPlayerDirection', [direction])
    memory.put('wPlayerState', [player_state])
    ui = read_ui(memory, game)
    assert (ui.facing, ui.movement) == expected and ui.movement_state == player_state


@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_gen2_start_menu(game):
    memory = gen2_memory(game)
    memory.box(10, 0, 19, 5)
    memory.draw(12, 2, 'PACK')
    memory.draw(12, 4, 'EXIT')
    memory.draw(11, 4, [CURSOR])
    memory.put('wMenuCursorY', [2])
    # A list's old scroll position is not this menu's.
    memory.put('wMenuScrollPosition', [5])
    ui = read_ui(memory, game)
    assert (ui.screen, ui.start_menu, ui.cursor, ui.menu_item, ui.scroll) == ('pause', True, (11, 4), 1, 0)
    assert not ui.text_box


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_text_box(game):
    memory = gen2_memory(game)
    memory.box(0, 12, 19, 17)
    memory.draw(1, 14, 'HELLO')
    ui = read_ui(memory, game)
    assert ui.text_box and ui.screen == 'dialogue' and not ui.start_menu


@pytest.mark.parametrize('pocket, scroll', [(0, 5), (1, 5), (3, 9)])
@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_bag_scroll(game, pocket, scroll):
    """The TM pocket keeps its own scroll position."""
    memory = gen2_memory(game)
    memory.draw(7, 4, [CURSOR])
    memory.put('wCurPocket', [pocket])
    memory.put('wMenuCursorY', [2])
    memory.put('wMenuScrollPosition', [5])
    memory.put('wTMHMPocketScrollPosition', [9])
    ui = read_ui(memory, game)
    assert (ui.screen, ui.cursor, ui.menu_item, ui.scroll) == ('bag', (7, 4), 1, scroll)


@pytest.mark.parametrize('pocket, expected', [
    (0, 'items'), (1, 'balls'), (2, 'key_items'), (3, 'tms_hms'), (4, None), (0xFF, None),
])
@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_menu_cursor_pocket_and_party_slot(game, pocket, expected):
    memory = gen2_memory(game)
    memory.put('wCurPocket', [pocket])
    memory.put('wMenuCursorX', [2])
    memory.put('wMenuCursorY', [3])
    memory.put('wCurPartyMon', [1])
    ui = read_ui(memory, game)
    assert (ui.pocket, ui.menu_cursor, ui.party_slot) == (expected, (2, 3), 1)
    assert ui.pocket is None or ui.pocket in POCKETS


@pytest.mark.parametrize('game', ['red', 'yellow'])
def test_gen1_party_slot(game):
    raw = gen1_memory(game)
    gen1_put(raw, game, gen1.W_WHICH_POKEMON, [2])
    ui = read_ui(raw, game)
    assert ui.party_slot == 2 and ui.menu_cursor is ui.pocket is None
    assert read_ui(raw, game) == read_ui(yellow.red_layout(raw, game), game)


@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_trainer_id_alone(game):
    memory = gen2_memory(game)
    assert gen2_state.trainer_id(memory, game) == read_state(memory, game).player.trainer_id == 54321


@pytest.mark.parametrize('loaded, screen', [(0, 'pc_party'), (3, 'pc_box')])
@pytest.mark.parametrize('game', ['gold', 'crystal'])
def test_gen2_bills_pc_scroll(game, loaded, screen):
    memory = gen2_memory(game)
    memory.draw(8, 0, [BOX_TL])
    memory.draw(8, 1, [BOX_V])
    memory.draw(8, 2, [BOX_BL])
    memory.draw(10, 1, 'BOX')
    memory.put('wBillsPC_LoadedBox', [loaded])
    memory.put('wBillsPC_ScrollPosition', [4])
    memory.put('wBillsPC_CursorPosition', [2])
    ui = read_ui(memory, game)
    assert (ui.screen, ui.cursor, ui.menu_item, ui.scroll) == (screen, None, 2, 4)
