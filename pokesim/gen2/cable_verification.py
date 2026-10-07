"""Read-only verification of Gen II cartridge trade results and save restarts."""
import io
import json

from .core import boot, stop_with_clock

from ..interactions.cable import checked, sha256
from .ram import Memory, read_snapshot
from .save import press


def party(pb, data):
    mem = Memory(pb.memory, data)
    count = mem.byte('wPartyCount')
    checked(1 <= count <= 6, 'Invalid Gen II party size')
    return [{'struct': mem.read('wPartyMons', 48, i * 48),
             'nickname': mem.read('wPartyMonNicknames', 11, i * 11),
             'trainer': mem.read('wPartyMonOTs', 11, i * 11)} for i in range(count)]


def individual_key(row):
    from .ram import individual
    raw = row['struct']
    dvs, _ = individual(raw)
    return sha256(json.dumps([int.from_bytes(raw[6:8], 'big'), list(dvs)]).encode())[:24]


def evolved_species(raw, data):
    if raw[1] == data.items['EVERSTONE']:
        return raw[0]
    plain = {64: 65, 67: 68, 75: 76, 93: 94}
    held = {(61, 'KINGS_ROCK'): 186, (79, 'KINGS_ROCK'): 199, (95, 'METAL_COAT'): 208,
            (123, 'METAL_COAT'): 212, (117, 'DRAGON_SCALE'): 230, (137, 'UP_GRADE'): 233}
    return next((result for (species, item), result in held.items()
                 if raw[0] == species and raw[1] == data.items[item]), plain.get(raw[0], raw[0]))


def available_trade_item(data, species, held_item, inventory, *, replace_held=False):
    if held_item and not replace_held:
        return None
    for evolution in data.species[species]['evolutions']:
        if evolution['method'] == 'trade' and evolution['requirements'][0] != '-1':
            item = data.items[evolution['requirements'][0]]
            if inventory.get(item, 0) and held_item != item:
                return item
    return None


def untraded_party(before, slot, source, current):
    """Account for the native friendship point earned while walking to the link desk."""
    gain = (source.step_count > current.step_count
            and source.happiness_cycle == 1 and current.happiness_cycle == 0)
    expected = []
    for index, row in enumerate(before):
        if index == slot:
            continue
        raw = bytearray(row['struct'])
        if gain and not source.party[index].egg:
            raw[27] = min(255, raw[27] + 1)
        expected.append({**row, 'struct': bytes(raw)})
    return expected


def verify_exchange(side, before, incoming, slot, source_snapshot, *, time_capsule=False):
    after = party(side.pb, side.data)
    snapshot = read_snapshot(side.pb.memory, side.data, side.frame)
    checked(len(after) == len(before), 'Trade changed party size')
    checked(after[:-1] == untraded_party(before, slot, source_snapshot, snapshot), 'Untraded party members changed')
    received = after[-1]
    source, target = incoming['struct'], received['struct']
    species = evolved_species(source, side.data)
    checked(target[0] == species, 'Unexpected trade evolution')
    item = 0 if species != source[0] and source[0] not in (64, 67, 75, 93) else source[1]
    checked(target[1] == item, 'Trade changed the held item unexpectedly')
    checked(target[2:27] == source[2:27] and target[28:32] == source[28:32],
            'Trade changed moves, identity, training or caught data')
    checked(target[27] == 70, 'Trade did not reset friendship normally')
    if species == source[0]:
        checked(target[32] == source[32] and target[34:] == source[34:]
                and (time_capsule or target[33] == source[33]), 'Trade changed battle stats or health')
    nickname_changed = (species != source[0]
                        and side.data.text(incoming['nickname']) == side.data.species[source[0]]['name'].upper()
                        and side.data.text(received['nickname']) == side.data.species[species]['name'].upper())
    checked(received['nickname'] == incoming['nickname'] or nickname_changed, 'Trade changed the nickname')
    checked(received['trainer'] == incoming['trainer'], 'Trade changed original trainer name')
    expected_eggs = tuple(mon.egg for index, mon in enumerate(source_snapshot.party) if index != slot) + (False,)
    checked(tuple(mon.egg for mon in snapshot.party) == expected_eggs, 'Trade changed untraded Egg status')
    checked(snapshot.event_flags == source_snapshot.event_flags, 'Trade changed story events')
    checked(snapshot.stored == source_snapshot.stored and snapshot.active_box == source_snapshot.active_box,
            'Trade changed boxed Pokémon')
    checked((snapshot.badges, snapshot.money, snapshot.items) ==
            (source_snapshot.badges, source_snapshot.money, source_snapshot.items), 'Trade changed adventure progress')
    checked(snapshot.owned == source_snapshot.owned | {source[0], species}, 'Trade did not update the Pokédex correctly')
    return after, {'party_preserved': True, 'storage_preserved': True, 'individual_preserved': True,
                   'pokedex_updated': True, 'species': species, 'held_item': item,
                   'received_species': species, 'incoming_species': source[0],
                   'default_name_evolved': nickname_changed}


def checkpoint_clock(rom, state):
    """Export the checkpoint RTC through Core without changing the source."""
    clone = boot(io.BytesIO(rom), sound=False)
    try:
        clone.load_state(io.BytesIO(state))
        clock = io.BytesIO()
        stop_with_clock(clone, io.BytesIO(), clock)
        return clock.getvalue()
    finally:
        clone.stop(save=False)


def continue_save(rom, save, data, *, rtc=None):
    pb = boot(io.BytesIO(rom), ram=io.BytesIO(save), rtc=rtc, sound=False)
    try:
        pb.tick(180, True)
        continuing = False
        for step in range(240):
            snapshot = read_snapshot(pb.memory, data, step * 48)
            if continuing and snapshot.started and snapshot.party and 'CONTINUE' not in snapshot.text and 'BADGES' not in snapshot.text:
                if data.maps[snapshot.map]['constant'] == 'POKECENTER_2F':
                    press(pb, wait=120)
                    checked(Memory(pb.memory, data).byte('wLinkMode') == 0, 'Continue retained link mode')
                    return pb
            if 'CONTINUE' in snapshot.text:
                continuing = True
                selected = next((row for row in snapshot.tiles if '▶' in row), '')
                button = 'a' if 'CONTINUE' in selected else 'up'
            else:
                button = 'start' if step % 3 == 0 else 'a'
            press(pb, button, 40)
        raise ValueError('Gen II cartridge save did not Continue outside the link session')
    except BaseException:
        pb.stop(save=False)
        raise
