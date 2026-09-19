"""Independent read-only validation of authentic cartridge trade results."""
from __future__ import annotations

import io
import json

from .cable import checked, sha256
from .centers import CENTERS, safe_center

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
    source_center = getattr(side, 'source_center_map', None)
    checked(safe_center(snapshot, source_center, side.pb.memory),
            'Trade did not return to its original supported Center')
    checked(side.get('wLinkState') == 0 and not side.attached, 'Live cable state remained after return')
    return after, {'received_key': individual_key(received), 'incoming_species': source[0],
                   'received_species': target[0], 'default_name_evolved': default_evolution_name,
                   'party_conserved': True,
                   'boxes_unchanged': True, 'pokedex_updated': True,
                   'source_center_map': source_center, 'safe_return_map': snapshot.map, 'safe_return_x': snapshot.x,
                   'safe_return_y': snapshot.y, 'transport': dict(side.counts)}


def walking_party_preserved(before, after):
    """Two ordinary steps may deal one point of existing poison damage."""
    if len(before) != len(after):
        return False
    for original, current in zip(before, after):
        if original == current:
            continue
        old, new = original['struct'], current['struct']
        if not old[4] & 8 or not 0 <= int.from_bytes(old[1:3], 'big') - int.from_bytes(new[1:3], 'big') <= 1:
            return False
        permitted = {**original, 'struct': old[:1] + new[1:3] + old[3:]}
        if permitted != current:
            return False
    return True


def verify_control(pb, source_center, expected, symbols):
    """Prove normal movement works on a disposable restarted cartridge."""
    from pokesim.ram import read_snapshot
    from pokesim.policies.navigation import Navigator
    before = read_snapshot(pb.memory, 0)
    position = (before.map, before.x, before.y)
    checked(position == CENTERS[source_center]['rendezvous'], 'Restart missed the Cable Club return position')
    def step(button, target):
        origin = read_snapshot(pb.memory, 0)
        origin_position = (origin.map, origin.x, origin.y)
        for attempt in range(3):
            pb.button_press(button)
            pb.tick(8)
            pb.button_release(button)
            pb.tick(60)
            after = read_snapshot(pb.memory, 0)
            actual = (after.map, after.x, after.y)
            checked(safe_center(after, source_center, pb.memory) and actual in (origin_position, target),
                    'Restart did not accept normal overworld movement')
            if actual == target:
                return True
        return False

    nav = Navigator()
    choices = [('down', 'up', (position[0], position[1], position[2] + 1)),
               ('left', 'right', (position[0], position[1] - 1, position[2])),
               ('right', 'left', (position[0], position[1] + 1, position[2]))]
    moved = False
    for outward, back, target in choices:
        nav.update_live(read_snapshot(pb.memory, 0), pb.memory)
        if dict(nav.neighbors(position, 0)).get(outward) != target:
            continue
        # A wandering NPC can occupy the chosen tile after the check. Try
        # another clear tile only if the player has not left the origin.
        if step(outward, target):
            checked(step(back, position), 'Restart did not accept normal overworld movement')
            moved = True
            break
    checked(moved, 'Restart did not accept normal overworld movement')
    after = read_snapshot(pb.memory, 0)
    checked(walking_party_preserved(expected, party(pb, symbols)) and after.owned == before.owned,
            'Restart movement changed party or Pokedex')


def verify_restarts(side, state, save, expected):
    from pyboy import PyBoy
    from pokesim.ram import read_snapshot
    from pokesim.screen import Screen
    source_center = getattr(side, 'source_center_map', None)
    checked(type(source_center) is int and source_center in CENTERS, 'Missing validated source Center')
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
        checked(safe_center(snapshot, source_center, pb.memory) and pb.memory[side.sym['wLinkState'][1]] == 0,
                'Checkpoint restart did not resume in its original safe Center')
        verify_control(pb, source_center, expected, side.sym)
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
                button = 'up' if screen.menu_index > 0 else 'a'
            elif 'NEW GAME' in screen.text:
                checked(False, 'Cartridge save has no Continue option')
            elif continued:
                button = None
            else:
                button = 'start' if step % 3 == 0 else 'a'
            snap = read_snapshot(pb.memory, 0)
            if continued and safe_center(snap, source_center, pb.memory) and pb.memory[side.sym['wLinkState'][1]] == 0:
                checked(party(pb, side.sym) == expected, 'Cartridge restart changed resulting party')
                verify_control(pb, source_center, expected, side.sym)
                return {'checkpoint_reload_passed': True, 'cartridge_restart_passed': True,
                        'checkpoint_movement_passed': True, 'cartridge_movement_passed': True,
                        'checkpoint_return_map': source_center, 'cartridge_return_map': source_center}
            if button:
                pb.button_press(button)
            pb.tick(8)
            if button:
                pb.button_release(button)
            pb.tick(60)
        checked(False, 'Cartridge restart did not reach its original safe Center')
    finally:
        pb.stop(save=False)
