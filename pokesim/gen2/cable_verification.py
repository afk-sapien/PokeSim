"""Read-only verification of Gen II cartridge trade results and save restarts."""
from pokecore.gen2.save import checkpoint_clock, continue_save as core_continue_save
from pokecore.identity import family_key as trade_key
from pokecore.trade import gen2_evolved_species as evolved_species, gen2_untraded_party, verify_gen2_received

from ..interactions.cable import checked
from pokecore.gen2.ram import Memory, read_snapshot

__all__ = ['available_trade_item', 'checkpoint_clock', 'continue_save', 'evolved_species', 'individual_key', 'party',
           'untraded_party', 'verify_exchange']


def party(pb, data):
    mem = Memory(pb.memory, data)
    count = mem.byte('wPartyCount')
    checked(1 <= count <= 6, 'Invalid Gen II party size')
    return [{'struct': mem.read('wPartyMons', 48, i * 48),
             'nickname': mem.read('wPartyMonNicknames', 11, i * 11),
             'trainer': mem.read('wPartyMonOTs', 11, i * 11)} for i in range(count)]


def individual_key(row):
    from pokecore.gen2.ram import individual
    raw = row['struct']
    dvs, _ = individual(raw)
    return trade_key(int.from_bytes(raw[6:8], 'big'), tuple(dvs), raw[0])


def available_trade_item(data, species, held_item, inventory, *, replace_held=False, held_species=()):
    """The bag item to give ``species`` so it evolves on arrival, or None.

    Each cartridge has a single King's Rock, Metal Coat, Dragon Scale or Up-Grade. When this
    cartridge already holds the evolved species, that copy can travel instead, so the item
    stays in the bag for an evolution nobody holds yet.
    """
    if held_item and not replace_held:
        return None
    for evolution in data.species[species]['evolutions']:
        if evolution['method'] == 'trade' and evolution['requirements'][0] != '-1':
            if int(evolution['species']) in held_species:
                continue
            item = data.items[evolution['requirements'][0]]
            if inventory.get(item, 0) and held_item != item:
                return item
    return None


def untraded_party(before, slot, source, current):
    """Account for the native friendship point earned while walking to the link desk."""
    gain = (source.step_count > current.step_count
            and source.happiness_cycle == 1 and current.happiness_cycle == 0)
    return gen2_untraded_party(before, slot, friendship_step=gain, eggs=[mon.egg for mon in source.party])


def verify_exchange(side, before, incoming, slot, source_snapshot, *, time_capsule=False):
    after = party(side.pb, side.data)
    snapshot = read_snapshot(side.pb.memory, side.data, side.frame)
    checked(len(after) == len(before), 'Trade changed party size')
    checked(after[:-1] == untraded_party(before, slot, source_snapshot, snapshot), 'Untraded party members changed')
    names = {number: entry['name'] for number, entry in side.data.species.items()}
    evidence = verify_gen2_received(incoming, after[-1], time_capsule=time_capsule, names=names, decode=side.data.text)
    source, species = incoming['struct'], evidence['species']
    expected_eggs = tuple(mon.egg for index, mon in enumerate(source_snapshot.party) if index != slot) + (False,)
    checked(tuple(mon.egg for mon in snapshot.party) == expected_eggs, 'Trade changed untraded Egg status')
    checked(snapshot.event_flags == source_snapshot.event_flags, 'Trade changed story events')
    checked(snapshot.stored == source_snapshot.stored and snapshot.active_box == source_snapshot.active_box,
            'Trade changed boxed Pokémon')
    checked((snapshot.badges, snapshot.money, snapshot.items) ==
            (source_snapshot.badges, source_snapshot.money, source_snapshot.items), 'Trade changed adventure progress')
    checked(snapshot.owned == source_snapshot.owned | {source[0], species}, 'Trade did not update the Pokédex correctly')
    return after, {'party_preserved': True, 'storage_preserved': True, 'individual_preserved': True,
                   'pokedex_updated': True, **evidence}


def continue_save(rom, save, data, *, rtc=None):
    """Core's Continue, which must reach the Pokémon Center upstairs with the link closed.

    The caller owns the returned emulator and stops it.
    """
    pb = core_continue_save(rom, save, data, rtc=rtc)
    try:
        snapshot = read_snapshot(pb.memory, data)
        checked(data.maps[snapshot.map]['constant'] == 'POKECENTER_2F',
                'Gen II cartridge save did not Continue outside the link session')
        checked(Memory(pb.memory, data).byte('wLinkMode') == 0, 'Continue retained link mode')
        return pb
    except BaseException:
        pb.stop(save=False)
        raise
