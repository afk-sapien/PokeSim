"""Read-only checks of a finished cartridge trade, for Gen 1, Gen 2 and Time Capsule links.

A party row is ``{'struct': bytes, 'nickname': bytes, 'trainer': bytes}`` with
44-byte Gen 1 or 48-byte Gen 2 structs and 11-byte names. The checks raise
``gen1_cable.CableError`` with PokeSim's messages and never touch the emulator
beyond reading memory.
"""
from __future__ import annotations

import hashlib
import json

from .gen1_cable import checked
from .timecapsule import DRAGON_SCALE, EVERSTONE, KINGS_ROCK, METAL_COAT, TRADE_FRIENDSHIP, UP_GRADE, individual

# Gen 1 internal species IDs: Kadabra, Machoke, Graveler and Haunter evolve when traded.
GEN1_TRADE_EVOLUTIONS = {38: 149, 147: 14, 41: 126, 39: 49}
# Gen 2 Pokédex numbers. These four evolve without an item and keep what they hold.
GEN2_PLAIN_EVOLUTIONS = {64: 65, 67: 68, 75: 76, 93: 94}
GEN2_ITEM_EVOLUTIONS = {(61, KINGS_ROCK): 186, (79, KINGS_ROCK): 199, (95, METAL_COAT): 208,
                        (123, METAL_COAT): 212, (117, DRAGON_SCALE): 230, (137, UP_GRADE): 233}
GEN1_ROW = (('struct', 'wPartyMons', 44), ('nickname', 'wPartyMonNicks', 11), ('trainer', 'wPartyMonOT', 11))


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def gen1_party(memory, symbols):
    """Party rows read at the build's Gen 1 symbols. Pass a Red-layout view for Yellow."""
    count = memory[symbols['wPartyCount'][1]]
    checked(1 <= count <= 6, 'Invalid party size')
    rows = []
    for index in range(count):
        row = {}
        for key, base, width in GEN1_ROW:
            address = symbols[base][1] + index * width
            row[key] = bytes(memory[address:address + width])
        rows.append(row)
    return rows


def gen1_individual_key(row) -> str:
    """Stable identity of a Gen 1 individual, independent of evolution and party slot."""
    raw = row['struct']
    attack, defense = raw[27] >> 4, raw[27] & 15
    speed, special = raw[28] >> 4, raw[28] & 15
    hp = ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)
    identity = [int.from_bytes(raw[12:14], 'big'), [hp, attack, defense, speed, special]]
    return _sha256(json.dumps(identity).encode())[:24]


def gen2_individual_key(row) -> str:
    """Stable identity of a Gen 2 individual."""
    raw = row['struct']
    dvs, _ = individual(raw)
    return _sha256(json.dumps([int.from_bytes(raw[6:8], 'big'), list(dvs)]).encode())[:24]


def boxed_inventory(memory, symbols):
    """The current box in WRAM and all twelve cartridge RAM boxes, as raw bytes."""
    start = symbols['wBoxDataStart'][1]
    size = symbols['wBoxDataEnd'][1] - start
    values = [bytes(memory[start:start + size])]
    for index in range(1, 13):
        bank, address = symbols[f'sBox{index}']
        values.append(bytes(memory[bank, address:address + size]))
    return tuple(values)


def walking_party_preserved(before, after) -> bool:
    """Whether a Gen 1 party is unchanged except for one point of poison damage per member."""
    if len(before) != len(after):
        return False
    for original, current in zip(before, after):
        if original == current:
            continue
        old, new = original['struct'], current['struct']
        if not old[4] & 8 or not 0 <= int.from_bytes(old[1:3], 'big') - int.from_bytes(new[1:3], 'big') <= 1:
            return False
        if {**original, 'struct': old[:1] + new[1:3] + old[3:]} != current:
            return False
    return True


def _default_name_evolved(incoming, received, source, target, names, decode):
    if names is None or target == source:
        return False
    return (decode(incoming['nickname']) == names[source].upper()
            and decode(received['nickname']) == names[target].upper())


def verify_gen1_received(incoming, received, *, names=None, decode=None) -> dict:
    """Check that a Gen 1 trade delivered the sent individual, evolved only by trade.

    ``names`` maps internal species IDs to names, so a default nickname may follow
    an evolution. ``decode`` turns name bytes into text and defaults to
    ``gen1.decode_text``.
    """
    if decode is None:
        from .gen1 import decode_text as decode
    source, target = incoming['struct'], received['struct']
    renamed = _default_name_evolved(incoming, received, source[0], target[0], names, decode)
    checked((received['nickname'] == incoming['nickname'] or renamed)
            and received['trainer'] == incoming['trainer'], 'Received individual names changed')
    checked(target[0] == GEN1_TRADE_EVOLUTIONS.get(source[0], source[0]), 'Unexpected received species')
    checked(target[3:5] == source[3:5] and target[7:34] == source[7:34],
            'Received individual identity or training changed')
    return {'received_key': gen1_individual_key(received), 'incoming_species': source[0],
            'received_species': target[0], 'default_name_evolved': renamed}


def gen2_evolved_species(raw) -> int:
    """The Pokédex number a Gen 2 struct has after a trade, honouring Everstone and held items."""
    if raw[1] == EVERSTONE:
        return raw[0]
    return GEN2_ITEM_EVOLUTIONS.get((raw[0], raw[1]), GEN2_PLAIN_EVOLUTIONS.get(raw[0], raw[0]))


def gen2_untraded_party(before, slot, *, friendship_step=False, eggs=()):
    """The rows a Gen 2 party should keep, with the friendship point a walk to the link desk can earn.

    ``eggs`` flags each row of ``before`` that is an Egg. Eggs earn no friendship.
    """
    expected = []
    for index, row in enumerate(before):
        if index == slot:
            continue
        raw = bytearray(row['struct'])
        if friendship_step and not (index < len(eggs) and eggs[index]):
            raw[27] = min(255, raw[27] + 1)
        expected.append({**row, 'struct': bytes(raw)})
    return expected


def verify_gen2_received(incoming, received, *, time_capsule=False, names=None, decode=None) -> dict:
    """Check a Gen 2 trade: evolution, held item, preserved identity, friendship reset and names.

    ``names`` maps Pokédex numbers to names and ``decode`` turns Gen 2 name bytes
    into text. Both are needed only to accept a default nickname after evolution.
    With ``time_capsule`` the level byte may differ, since the cartridge recalculates it.
    """
    source, target = incoming['struct'], received['struct']
    species = gen2_evolved_species(source)
    checked(target[0] == species, 'Unexpected trade evolution')
    item = 0 if species != source[0] and source[0] not in GEN2_PLAIN_EVOLUTIONS else source[1]
    checked(target[1] == item, 'Trade changed the held item unexpectedly')
    checked(target[2:27] == source[2:27] and target[28:32] == source[28:32],
            'Trade changed moves, identity, training or caught data')
    checked(target[27] == TRADE_FRIENDSHIP, 'Trade did not reset friendship normally')
    if species == source[0]:
        checked(target[32] == source[32] and target[34:] == source[34:]
                and (time_capsule or target[33] == source[33]), 'Trade changed battle stats or health')
    renamed = _default_name_evolved(incoming, received, source[0], species, names, decode) if decode else False
    checked(received['nickname'] == incoming['nickname'] or renamed, 'Trade changed the nickname')
    checked(received['trainer'] == incoming['trainer'], 'Trade changed original trainer name')
    return {'species': species, 'held_item': item, 'received_species': species,
            'incoming_species': source[0], 'default_name_evolved': renamed,
            'received_key': gen2_individual_key(received)}
