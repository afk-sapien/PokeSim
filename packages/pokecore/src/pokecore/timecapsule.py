"""Time Capsule rules and the retail party conversion between Generations I and II.

Everything here is pure and read-only. Item IDs are the pret/pokecrystal and
pret/pokegold item constants, which are the same in Gold, Silver and Crystal.
Species tables come from the caller, because Core ships no game tables:

* ``gen1_species``: Gen 1 internal species ID to a dict with ``dex`` and
  ``stats`` (HP, Attack, Defense, Speed, Special).
* ``gen2_species``: Pokédex number to a dict with ``types`` and ``stats``
  (HP, Attack, Defense, Speed, Special Attack, Special Defense).

Given the same tables, ``to_gen1`` and ``to_gen2`` return what PokeSim's
``gen2.timecapsule_conversion`` returns.
"""
from __future__ import annotations

from .gen1_battle_power import calculated_stat
from .gen1_cable import checked
from .gen1_link_metadata import rom_offset

ADAPTER_ID = 'english-rbgsc-core-timecapsule-v1'
# Gen2ToGen1LinkComms lives in ROM bank 10. Values are (address, first eight bytes).
COMMUNICATION_BANK = 10
COMMUNICATION = {'gold': (16469, 'cdb443cd2744cdc2'), 'silver': (16469, 'cdb443cd2744cdc2'),
                 'crystal': (16477, 'cd2644cd9944cd34')}

# Gen 2 item IDs used by the trade rules.
KINGS_ROCK, BITTER_BERRY, EVERSTONE, METAL_COAT = 0x52, 0x53, 0x70, 0x8F
LEFTOVERS, DRAGON_SCALE, UP_GRADE, BERRY, GOLD_BERRY = 0x92, 0x97, 0xAC, 0xAD, 0xAE
FLOWER_MAIL = 0x9E
# FLOWER_MAIL, then SURF_MAIL through MIRAGE_MAIL. Mail cannot cross the Time Capsule.
MAIL_ITEMS = frozenset({FLOWER_MAIL, *range(0xB5, 0xBE)})
# TimeCapsule_CatchRateItems: a Gen 1 catch rate that becomes another Gen 2 item.
# Any other catch rate byte is kept as the held item.
CATCH_RATE_ITEMS = {0x19: LEFTOVERS, 0x2D: BITTER_BERRY, 0x32: GOLD_BERRY,
                    **{rate: BERRY for rate in (0x5A, 0x64, 0x78, 0x87, 0xBE, 0xC3, 0xDC, 0xFA, 0xFF)}}
KANTO_DEX = range(1, 152)
# STRUGGLE is the last Generation I move.
LAST_GEN1_MOVE = 165
# Magnemite and Magneton are Electric and Steel in Gen 2 and become pure Electric in Gen 1.
GEN1_TYPE_OVERRIDES = {81: (23, 23), 82: (23, 23)}
TRADE_FRIENDSHIP = 70
GEN1_STRUCT, GEN2_STRUCT = 44, 48


def held_item_from_catch_rate(catch_rate: int) -> int:
    """The Gen 2 held item a Gen 1 Pokémon arrives with."""
    return CATCH_RATE_ITEMS.get(catch_rate, catch_rate)


def is_mail(item: int) -> bool:
    return item in MAIL_ITEMS


def compatible(dex: int, moves, held_item: int = 0, *, egg: bool = False) -> bool:
    """Whether a Gen 2 Pokémon may enter the Time Capsule.

    It must be a Kanto species, know only Generation I moves, not be an Egg and
    not hold Mail.
    """
    return (not egg and dex in KANTO_DEX and all(move <= LAST_GEN1_MOVE for move in moves)
            and not is_mail(held_item))


def compatible_struct(raw, *, egg: bool = False) -> bool:
    """``compatible`` for a 48-byte Gen 2 party struct. Eggs are marked in the party species list."""
    raw = bytes(raw)
    return len(raw) == GEN2_STRUCT and compatible(raw[0], raw[2:6], raw[1], egg=egg)


def communication_ok(rom, version: str) -> bool:
    """Whether a Gen 2 ROM carries the expected Gen2ToGen1LinkComms instructions."""
    address, signature = COMMUNICATION[version]
    offset = rom_offset(COMMUNICATION_BANK, address)
    return bytes(rom)[offset:offset + 8].hex() == signature


def individual(raw):
    """DVs (HP, Attack, Defense, Speed, Special) and stat experience from a Gen 2 struct."""
    attack, defense = raw[21] >> 4, raw[21] & 15
    speed, special = raw[22] >> 4, raw[22] & 15
    hp = (attack & 1) * 8 + (defense & 1) * 4 + (speed & 1) * 2 + (special & 1)
    training = tuple(int.from_bytes(raw[index:index + 2], 'big') for index in range(11, 21, 2))
    return (hp, attack, defense, speed, special), training


def calculated_stats(base, level, dvs, training) -> tuple[int, ...]:
    """Stats for five Gen 1 or six Gen 2 base stats. Both special stats use the Special DV and stat experience."""
    return tuple(calculated_stat(stat, level, dvs[min(index, 4)], training[min(index, 4)], hp=index == 0)
                 for index, stat in enumerate(base))


def to_gen1(row, gen1_species, gen2_species):
    """The 44-byte Gen 1 struct a Gen 2 party row becomes on the Gen 1 side."""
    raw = row['struct']
    checked(len(raw) == GEN2_STRUCT and 1 <= raw[0] <= 151 and all(move <= LAST_GEN1_MOVE for move in raw[2:6]),
            'The Time Capsule requires a Kanto species with Generation I moves')
    species = next(sid for sid, entry in gen1_species.items() if entry['dex'] == raw[0])
    types = list(GEN1_TYPE_OVERRIDES.get(raw[0], gen2_species[raw[0]]['types']))
    dvs, training = individual(raw)
    stats = calculated_stats(gen1_species[species]['stats'], raw[31], dvs, training)
    converted = bytes([species]) + raw[34:36] + bytes([0, raw[32], *types]) + raw[1:27]
    converted += raw[31:32] + raw[36:44] + stats[-1].to_bytes(2, 'big')
    checked(len(converted) == GEN1_STRUCT, 'Invalid Generation I conversion width')
    return {**row, 'struct': converted}


def to_gen2(row, gen1_species, gen2_species):
    """The 48-byte Gen 2 struct a Gen 1 party row becomes on the Gen 2 side."""
    raw = row['struct']
    checked(len(raw) == GEN1_STRUCT and raw[0] in gen1_species, 'Invalid Generation I Time Capsule partner')
    dex = gen1_species[raw[0]]['dex']
    item = held_item_from_catch_rate(raw[7])
    converted = bytearray([dex, item]) + raw[8:33] + bytes([TRADE_FRIENDSHIP, 0, 0, 0, raw[33], raw[4], 0])
    converted += raw[1:3] + raw[34:42]
    dvs, training = individual(converted)
    stats = calculated_stats(gen2_species[dex]['stats'], raw[33], dvs, training)
    converted += stats[4].to_bytes(2, 'big') + stats[5].to_bytes(2, 'big')
    checked(len(converted) == GEN2_STRUCT, 'Invalid Generation II conversion width')
    return {**row, 'struct': bytes(converted)}


def convert(row, generation, gen1_species, gen2_species):
    """Convert a party row to ``generation`` unless it already has that struct width."""
    width = GEN1_STRUCT if generation == 1 else GEN2_STRUCT
    if len(row['struct']) == width:
        return row
    return to_gen1(row, gen1_species, gen2_species) if generation == 1 else to_gen2(row, gen1_species, gen2_species)
