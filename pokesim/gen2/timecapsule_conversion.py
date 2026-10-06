"""Read-only expectations for the retail Time Capsule party conversion."""
from ..interactions.cable import checked
from .ram import calculated_stats, individual


def to_gen1(row, data):
    from ..strategy_data import SPECIES
    raw = row['struct']
    checked(len(raw) == 48 and 1 <= raw[0] <= 151 and all(move <= 165 for move in raw[2:6]),
            'The Time Capsule requires a Kanto species with Generation I moves')
    species = next(sid for sid, entry in SPECIES.items() if entry['dex'] == raw[0])
    types = data.species[raw[0]]['types'] if raw[0] not in (81, 82) else [23, 23]
    dvs, training = individual(raw)
    stats = calculated_stats(SPECIES[species]['stats'], raw[31], dvs, training)
    converted = bytes([species]) + raw[34:36] + bytes([0, raw[32], *types]) + raw[1:27]
    converted += raw[31:32] + raw[36:44] + stats[-1].to_bytes(2, 'big')
    checked(len(converted) == 44, 'Invalid Generation I conversion width')
    return {**row, 'struct': converted}


def to_gen2(row, data):
    from ..strategy_data import SPECIES
    raw = row['struct']
    checked(len(raw) == 44 and raw[0] in SPECIES, 'Invalid Generation I Time Capsule partner')
    dex = SPECIES[raw[0]]['dex']
    names = {0x19: 'LEFTOVERS', 0x2d: 'BITTER_BERRY', 0x32: 'GOLD_BERRY'}
    names.update({value: 'BERRY' for value in (0x5a, 0x64, 0x78, 0x87, 0xbe, 0xc3, 0xdc, 0xfa, 0xff)})
    item = data.items[names[raw[7]]] if raw[7] in names else raw[7]
    converted = bytearray([dex, item]) + raw[8:33] + bytes([70, 0, 0, 0, raw[33], raw[4], 0])
    converted += raw[1:3] + raw[34:42]
    dvs, training = individual(converted)
    stats = calculated_stats(data.species[dex]['stats'], raw[33], dvs, training)
    converted += stats[4].to_bytes(2, 'big') + stats[5].to_bytes(2, 'big')
    checked(len(converted) == 48, 'Invalid Generation II conversion width')
    return {**row, 'struct': bytes(converted)}


def convert(row, generation, data):
    width = 44 if generation == 1 else 48
    if len(row['struct']) == width:
        return row
    return to_gen1(row, data) if generation == 1 else to_gen2(row, data)
