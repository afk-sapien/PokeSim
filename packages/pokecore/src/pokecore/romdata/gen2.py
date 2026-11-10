"""Read Gold, Silver and Crystal game data from the cartridge.

Species are keyed by dex number, which Gen II also uses in memory. Map IDs are
``group * 256 + number``, as in :mod:`pokecore.gen2.tables`.
"""
from __future__ import annotations

from ..gen2.tables import decode_text
from .gen1 import banked, class_spans, machines, word

RECORD = 32
NAME_LENGTH = 10
GRASS_SLOTS = 7
WATER_SLOTS = 3
TIMES = ('morn', 'day', 'nite')
EVOLUTION_METHODS = {1: ('level', 'level'), 2: ('item', 'item'), 3: ('trade', 'item'),
                     4: ('happiness', 'time')}
ITEM = 1 << 1
MOVES = 1 << 0


def base_record(rom, offset, tm_count):
    raw = rom[offset:offset + RECORD]
    return {'stats': list(raw[1:7]), 'types': list(raw[7:9]), 'catch_rate': raw[9], 'base_exp': raw[10],
            'items': list(raw[11:13]), 'gender_ratio': raw[13], 'egg_steps': raw[15], 'growth': raw[22],
            'egg_groups': [raw[23] >> 4, raw[23] & 0x0F], 'tmhm': machines(raw[24:32], tm_count)}


def evos_moves(rom, offset):
    evolutions = []
    while (method := rom[offset]) != 0:
        if method == 5:
            evolutions.append({'method': 'stat', 'level': rom[offset + 1], 'stat': rom[offset + 2],
                               'species': rom[offset + 3]})
            offset += 4
        elif method in EVOLUTION_METHODS:
            name, field = EVOLUTION_METHODS[method]
            evolutions.append({'method': name, field: rom[offset + 1], 'species': rom[offset + 2]})
            offset += 3
        else:
            raise ValueError(f'Unknown evolution method {method} at {offset:#x}')
    offset += 1
    learnset = []
    while rom[offset] != 0:
        learnset.append([rom[offset], rom[offset + 1]])
        offset += 2
    return evolutions, learnset


def pairs(rom, offset, count):
    return [[rom[offset + 2 * slot], rom[offset + 2 * slot + 1]] for slot in range(count)]


def encounter_sites(rom, layout):
    """(key, offset of the first rate byte, table) for each wild table, in ROM order."""
    seen = set()
    for kind, offset in layout.wild:
        grass = kind.endswith('grass')
        while rom[offset] != 0xFF:
            map_id = rom[offset] * 256 + rom[offset + 1]
            offset += 2
            start = offset
            if grass:
                table = {'rates': list(rom[offset:offset + 3]),
                         'slots': {time: pairs(rom, offset + 3 + 2 * GRASS_SLOTS * n, GRASS_SLOTS)
                                   for n, time in enumerate(TIMES)}}
                offset += 3 + 2 * GRASS_SLOTS * len(TIMES)
            else:
                table = {'rate': rom[offset], 'slots': pairs(rom, offset + 1, WATER_SLOTS)}
                offset += 1 + 2 * WATER_SLOTS
            key = f'{kind}:{map_id}'
            if key in seen:
                raise ValueError(f'Two {kind} tables for map {map_id}')
            seen.add(key)
            yield key, start, {'kind': kind, 'map': map_id, **table}


def encounters(rom, layout):
    return {key: table for key, _, table in encounter_sites(rom, layout)}


def _flat(slots, count):
    if len(slots) != count:
        raise ValueError(f'An encounter table needs {count} slots per time of day, got {len(slots)}')
    return [value for slot in slots for value in slot]


def encode_encounter(table):
    if 'rates' in table:
        if set(table['slots']) != set(TIMES):
            raise ValueError(f'A grass table needs slots for {", ".join(TIMES)}')
        return bytes([*table['rates'], *(value for time in TIMES
                                         for value in _flat(table['slots'][time], GRASS_SLOTS))])
    return bytes([table['rate'], *_flat(table['slots'], WATER_SLOTS)])


RODS = ('old_rod', 'good_rod', 'super_rod')
FISH_GROUP = 7
MAP_HEADER = 9
MAP_FISH_GROUP = 8


def fish_groups(rom, layout):
    """{map ID: fish group} for each map whose header names a fish group."""
    pointers = [banked(layout.map_groups, word(rom, layout.map_groups + 2 * n)) for n in range(layout.map_group_count)]
    ends = sorted(pointers) + [layout.map_groups_end]
    groups = {}
    for number, start in enumerate(pointers, 1):
        end = ends[ends.index(start) + 1]
        for index in range((end - start) // MAP_HEADER):
            group = rom[start + MAP_HEADER * index + MAP_FISH_GROUP]
            if group:
                groups[number * 256 + index + 1] = group
    return groups


def fishing(rom, layout):
    """Rod tables for each fish group. ``bite`` is the chance a cast hooks anything,
    and each slot's ``probability`` is its chance once something bites.

    A rod table lists cumulative cutoffs out of 256, ending at 255. A slot with
    species 0 reads its species and level from a time table, one pair for morning and
    day and one for night, so every table carries slots for each time of day.
    """
    tables = {}
    for group in range(1, layout.fish_group_count + 1):
        base = layout.fish_groups + FISH_GROUP * (group - 1)
        for rod, name in enumerate(RODS):
            offset = banked(base, word(rom, base + 1 + 2 * rod))
            slots = {time: [] for time in TIMES}
            low = 0
            while True:
                cutoff, species, level = rom[offset:offset + 3]
                for time in TIMES:
                    pair = (species, level)
                    if species == 0:
                        at = layout.time_fish_groups + 4 * level + 2 * (time == 'nite')
                        pair = (rom[at], rom[at + 1])
                    slots[time].append({'level': pair[1], 'species': pair[0], 'probability': (cutoff + 1 - low) / 256})
                low = cutoff + 1
                offset += 3
                if cutoff == 0xFF:
                    break
            tables[f'{name}:{group}'] = {'kind': name, 'group': group, 'bite': rom[base] / 256, 'slots': slots}
    return tables


def party_sites(rom, offset, end, version):
    """(offset, trainer) for each trainer from ``offset`` up to ``end``. The offset is the party's
    first byte, after the name and type."""
    while offset < end:
        name_end = rom.index(0x50, offset)
        name = decode_text(rom[offset:name_end + 1], version)
        kind = rom[name_end + 1]
        offset = name_end + 2
        start = offset
        party = []
        while rom[offset] != 0xFF:
            mon = {'level': rom[offset], 'species': rom[offset + 1]}
            offset += 2
            if kind & ITEM:
                mon['item'] = rom[offset]
                offset += 1
            if kind & MOVES:
                mon['moves'] = list(rom[offset:offset + 4])
                offset += 4
            party.append(mon)
        offset += 1
        yield start, {'name': name, 'type': kind, 'party': party}


def parties(rom, offset, end, version):
    return [trainer for _, trainer in party_sites(rom, offset, end, version)]


def encode_party(trainer, first=None):
    """Party bytes for ``trainer``, whose type byte decides which fields each Pokemon carries.

    ``first`` is unused. It matches :func:`.gen1.encode_party`.
    """
    kind = trainer['type']
    fields = ['level', 'species'] + ['item'] * bool(kind & ITEM) + ['moves'] * bool(kind & MOVES)
    if not trainer['party']:
        raise ValueError('A trainer party needs at least one Pokemon')
    raw = []
    for mon in trainer['party']:
        if sorted(mon) != sorted(fields) or len(mon.get('moves', [0] * 4)) != 4:
            raise ValueError(f'Trainer type {kind} Pokemon need exactly {fields}, with four moves')
        for field in fields:
            raw.extend(mon[field] if field == 'moves' else [mon[field]])
    return bytes([*raw, 0xFF])


def trainer_sites(rom, layout):
    """(key, offset, trainer) for each trainer, in ROM order."""
    for cls, start, end in class_spans(rom, layout):
        for number, (offset, trainer) in enumerate(party_sites(rom, start, end, layout.version), 1):
            yield f'{cls}:{number}', offset, {'class': cls, 'index': number, **trainer}


def trainers(rom, layout):
    return {key: trainer for key, _, trainer in trainer_sites(rom, layout)}


def read(rom, layout):
    tm_count = layout.tm_count
    species, evolutions, learnsets = {}, {}, {}
    for dex in range(1, layout.species_count + 1):
        name_at = layout.names + (dex - 1) * NAME_LENGTH
        species[dex] = {'name': decode_text(rom[name_at:name_at + NAME_LENGTH], layout.version), 'dex': dex,
                        **base_record(rom, layout.base_stats + (dex - 1) * RECORD, tm_count)}
        pointer = banked(layout.evos_moves, word(rom, layout.evos_moves + 2 * (dex - 1)))
        evolutions[dex], learnsets[dex] = evos_moves(rom, pointer)
    return {
        'species': species,
        'evolutions': evolutions,
        'learnsets': learnsets,
        'tm_moves': list(rom[layout.tm_moves:layout.tm_moves + tm_count]),
        'encounters': encounters(rom, layout),
        'fishing': fishing(rom, layout) if layout.fish_groups is not None else {},
        'fish_groups': fish_groups(rom, layout) if layout.map_groups is not None else {},
        'trainers': trainers(rom, layout),
        'starters': [rom[sites[0]] for sites in layout.starters],
    }
