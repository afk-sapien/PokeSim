"""Bank-aware, read-only observation for Generation II cartridges."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isqrt

from ..experimental.gen2 import dex_flags

BADGES = ('Zephyr', 'Hive', 'Plain', 'Fog', 'Mineral', 'Storm', 'Glacier', 'Rising',
          'Boulder', 'Cascade', 'Thunder', 'Rainbow', 'Soul', 'Marsh', 'Volcano', 'Earth')
STAT_NAMES = ('HP', 'Attack', 'Defense', 'Speed', 'Special Attack', 'Special Defense')


class Memory:
    def __init__(self, memory, data):
        self.memory = memory
        self.data = data

    def raw(self, bank, address, size):
        if size == 0:
            return b''
        if 0x8000 <= address < 0xE000:
            return bytes(self.memory[bank, address:address + size])
        return bytes(self.memory[address:address + size])

    def read(self, name, size=1, offset=0):
        bank, address = self.data.symbols[name]
        return self.raw(bank, address + offset, size)

    def byte(self, name, offset=0):
        return self.read(name, offset=offset)[0]

    def word(self, name):
        return int.from_bytes(self.read(name, 2), 'big')

    def text(self, name, length=11):
        return self.data.text(self.read(name, length))

    def tiles(self):
        raw = self.read('wTilemap', 360)
        return tuple(''.join(value if len(value := self.data.charmap.get(tile, ' ')) == 1 else ' '
                             for tile in raw[row:row + 20]) for row in range(0, 360, 20))


def individual(raw):
    attack, defense = raw[21] >> 4, raw[21] & 15
    speed, special = raw[22] >> 4, raw[22] & 15
    hp = (attack & 1) * 8 + (defense & 1) * 4 + (speed & 1) * 2 + (special & 1)
    dvs = (hp, attack, defense, speed, special)
    training = tuple(int.from_bytes(raw[index:index + 2], 'big') for index in range(11, 21, 2))
    return dvs, training


def experience_at(level, growth):
    n = max(1, min(100, level))
    if growth == 'FAST':
        return 4 * n ** 3 // 5
    if growth == 'SLOW':
        return 5 * n ** 3 // 4
    if growth == 'MEDIUM_SLOW':
        return max(0, 6 * n ** 3 // 5 - 15 * n ** 2 + 100 * n - 140)
    return n ** 3


def experience_progress(total, level, growth):
    start = experience_at(level, growth)
    end = experience_at(min(100, level + 1), growth)
    return {'total': total, 'level_start': start, 'next_level': end,
            'remaining': max(0, end - total), 'max_level': level >= 100,
            'percent': 100 if level >= 100 else round(max(0, min(100, (total - start) * 100 / max(1, end - start))), 1)}


def calculated_stats(base, level, dvs, training):
    result = []
    for index, stat in enumerate(base):
        source = min(index, 4)
        root = isqrt(training[source])
        bonus = min(255, root + (root * root < training[source])) // 4
        value = ((stat + dvs[source]) * 2 + bonus) * level // 100
        result.append(min(999, value + (level + 10 if index == 0 else 5)))
    return tuple(result)


@dataclass(frozen=True)
class Mon:
    species: int
    nick: str
    level: int
    hp: int
    max_hp: int
    status: int
    held_item: int
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    max_pp: tuple[int, ...]
    stats: tuple[int, ...]
    experience: int
    dvs: tuple[int, ...]
    stat_exp: tuple[int, ...]
    trainer_id: int
    friendship: int
    egg: bool = False
    box: int | None = None
    position: int | None = None
    data: object = field(default=None, repr=False, compare=False)

    @property
    def name(self):
        return self.data.species.get(self.species, {}).get('name', 'Joining the team')

    @property
    def pending(self):
        return self.species == 0

    @property
    def gender(self):
        ratio = self.data.species.get(self.species, {}).get('gender_ratio', 255)
        if ratio == 255:
            return 'Genderless'
        if ratio == 0:
            return 'Male'
        return 'Female' if ratio == 254 or self.dvs[1] * 16 + self.dvs[3] <= ratio else 'Male'

    @property
    def shiny(self):
        return self.dvs[2:] == (10, 10, 10) and bool(self.dvs[1] & 2)

    def to_dict(self):
        species = self.data.species.get(self.species, {})
        details = []
        for index, move in enumerate(self.moves):
            if move:
                entry = self.data.moves.get(move, {})
                details.append({'id': move, 'name': entry.get('name', f'Move {move}'),
                                'type': self.data.type_names.get(entry.get('type'), 'Normal'),
                                'pp': self.pp[index], 'max_pp': self.max_pp[index]})
        condition = ('Egg' if self.egg else 'Fainted' if self.hp == 0 else 'Asleep' if self.status & 7 else
                     next((name for flag, name in ((8, 'Poisoned'), (16, 'Burned'), (32, 'Frozen'), (64, 'Paralyzed'))
                           if self.status & flag), 'Healthy'))
        result = {'species': self.species, 'dex': self.species, 'name': self.name, 'nick': self.nick,
                  'level': self.level, 'hp': self.hp, 'max_hp': self.max_hp, 'status': self.status,
                  'pending': self.pending, 'types': species.get('types', []),
                  'type_names': list(dict.fromkeys(self.data.type_names.get(t, 'Normal') for t in species.get('types', []))),
                  'moves': self.moves, 'pp': self.pp, 'max_pp': self.max_pp, 'move_details': details,
                  'stats': dict(zip(STAT_NAMES[1:], self.stats[1:])), 'calculated_stats': dict(zip(STAT_NAMES, self.stats)),
                  'stat_total': sum(self.stats), 'power': sum(self.stats), 'dvs': self.dvs, 'stat_exp': self.stat_exp,
                  'perfect_dvs': sum(self.dvs) == 75,
                  'potential_power': sum(calculated_stats(species.get('stats', [0] * 6), 100, self.dvs, (65535,) * 5)),
                  'dv_total': sum(self.dvs), 'dv_percent': round(sum(self.dvs) * 100 / 75, 1),
                  'dv_stars': 4 if sum(self.dvs) == 75 else 3 if sum(self.dvs) >= 60 else 2 if sum(self.dvs) >= 38 else 1,
                  'trainer_id': self.trainer_id, 'held_item': self.held_item,
                  'held_item_name': self.data.item_names.get(self.held_item) if self.held_item else None,
                  'friendship': self.friendship, 'egg': self.egg, 'shiny': self.shiny, 'gender': self.gender,
                  'status_label': condition, 'experience': experience_progress(self.experience, self.level, species.get('growth')),
                  'box': self.box + 1 if self.box is not None else None,
                  'position': self.position + 1 if self.position is not None else None}
        return result


def decode_mon(raw, name, data, *, egg=False, box=None, position=None):
    dvs, training = individual(raw)
    species, level = raw[0], raw[31]
    if not 1 <= species <= 251 or not 1 <= level <= 100:
        return None
    moves = tuple(raw[2:6])
    max_pp = tuple(min(61, data.moves.get(move, {}).get('pp', 0) * (5 + (raw[23 + i] >> 6)) // 5)
                   for i, move in enumerate(moves))
    if len(raw) == 48:
        stats = tuple(int.from_bytes(raw[i:i + 2], 'big') for i in (36, 38, 40, 42, 44, 46))
        hp, status = int.from_bytes(raw[34:36], 'big'), raw[32]
    else:
        stats = calculated_stats(data.species[species]['stats'], level, dvs, training)
        hp, status = stats[0], 0
    return Mon(species, data.text(name), level, hp, stats[0], status, raw[1], moves,
               tuple(value & 63 for value in raw[23:27]), max_pp, stats,
               int.from_bytes(raw[8:11], 'big'), dvs, training, int.from_bytes(raw[6:8], 'big'),
               raw[27], egg, box, position, data)


@dataclass(frozen=True)
class Snapshot:
    frame: int
    map: int
    x: int
    y: int
    player_name: str
    rival_name: str
    party: tuple[Mon, ...]
    stored: tuple[Mon, ...]
    box_counts: tuple[int, ...]
    active_box: int
    owned: frozenset[int]
    seen: frozenset[int]
    badges: int
    items: tuple[tuple[int, int], ...]
    pockets: dict
    money: int
    coins: int
    in_battle: int
    enemy_species: int
    enemy_level: int
    enemy_hp: int
    enemy_max_hp: int
    trainer_class: int
    battle_type: int
    playtime: tuple[int, int, int]
    hall_of_fame_count: int
    event_flags: bytes
    tiles: tuple[str, ...]
    objects: tuple[tuple[int, int, int], ...]
    valid: bool
    data: object = field(repr=False, compare=False)
    generation: int = 2
    daycare: tuple[Mon | None, Mon | None] = (None, None)
    egg_ready: bool = False
    breeding_compatible: bool = False
    roamers: tuple[dict, ...] = ()

    @property
    def started(self):
        return self.valid and self.map in self.data.maps

    @property
    def map_name(self):
        return self.data.maps.get(self.map, {}).get('name', 'Starting adventure')

    @property
    def badge_list(self):
        return [badge for i, badge in enumerate(BADGES) if self.badges & 1 << i]

    @property
    def playtime_seconds(self):
        return self.playtime[0] * 3600 + self.playtime[1] * 60 + self.playtime[2]

    @property
    def can_catch(self):
        return len(self.party) < 6 or self.box_counts[self.active_box] < 20

    @property
    def all_fainted(self):
        return bool(self.party) and not any(mon.hp and not mon.egg for mon in self.party)

    @property
    def text(self):
        return '\n'.join(self.tiles)

    def event(self, name):
        index = self.data.events[name]
        return bool(self.event_flags[index // 8] & (1 << (index % 8)))

    def to_dict(self):
        return {'generation': 2, 'version': self.data.game, 'dex_total': 251, 'badge_total': 16,
                'frame': self.frame, 'map': self.map, 'map_group': self.map >> 8, 'map_number': self.map & 255,
                'map_name': self.map_name, 'x': self.x, 'y': self.y, 'player_name': self.player_name,
                'rival_name': self.rival_name, 'badges': self.badge_list, 'party': [mon.to_dict() for mon in self.party],
                'owned': len(self.owned), 'seen': len(self.seen), 'dex_owned': sorted(self.owned), 'dex_seen': sorted(self.seen),
                'items': [{'id': item, 'qty': count, 'name': self.data.item_names.get(item, f'Item {item}')}
                          for item, count in self.items], 'money': self.money, 'coins': self.coins,
                'in_battle': self.in_battle,
                'enemy': self.data.species.get(self.enemy_species, {}).get('name') if self.in_battle else None,
                'enemy_level': self.enemy_level, 'opponent': self.trainer_class if self.in_battle == 2 else None,
                'playtime': '%d:%02d:%02d' % self.playtime, 'playtime_seconds': self.playtime_seconds,
                'hall_of_fame_count': self.hall_of_fame_count,
                'daycare': {'parents': [mon.to_dict() if mon else None for mon in self.daycare],
                            'egg_ready': self.egg_ready, 'compatible': self.breeding_compatible},
                'roamers': list(self.roamers),
                'storage': {'active_box': self.active_box + 1, 'count': len(self.stored), 'capacity': 20,
                            'box_counts': self.box_counts, 'can_catch': self.can_catch,
                            'pokemon': [mon.to_dict() for mon in self.stored]}}


def read_snapshot(memory, data, frame=0):
    mem = Memory(memory, data)
    count = mem.byte('wPartyCount')
    party = []
    for slot in range(min(count, 6)):
        mon = decode_mon(mem.read('wPartyMons', 48, slot * 48), mem.read('wPartyMonNicknames', 11, slot * 11), data,
                         egg=mem.byte('wPartySpecies', slot) == 0xFD)
        if mon:
            party.append(mon)
    active_box = mem.byte('wCurBox') & 0x7F
    valid = count <= 6 and active_box < 14 and len(party) == count
    active_box = min(active_box, 13)
    stored, box_counts = [], []
    for box in range(14):
        name = 'sBox' if box == active_box else f'sBox{box + 1}'
        count_box = min(mem.byte(name), 20)
        box_counts.append(count_box)
        for slot in range(count_box):
            mon = decode_mon(mem.read(name, 32, 22 + slot * 32), mem.read(name, 11, 862 + slot * 11), data,
                             box=box, position=slot, egg=mem.byte(name, 1 + slot) == 0xFD)
            if mon:
                stored.append(mon)
    pockets = {}
    for pocket, symbol, capacity in [('items', 'wNumItems', 20), ('balls', 'wNumBalls', 12)]:
        size = min(mem.byte(symbol), capacity)
        raw = mem.read(symbol, size * 2, 1)
        pockets[pocket] = tuple((raw[i], raw[i + 1]) for i in range(0, len(raw), 2) if raw[i] != 0xFF)
    pockets['key'] = tuple((item, 1) for item in mem.read('wNumKeyItems', min(mem.byte('wNumKeyItems'), 26), 1) if item != 0xFF)
    machines = [data.items.get(f'TM{i:02d}') for i in range(1, 51)] + [data.items.get(f'HM{i:02d}') for i in range(1, 8)]
    pockets['machines'] = tuple((item, qty) for item, qty in zip(machines, mem.read('wTMsHMs', 57)) if item and qty)
    objects = []
    for slot in range(1, 13):
        raw = mem.read('wObjectStructs', 40, slot * 40)
        if raw[0] and not raw[4] & 1:
            objects.append((raw[1] - (data.game != 'crystal'), raw[16] - 4, raw[17] - 4))
    mid = mem.byte('wMapGroup') * 256 + mem.byte('wMapNumber')
    for index, obj in enumerate(data.maps.get(mid, {}).get('objects', []), 1):
        if obj['sprite'] != 'SPRITE_BOULDER':
            continue
        event = data.events.get(obj['event'])
        if event is not None and mem.byte('wEventFlags', event // 8) & (1 << (event % 8)):
            continue
        raw = mem.read('wMapObjects', 4, (index + (data.game != 'crystal')) * 16)
        if raw[1] and index not in {item[0] for item in objects}:
            objects.append((index, raw[3] - 4, raw[2] - 4))
    seen = frozenset(dex_flags(mem.read('wPokedexSeen', 32)))
    owned = frozenset(dex_flags(mem.read('wPokedexCaught', 32))) & seen
    daycare = tuple(decode_mon(mem.read(f'wBreedMon{i}', 32), mem.read(f'wBreedMon{i}Nickname', 11), data)
                    if mem.byte(flag) & 1 else None
                    for i, flag in [(1, 'wDayCareMan'), (2, 'wDayCareLady')])
    roamers = []
    for index in (1, 2, 3):
        raw = mem.read(f'wRoamMon{index}', 7)
        if raw[0] in (243, 244, 245):
            roamers.append({'species': raw[0], 'level': raw[1], 'map': raw[2] * 256 + raw[3], 'hp': raw[4]})
    return Snapshot(frame, mem.byte('wMapGroup') * 256 + mem.byte('wMapNumber'), mem.byte('wXCoord'), mem.byte('wYCoord'),
                    mem.text('wPlayerName'), mem.text('wRivalName'), tuple(party), tuple(stored), tuple(box_counts), active_box,
                    owned, seen, mem.byte('wJohtoBadges') | (mem.byte('wKantoBadges') << 8),
                    tuple(row for rows in pockets.values() for row in rows), pockets,
                    int.from_bytes(mem.read('wMoney', 3), 'big'), mem.word('wCoins'),
                    mem.byte('wBattleMode'), mem.byte('wEnemyMonSpecies'), mem.byte('wEnemyMonLevel'),
                    mem.word('wEnemyMonHP'), mem.word('wEnemyMonMaxHP'), mem.byte('wTrainerClass'), mem.byte('wBattleType'),
                    (mem.word('wGameTimeHours'), mem.byte('wGameTimeMinutes'), mem.byte('wGameTimeSeconds')),
                    mem.byte('wHallOfFameCount'), mem.read('wEventFlags', 256), mem.tiles(), tuple(objects), valid, data,
                    daycare=daycare, egg_ready=bool(mem.byte('wDayCareMan') & 64),
                    breeding_compatible=bool(mem.byte('wDayCareMan') & 32), roamers=tuple(roamers))
