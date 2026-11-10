"""Table-free Gen II reads: raw Pokémon structures, player, clock, items and Day Care.

Everything here needs only the version's memory map, never species or move tables,
so it works on any Gold, Silver or Crystal machine. ``memory`` is anything that
supports banked reads ``memory[bank, start:stop]`` (Core's emulator memory, a snapshot
memory, or a synthetic fixture). Reads never write memory or change banks.
"""
from __future__ import annotations

from functools import lru_cache

from .memory_map import symbols
from .ram import BADGES, Memory, dex_flags, individual
from .tables import GameTables, npc_trades

EGG = 0xFD
PARTY_STRUCT = 48
BOX_STRUCT = 32
NAME_LENGTH = 11
PARTY_CAPACITY = 6
BOX_CAPACITY = 20
BOX_COUNT = 14
BOX_SIZE = 1102
PC_ITEM_CAPACITY = 50
TIME_OF_DAY = ('morning', 'day', 'night', 'darkness')
WEEKDAYS = ('Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')
FACING = ('down', 'up', 'left', 'right')
CAUGHT_TIME = (None, 'morning', 'day', 'night')
PLAYER_STATES = {0: 'normal', 1: 'bike', 2: 'skate', 4: 'surf', 8: 'surf_pikachu'}


@lru_cache(maxsize=3)
def _tables(version):
    symbols(version)  # rejects unknown versions
    return GameTables({'game': version})


def memory_reader(memory, version):
    """A :class:`pokecore.gen2.ram.Memory` that resolves names through Core's memory map."""
    return Memory(memory, _tables(version))


def pokerus(value):
    """Decode the Pokérus byte: strain in the high nibble, days left in the low nibble."""
    strain, days = value >> 4, value & 15
    return {'strain': strain, 'days': days, 'infected': bool(value) and days > 0, 'cured': strain > 0 and days == 0}


def caught_data(raw, version):
    """Crystal's caught time, level, trainer gender and location. Gold and Silver do not record them."""
    if version != 'crystal':
        return None
    first, second = raw[29], raw[30]
    if not first and not second:
        return None
    return {'time': CAUGHT_TIME[first >> 6], 'level': first & 63,
            'trainer_gender': 'Female' if second & 0x80 else 'Male', 'location': second & 0x7F}


def decode_struct(raw, version, *, nickname=b'', ot_name=b'', egg=False):
    """Every field of a 48-byte party or 32-byte box structure, with no table lookups.

    Values are not validated. Eggs keep their remaining egg cycles in the friendship byte.
    """
    raw = bytes(raw)
    if len(raw) not in (BOX_STRUCT, PARTY_STRUCT):
        raise ValueError('Expected a 32-byte box or 48-byte party structure')
    dvs, stat_exp = individual(raw)
    tables = _tables(version)
    result = {
        'species': raw[0], 'held_item': raw[1], 'moves': tuple(raw[2:6]),
        'trainer_id': int.from_bytes(raw[6:8], 'big'), 'experience': int.from_bytes(raw[8:11], 'big'),
        'stat_exp': stat_exp, 'dvs': dvs, 'pp': tuple(value & 63 for value in raw[23:27]),
        'pp_ups': tuple(value >> 6 for value in raw[23:27]), 'friendship': raw[27],
        'egg': egg, 'egg_cycles': raw[27] if egg else None,
        'pokerus': pokerus(raw[28]), 'caught': caught_data(raw, version), 'level': raw[31],
        'shiny': dvs[2:] == (10, 10, 10) and bool(dvs[1] & 2),
        'nickname': tables.text(nickname) if nickname else '', 'ot_name': tables.text(ot_name) if ot_name else '',
    }
    if len(raw) == PARTY_STRUCT:
        result.update(status=raw[32], hp=int.from_bytes(raw[34:36], 'big'),
                      stats=tuple(int.from_bytes(raw[i:i + 2], 'big') for i in range(36, 48, 2)))
    return result


def read_party_structs(memory, version):
    """All counted party slots as :func:`decode_struct` dicts, eggs included."""
    mem = memory_reader(memory, version)
    count = min(mem.byte('wPartyCount'), PARTY_CAPACITY)
    species = mem.read('wPartySpecies', PARTY_CAPACITY)
    mons = mem.read('wPartyMons', PARTY_STRUCT * PARTY_CAPACITY)
    names = mem.read('wPartyMonNicknames', NAME_LENGTH * PARTY_CAPACITY)
    trainers = mem.read('wPartyMonOTs', NAME_LENGTH * PARTY_CAPACITY)
    return tuple(decode_struct(mons[i * PARTY_STRUCT:(i + 1) * PARTY_STRUCT], version,
                               nickname=names[i * NAME_LENGTH:(i + 1) * NAME_LENGTH],
                               ot_name=trainers[i * NAME_LENGTH:(i + 1) * NAME_LENGTH], egg=species[i] == EGG)
                 for i in range(count))


def box_symbol(box, active_box):
    """The cartridge keeps the active box in sBox and the others in sBox1 to sBox14."""
    return 'sBox' if box == active_box else f'sBox{box + 1}'


def read_box_structs(memory, version, box=None):
    """One PC box (0 to 13, the active box by default) as :func:`decode_struct` dicts."""
    mem = memory_reader(memory, version)
    active = min(mem.byte('wCurBox') & 0x7F, BOX_COUNT - 1)
    box = active if box is None else box
    if not 0 <= box < BOX_COUNT:
        raise ValueError('Box must be 0 to 13')
    raw = mem.read(box_symbol(box, active), BOX_SIZE)
    count = min(raw[0], BOX_CAPACITY)
    structs, trainers, names = 22, 22 + BOX_STRUCT * BOX_CAPACITY, 22 + (BOX_STRUCT + NAME_LENGTH) * BOX_CAPACITY
    return tuple(decode_struct(raw[structs + i * BOX_STRUCT:structs + (i + 1) * BOX_STRUCT], version,
                               nickname=raw[names + i * NAME_LENGTH:names + (i + 1) * NAME_LENGTH],
                               ot_name=raw[trainers + i * NAME_LENGTH:trainers + (i + 1) * NAME_LENGTH],
                               egg=raw[1 + i] == EGG) for i in range(count))


def read_box_counts(memory, version):
    """Pokémon count of each of the 14 boxes, and the active box index."""
    mem = memory_reader(memory, version)
    active = min(mem.byte('wCurBox') & 0x7F, BOX_COUNT - 1)
    return tuple(min(mem.read(box_symbol(box, active), 1)[0], BOX_CAPACITY) for box in range(BOX_COUNT)), active


def _pairs(raw):
    return tuple((raw[i], raw[i + 1]) for i in range(0, len(raw) - 1, 2) if raw[i] != 0xFF)


def read_items(memory, version):
    """Bag pockets and PC items as (item id, quantity) pairs. Key items have quantity 1.

    The TM/HM pocket is the raw 57-byte quantity array, TM01 to TM50 then HM01 to HM07.
    """
    mem = memory_reader(memory, version)
    result = {}
    for pocket, symbol, capacity in (('items', 'wNumItems', 20), ('balls', 'wNumBalls', 12),
                                     ('pc', 'wNumPCItems', PC_ITEM_CAPACITY)):
        size = min(mem.byte(symbol), capacity)
        result[pocket] = _pairs(mem.read(symbol, size * 2, 1))
    result['key'] = tuple((item, 1) for item in mem.read('wNumKeyItems', min(mem.byte('wNumKeyItems'), 26), 1)
                          if item != 0xFF)
    result['tms_hms'] = tuple(mem.read('wTMsHMs', 57))
    return result


def read_player(memory, version):
    """Trainer, position, badges, money and play time."""
    mem = memory_reader(memory, version)
    johto, kanto = mem.byte('wJohtoBadges'), mem.byte('wKantoBadges')
    badges = johto | kanto << 8
    group, number = mem.byte('wMapGroup'), mem.byte('wMapNumber')
    state = mem.byte('wPlayerState')
    return {
        'version': version, 'name': mem.text('wPlayerName'), 'rival_name': mem.text('wRivalName'),
        'trainer_id': mem.word('wPlayerID'),
        'gender': 'Female' if version == 'crystal' and mem.byte('wPlayerGender') & 1 else 'Male',
        'map': group * 256 + number, 'map_group': group, 'map_number': number,
        'x': mem.byte('wXCoord'), 'y': mem.byte('wYCoord'),
        'facing': FACING[(mem.byte('wPlayerDirection') >> 2) & 3], 'state': PLAYER_STATES.get(state, state),
        'johto_badges': johto, 'kanto_badges': kanto, 'badges': [name for i, name in enumerate(BADGES) if badges >> i & 1],
        'money': int.from_bytes(mem.read('wMoney', 3), 'big'), 'moms_money': int.from_bytes(mem.read('wMomsMoney', 3), 'big'),
        'coins': mem.word('wCoins'),
        'playtime': (mem.word('wGameTimeHours'), mem.byte('wGameTimeMinutes'), mem.byte('wGameTimeSeconds')),
        'hall_of_fame_count': mem.byte('wHallOfFameCount'),
    }


def read_pokedex(memory, version):
    """Seen and caught Pokédex numbers, and the Unown forms in the order they were caught."""
    mem = memory_reader(memory, version)
    seen = frozenset(dex_flags(mem.read('wPokedexSeen', 32)))
    caught = frozenset(dex_flags(mem.read('wPokedexCaught', 32)))
    unown = tuple(value for value in mem.read('wUnownDex', 26) if value)
    return {'seen': seen, 'caught': caught, 'unown': unown}


def read_clock(memory, version):
    """The game clock as the cartridge last computed it, plus the RTC base it was set from.

    ``day`` counts days since the clock was set, so ``day % 7`` is the weekday from Sunday.
    Hours, minutes and seconds are the cartridge's last update in HRAM, refreshed every
    overworld frame. Read the hardware RTC through the emulator's ``rtc_registers``.
    """
    mem = memory_reader(memory, version)
    day, time_of_day = mem.byte('wCurDay'), mem.byte('wTimeOfDay')
    return {
        'day': day, 'weekday': WEEKDAYS[day % 7],
        'hours': mem.byte('hHours'), 'minutes': mem.byte('hMinutes'), 'seconds': mem.byte('hSeconds'),
        'time_of_day': TIME_OF_DAY[time_of_day] if time_of_day < 4 else None, 'time_of_day_id': time_of_day,
        'start': {'day': mem.byte('wStartDay'), 'hour': mem.byte('wStartHour'),
                  'minute': mem.byte('wStartMinute'), 'second': mem.byte('wStartSecond')},
        'daylight_saving': bool(mem.byte('wDST') & 0x80),
        'rtc_status': mem.byte('sRTCStatusFlags'),
    }


def read_daycare(memory, version):
    """Both Day Care parents, the egg flags and the step counter, without table lookups."""
    mem = memory_reader(memory, version)
    man, lady = mem.byte('wDayCareMan'), mem.byte('wDayCareLady')
    parents = []
    for index, flags in ((1, man), (2, lady)):
        parents.append(decode_struct(mem.read(f'wBreedMon{index}', BOX_STRUCT), version,
                                     nickname=mem.read(f'wBreedMon{index}Nickname', NAME_LENGTH),
                                     ot_name=mem.read(f'wBreedMon{index}OT', NAME_LENGTH)) if flags & 1 else None)
    egg_ready = bool(man & 64)
    return {'parents': tuple(parents), 'egg_ready': egg_ready, 'compatible': bool(man & 32),
            'steps_to_egg': mem.byte('wStepsToEgg'), 'mother_or_non_ditto': mem.byte('wBreedMotherOrNonDitto'),
            'egg': decode_struct(mem.read('wEggMon', BOX_STRUCT), version, nickname=mem.read('wEggMonNickname', NAME_LENGTH),
                                 ot_name=mem.read('wEggMonOT', NAME_LENGTH), egg=True) if egg_ready else None}


def read_roamers(memory, version):
    """Raikou, Entei and Suicune (and Crystal's unused third slot) while they roam."""
    mem = memory_reader(memory, version)
    roamers = []
    for index in (1, 2, 3):
        raw = mem.read(f'wRoamMon{index}', 7)
        if raw[0] in (243, 244, 245):
            roamers.append({'species': raw[0], 'level': raw[1], 'map': raw[2] * 256 + raw[3], 'hp': raw[4]})
    return tuple(roamers)


def npc_trade_flags(memory, version):
    """The ``wTradeFlags`` byte. Bit ``trade.index`` is set once that in-game trade has happened."""
    return memory_reader(memory, version).byte('wTradeFlags')


def npc_trade_done(memory, version, trade):
    """Whether the in-game trade ``trade`` (an :class:`NpcTrade` or its index) has happened."""
    index = trade if isinstance(trade, int) else trade.index
    return bool(npc_trade_flags(memory, version) >> index & 1)


def npc_trades_done(memory, version):
    """The in-game trades of ``version`` that have happened, in bit order."""
    flags = npc_trade_flags(memory, version)
    return tuple(trade for trade in npc_trades(version) if flags >> trade.index & 1)


def npc_trade_qualifies(mon, trade):
    """Whether ``mon`` is a Pokémon the person accepts: the requested species, not an Egg,
    and female when the trade asks for one.

    ``mon`` is a :class:`pokecore.gen2.ram.Mon`, or a mapping with ``species``, ``egg``
    and ``gender``. Core cannot tell gender without species tables, so a female-only trade
    needs ``gender`` filled in.
    """
    field = mon.get if isinstance(mon, dict) else lambda name: getattr(mon, name, None)
    return (field('species') == trade.request and not field('egg')
            and (not trade.female or field('gender') == 'Female'))


CONTEST_STATS = ('Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef')


def contest_score(memory, version, prefix='wContestMon'):
    """The Bug-Catching Contest judge's score for the caught Pokémon, or ``prefix='wEnemyMon'``
    for the wild one in battle. 0 when the slot is empty.

    The judge (pret ContestScore) adds four times max HP, plus the other five stats,
    plus a DV bonus, plus an eighth of current HP, plus one for a held item.
    """
    mem = memory_reader(memory, version)
    if not mem.byte(prefix + 'Species'):
        return 0
    first, second = mem.read(prefix + 'DVs', 2)
    bonus = ((second >> 4) & 2) // 2 + (second & 2) * 2 + ((first >> 4) & 2) * 4 + (first & 2) * 8
    return (mem.word(prefix + 'MaxHP') * 4 + sum(mem.word(prefix + stat) for stat in CONTEST_STATS)
            + bonus + mem.word(prefix + 'HP') // 8 + bool(mem.byte(prefix + 'Item')))
