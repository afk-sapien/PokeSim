"""Read Red, Blue and Yellow game data from the cartridge.

Species are keyed by the internal index the game stores in memory (RHYDON is 1),
as in every other Gen I decoder in Core. Each species also carries its ``dex`` number.
"""
from __future__ import annotations

from ..gen1 import decode_text
from ..rom import rom_offset

RECORD = 28
INDEX_COUNT = 190
NAME_LENGTH = 10
SLOTS = 10
EVOLUTION_METHODS = {1: 'level', 2: 'item', 3: 'trade'}
GOOD_ROD_SLOTS = 2


def word(rom, offset):
    return rom[offset] | rom[offset + 1] << 8


def banked(base, address):
    """File offset of ``address`` in the same bank as the file offset ``base``."""
    return rom_offset(base // 0x4000, address)


def machines(raw, count):
    """TM and HM numbers (1-based, HMs follow the TMs) whose bit is set in ``raw``."""
    return [number + 1 for number in range(count) if raw[number // 8] >> (number % 8) & 1]


def base_record(rom, offset, tm_count):
    raw = rom[offset:offset + RECORD]
    return {'dex': raw[0], 'stats': list(raw[1:6]), 'types': list(raw[6:8]), 'catch_rate': raw[8],
            'base_exp': raw[9], 'start_moves': list(raw[15:19]), 'growth': raw[19],
            'tmhm': machines(raw[20:27], tm_count)}


def evos_moves(rom, offset):
    evolutions = []
    while (method := rom[offset]) != 0:
        if method == 2:
            evolutions.append({'method': 'item', 'item': rom[offset + 1], 'level': rom[offset + 2],
                               'species': rom[offset + 3]})
            offset += 4
        elif method in EVOLUTION_METHODS:
            evolutions.append({'method': EVOLUTION_METHODS[method], 'level': rom[offset + 1],
                               'species': rom[offset + 2]})
            offset += 3
        else:
            raise ValueError(f'Unknown evolution method {method} at {offset:#x}')
    offset += 1
    learnset = []
    while rom[offset] != 0:
        learnset.append([rom[offset], rom[offset + 1]])
        offset += 2
    return evolutions, learnset


def slots(rom, offset):
    return [[rom[offset + 2 * slot], rom[offset + 2 * slot + 1]] for slot in range(SLOTS)]


def encounter_sites(rom, pointers):
    """(key, offset of the rate byte, table) for each wild table, in ROM order."""
    for map_id in range(256):
        address = word(rom, pointers + 2 * map_id)
        if address == 0xFFFF:
            break
        offset = banked(pointers, address)
        for kind in ('grass', 'water'):
            rate = rom[offset]
            if rate:
                yield f'{kind}:{map_id}', offset, {'kind': kind, 'map': map_id, 'rate': rate,
                                                   'slots': slots(rom, offset + 1)}
                offset += 2 * SLOTS
            offset += 1


def encounters(rom, pointers):
    return {key: table for key, _, table in encounter_sites(rom, pointers)}


def encode_encounter(table):
    if not 1 <= table['rate'] <= 255:
        raise ValueError(f'{table["kind"]}:{table["map"]}: the rate must stay between 1 and 255')
    return bytes([table['rate'], *(value for slot in _sized(table['slots'], SLOTS) for value in slot)])


def _sized(slots, count):
    if len(slots) != count:
        raise ValueError(f'An encounter table needs {count} slots, got {len(slots)}')
    return slots


def fish(level, species, probability):
    return {'level': level, 'species': species, 'probability': probability}


def fishing(rom, layout):
    """Rod tables. ``bite`` is the chance a cast hooks anything, and each slot's
    ``probability`` is its chance once something bites.

    The Old and Good Rod hook the same Pokemon on every map. The Good Rod draws a random
    byte until bit 0 is set (no bite) or bits 1 and 2 pick one of its two slots, so it
    bites a third of the time. Red and Blue's Super Rod does the same over a map's 2 to
    4 slots. Yellow's bites half the time and weighs its 4 slots by the cutoffs in its code.
    """
    old_rod = layout.old_rod
    tables = {'old_rod': {'kind': 'old_rod', 'bite': 1.0, 'slots': [fish(rom[old_rod + 1], rom[old_rod], 1.0)]},
              'good_rod': {'kind': 'good_rod', 'bite': GOOD_ROD_SLOTS / (4 + GOOD_ROD_SLOTS),
                           'slots': [fish(level, species, 1 / GOOD_ROD_SLOTS)
                                     for level, species in slots_at(rom, layout.good_rod, GOOD_ROD_SLOTS)]}}
    offset = layout.super_rod
    while (map_id := rom[offset]) != 0xFF:
        if layout.super_rod_odds is None:
            group = banked(offset, word(rom, offset + 1))
            count = rom[group]
            table = {'bite': count / (4 + count),
                     'slots': [fish(level, species, 1 / count) for level, species in slots_at(rom, group + 1, count)]}
            offset += 3
        else:
            cutoffs = [rom[layout.super_rod_odds + 6 * n] for n in range(3)] + [256]
            weights = [high - low for low, high in zip([0] + cutoffs, cutoffs)]
            table = {'bite': 0.5, 'slots': [fish(rom[offset + 2 + 2 * n], rom[offset + 1 + 2 * n], weight / 256)
                                            for n, weight in enumerate(weights)]}
            offset += 9
        tables.setdefault(f'super_rod:{map_id}', {'kind': 'super_rod', 'map': map_id, **table})
    return tables


def slots_at(rom, offset, count):
    return [(rom[offset + 2 * n], rom[offset + 2 * n + 1]) for n in range(count)]


def party_sites(rom, offset, end):
    """(offset, party) for each party from ``offset`` up to ``end``."""
    while offset < end:
        start = offset
        if rom[offset] == 0xFF:
            offset += 1
            party = []
            while rom[offset] != 0:
                party.append({'level': rom[offset], 'species': rom[offset + 1]})
                offset += 2
        else:
            level = rom[offset]
            offset += 1
            party = []
            while rom[offset] != 0:
                party.append({'level': level, 'species': rom[offset]})
                offset += 1
        offset += 1
        yield start, party


def parties(rom, offset, end):
    return [party for _, party in party_sites(rom, offset, end)]


def encode_party(trainer, first):
    """Party bytes in the format the ROM uses now. ``first`` is the party's first ROM byte."""
    party = trainer['party']
    if not party:
        raise ValueError('A trainer party needs at least one Pokemon')
    if first == 0xFF:
        return bytes([0xFF, *(value for mon in party for value in (mon['level'], mon['species'])), 0])
    if {mon['level'] for mon in party} != {first}:
        raise ValueError('This party stores one level for every Pokemon, so levels cannot change')
    return bytes([first, *(mon['species'] for mon in party), 0])


def class_spans(rom, layout):
    """(class, start, end) for each trainer class with parties.

    A class with no parties points at the next class's data. Of the classes that share a
    start, only the last one owns the parties there.
    """
    starts = [banked(layout.trainers, word(rom, layout.trainers + 2 * index))
              for index in range(layout.trainer_classes)]
    for index, start in enumerate(starts):
        if start in starts[index + 1:]:
            continue
        end = min((other for other in starts if other > start), default=layout.trainers_end)
        yield index + 1, start, end


def trainer_sites(rom, layout):
    """(key, offset, trainer) for each trainer, in ROM order."""
    for cls, start, end in class_spans(rom, layout):
        for number, (offset, party) in enumerate(party_sites(rom, start, end), 1):
            yield f'{cls}:{number}', offset, {'class': cls, 'index': number, 'party': party}


def trainers(rom, layout):
    return {key: trainer for key, _, trainer in trainer_sites(rom, layout)}


def read(rom, layout):
    dex_order = rom[layout.dex_order:layout.dex_order + INDEX_COUNT]
    tm_count = layout.tm_count
    by_dex = {dex: base_record(rom, layout.base_stats + (dex - 1) * RECORD, tm_count)
              for dex in range(1, layout.species_count + 1)}
    if layout.mew_base_stats is not None:
        by_dex[151] = base_record(rom, layout.mew_base_stats, tm_count)
    species, evolutions, learnsets = {}, {}, {}
    for index in range(1, INDEX_COUNT + 1):
        dex = dex_order[index - 1]
        if dex == 0:
            continue
        name_at = layout.names + (index - 1) * NAME_LENGTH
        species[index] = {'name': decode_text(rom[name_at:name_at + NAME_LENGTH]), **by_dex[dex]}
        pointer = banked(layout.evos_moves, word(rom, layout.evos_moves + 2 * (index - 1)))
        evolutions[index], learnsets[index] = evos_moves(rom, pointer)
    return {
        'species': species,
        'evolutions': evolutions,
        'learnsets': learnsets,
        'tm_moves': list(rom[layout.tm_moves:layout.tm_moves + tm_count]),
        'encounters': encounters(rom, layout.wild[0][1]),
        'fishing': fishing(rom, layout) if layout.old_rod is not None else {},
        'fish_groups': {},
        'trainers': trainers(rom, layout),
        'starters': [rom[sites[0]] for sites in layout.starters],
    }
