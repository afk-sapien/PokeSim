"""Independent read-only validation of authentic cartridge trade results."""
from __future__ import annotations

import io
import json

from .cable import checked, sha256

EVOLUTIONS = {38: 149, 147: 14, 41: 126, 39: 49}


def party(pb, symbols):
    count = pb.memory[symbols['wPartyCount'][1]]
    checked(1 <= count <= 6, 'Invalid party size')
    rows = []
    for i in range(count):
        row = {}
        for key, base, width in (('struct', 'wPartyMons', 44),
                                 ('nickname', 'wPartyMonNicks', 11), ('trainer', 'wPartyMonOT', 11)):
            addr = symbols[base][1] + i * width
            row[key] = bytes(pb.memory[addr:addr + width])
        rows.append(row)
    return rows


def individual_key(row):
    """Stable individual identity, independent of evolution and party placement."""
    raw = row['struct']
    attack, defense = raw[27] >> 4, raw[27] & 15
    speed, special = raw[28] >> 4, raw[28] & 15
    hp = ((attack & 1) << 3) | ((defense & 1) << 2) | ((speed & 1) << 1) | (special & 1)
    # This is the existing trade preference identity serialization. Keep it
    # local to avoid importing the legacy trade package into the manager.
    identity = [int.from_bytes(raw[12:14], 'big'), [hp, attack, defense, speed, special]]
    return sha256(json.dumps(identity).encode())[:24]


def boxed_inventory(pb, symbols):
    start = symbols['wBoxDataStart'][1]
    size = symbols['wBoxDataEnd'][1] - start
    values = [bytes(pb.memory[start:start + size])]
    for i in range(1, 13):
        bank, addr = symbols[f'sBox{i}']
        values.append(bytes(pb.memory[bank, addr:addr + size]))
    return tuple(values)


def verify_exchange(side, before, incoming, selected_slot, boxes):
    from pokesim.ram import read_snapshot
    from pokesim.strategy_data import SPECIES
    after = party(side.pb, side.sym)
    checked(len(after) == len(before), 'Trade changed party size')
    checked(after[:-1] == before[:selected_slot] + before[selected_slot + 1:],
            'Untraded party members changed')
    received = after[-1]
    source, target = incoming['struct'], received['struct']
    from pokesim.ram import decode_text
    default_evolution_name = (target[0] != source[0]
        and decode_text(incoming['nickname']) == SPECIES[source[0]]['name'].upper()
        and decode_text(received['nickname']) == SPECIES[target[0]]['name'].upper())
    checked((received['nickname'] == incoming['nickname'] or default_evolution_name)
            and received['trainer'] == incoming['trainer'], 'Received individual names changed')
    checked(target[0] == EVOLUTIONS.get(source[0], source[0]), 'Unexpected received species')
    checked(target[3:5] == source[3:5] and target[7:34] == source[7:34],
            'Received individual identity or training changed')
    checked(boxed_inventory(side.pb, side.sym) == boxes, 'Boxed inventory changed')
    snapshot = read_snapshot(side.pb.memory, side.frame)
    checked({SPECIES[source[0]]['dex'], SPECIES[target[0]]['dex']} <= snapshot.owned,
            'Cartridge did not update received species in Pokedex')
    checked(side.counts['TradeCenter_Trade'] == 1, 'Expected exactly one cartridge trade')
    checked(side.counts['TradeCenter_Trade.tradeCompleted'] == 1, 'Trade animation did not complete')
    checked(side.counts['SavePartyAndDexData'] == 2, 'Expected pre-connection and post-trade saves')
    checked(side.counts['ReturnToCableClubRoom'] == 1, 'Trade menu was not cancelled normally')
    checked(snapshot.valid and snapshot.started and snapshot.map == 89 and not snapshot.textbox,
            'Trade did not return to a safe Center')
    checked(side.get('wLinkState') == 0 and not side.attached, 'Live cable state remained after return')
    return after, {'received_key': individual_key(received), 'incoming_species': source[0],
                   'received_species': target[0], 'default_name_evolved': default_evolution_name,
                   'party_conserved': True,
                   'boxes_unchanged': True, 'pokedex_updated': True,
                   'safe_return_map': snapshot.map, 'safe_return_x': snapshot.x,
                   'safe_return_y': snapshot.y, 'transport': dict(side.counts)}


def verify_restarts(side, state, save, expected):
    from pyboy import PyBoy
    from pokesim.ram import read_snapshot
    from pokesim.screen import Screen
    def emulator():
        pb = PyBoy(io.BytesIO(side.rom_bytes), ram_file=io.BytesIO(save), window='null',
                   sound_emulated=False, log_level='ERROR')
        pb.set_emulation_speed(0)
        return pb
    pb = emulator()
    try:
        pb.load_state(io.BytesIO(state))
        pb.tick(120)
        checked(party(pb, side.sym) == expected, 'Checkpoint restart changed resulting party')
        snapshot = read_snapshot(pb.memory, 120)
        checked(snapshot.valid and snapshot.map == 89 and not snapshot.textbox,
                'Checkpoint restart did not resume in safe Center')
    finally:
        pb.stop(save=False)
    pb = emulator()
    try:
        pb.tick(180)
        continued = False
        for step in range(180):
            screen = Screen(pb.memory)
            if 'CONTINUE' in screen.text:
                continued = True
                button = 'a'
            else:
                button = 'start' if step % 3 == 0 else 'a'
            snap = read_snapshot(pb.memory, 0)
            if continued and snap.valid and snap.started and snap.map == 89 and not snap.textbox:
                checked(party(pb, side.sym) == expected, 'Cartridge restart changed resulting party')
                return {'checkpoint_reload_passed': True, 'cartridge_restart_passed': True}
            pb.button_press(button)
            pb.tick(8)
            pb.button_release(button)
            pb.tick(60)
        checked(False, 'Cartridge restart did not reach safe Center')
    finally:
        pb.stop(save=False)
