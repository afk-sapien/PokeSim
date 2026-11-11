"""Walking returns for Gen II's one-time legendaries, overworld encounters, gifts and trades.

Gen II hides an overworld object while its event flag is set and reloads that state when a map
loads, so clearing a flag away from the map brings the encounter back on the next visit. A gift
giver checks its GOT flag and a trader its wTradeFlags bit the same way.
The legendaries' returns are ``legendary`` rows in the claims ledger (return_claims), and the kv
value under KEY keeps only the walking clock. The other returns are ``event`` rows, and the kv value
under EVENTS keeps each one's walking clock and the count at the venue.
"""
import json

from .. import config, return_claims
from ..events import Event
from ..state import claims as ledger, kv
from pokecore.gen2.ram import Memory
from pokecore.gen2.resets import write_byte, write_flag

KEY = 'gen2-legendary-returns-v1'
EVENTS = 'gen2-event-returns-v1'
STEPS = 'cartridge-steps-v1'
# Roaming slot, starting map and level from InitRoamMons.
ROAMERS = {243: (1, 'ROUTE_42'), 244: (2, 'ROUTE_37'), 245: (3, 'ROUTE_38')}
STATICS = {249: ('WHIRL_ISLAND_LUGIA_CHAMBER', ('EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA')),
           250: ('TIN_TOWER_ROOF', ('EVENT_FOUGHT_HO_OH', 'EVENT_TIN_TOWER_ROOF_HO_OH')),
           245: ('TIN_TOWER_1F', ('EVENT_FOUGHT_SUICUNE', 'EVENT_TIN_TOWER_1F_SUICUNE'))}
# Clearing these restarts Crystal's GS Ball quest at the Goldenrod Pokémon Center.
CELEBI_OPEN = (('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', False), ('EVENT_CAN_GIVE_GS_BALL_TO_KURT', False),
               ('EVENT_GAVE_GS_BALL_TO_KURT', False), ('EVENT_FOREST_IS_RESTLESS', False))
CELEBI_CLOSED = (('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', True), ('EVENT_CAN_GIVE_GS_BALL_TO_KURT', False),
                 ('EVENT_GAVE_GS_BALL_TO_KURT', True), ('EVENT_FOREST_IS_RESTLESS', False))
CELEBI_ROOMS = ('GOLDENROD_POKECENTER_1F', 'KURTS_HOUSE', 'AZALEA_TOWN', 'ILEX_FOREST')
SPRITE_SUDOWOODO, SPRITE_TWIN = 0x52, 0x26
WEIRD_TREE = 4  # SPRITE_WEIRD_TREE - SPRITE_VARS
# Overworld statics with no other source. The Red Gyarados stays one of a kind.
# (fought, shown): only the object flag reopens the encounter. The fought flag stays set because the
# cartridge also uses it for the Victory Road Gate guard and for NPC dialogue.
ACTIVITIES = (('sudowoodo', 'Sudowoodo', 185, 'ROUTE_36', ('EVENT_FOUGHT_SUDOWOODO', 'EVENT_ROUTE_36_SUDOWOODO')),
              ('snorlax', 'Snorlax', 143, 'VERMILION_CITY', ('EVENT_FOUGHT_SNORLAX', 'EVENT_VERMILION_CITY_SNORLAX')))
# One-time gifts with no other source, as (key, name, room, flag, species that count as the gift).
# Each giver's script checks only its own GOT flag (pret pokegold and pokecrystal), so clearing it
# away from the room offers the gift again. Kiyo's beaten flag stays set, so he hands over Tyrogue
# without another battle. Togepi's egg, Shuckie and Kenya's Spearow are left alone because their
# givers move on with the story or take the Pokémon back.
GIFTS = (('gift_eevee', 'Eevee gift', 'BILLS_FAMILYS_HOUSE', 'EVENT_GOT_EEVEE', (133,)),
         ('gift_odd_egg', 'Odd Egg gift', 'DAY_CARE', 'EVENT_GOT_ODD_EGG', (172, 173, 174, 236, 238, 239, 240)),
         ('gift_dratini', 'Dratini gift', 'DRAGON_SHRINE', 'EVENT_GOT_DRATINI', (147,)),
         ('gift_tyrogue', 'Tyrogue gift', 'MOUNT_MORTAR_B1F', 'EVENT_GOT_TYROGUE_FROM_KIYO', (236,)))


def interval():
    return getattr(config, 'LEGENDARY_RETURN_STEPS', 1000000)


def event_interval():
    return getattr(config, 'EVENT_RETURN_STEPS', 100000)


def legends(data):
    """Dex numbers that can return in this game."""
    rows = [243, 244, 245, 249, 250]
    if data.game == 'crystal' and getattr(config, 'CELEBI_EVENT', False):
        rows.append(251)
    return rows


def roamer(memory, data, dex, *, present):
    """Put a roaming beast back at its starting route, or mark it caught."""
    slot, start = ROAMERS[dex]
    name = f'wRoamMon{slot}'
    raw = Memory(memory, data).read(name, 5)
    if present:
        if raw[0] == dex:
            return False
        mid = data.map_ids[start]
        values = (dex, 40, mid >> 8, mid & 0xFF, 0)  # HP 0 asks the cartridge for new stats.
    else:
        if raw[0] != dex:
            return False
        values = (0, raw[1], 0xFF, 0xFF, 0)
    for offset, value in enumerate(values):
        write_byte(memory, data, name, value, offset)
    return True


def roaming(data, dex):
    return dex in (243, 244) or dex == 245 and data.game != 'crystal'


def rooms(data, dex):
    if dex == 251:
        return {data.map_ids[name] for name in CELEBI_ROOMS}
    if roaming(data, dex):
        return set()
    return {data.map_ids[STATICS[dex][0]]}


def encounter(memory, data, dex, *, present):
    if roaming(data, dex):
        return roamer(memory, data, dex, present=present)
    if dex == 251:
        changed = False
        for name, value in (CELEBI_OPEN if present else CELEBI_CLOSED):
            changed |= write_flag(memory, data, name, value)
        return changed
    changed = False
    for name in STATICS[dex][1]:
        changed |= write_flag(memory, data, name, not present)
    if dex == 245 and present:
        changed |= write_byte(memory, data, 'wTinTower1FSceneID', 0)
    return changed


def celebi_spent(snapshot, data):
    """The GS Ball quest ran to its end without a Celebi capture."""
    return (all(snapshot.event(name) == value for name, value in CELEBI_CLOSED)
            and data.items['GS_BALL'] not in dict(snapshot.items))


def safe(snapshot, memory):
    return (snapshot.valid and snapshot.started and not snapshot.in_battle
            and not Memory(memory, snapshot.data).byte('wScriptRunning') and '┌' not in snapshot.tiles[12])


def observe(store, snapshot, memory, walking=None):
    """Open one claim per walking milestone and keep spent claims closed after restores."""
    data = snapshot.data
    every = interval()
    steps = walking if walking is not None else store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not steps.get('available', True):
        return [], False
    total = steps.get('total', 0)
    saved = store.get(KEY)
    value = dict(saved) if saved else {'cycle': 0, 'interval': every, 'next_at': every}
    if not every:
        value.update(interval=0, next_at=0)
        if value != saved:
            store.set(KEY, value)
        return [], False
    if value['interval'] != every:
        value.update(interval=every, next_at=total + every)
    from ..progress_events import frame
    events, changed, now = [], False, frame(store)
    with store.transaction() as db:
        found = return_claims.rows(db)
        if total >= value['next_at']:
            passed = 1 + (total - value['next_at']) // every
            value['cycle'] += passed
            value['next_at'] += passed * every
            return_claims.earn(db, [dex for dex in legends(data) if dex in snapshot.owned or dex in found], now)
            found = return_claims.rows(db)
        if safe(snapshot, memory):
            for dex in legends(data):
                row = found.get(dex)
                if not row or snapshot.map in rooms(data, dex):
                    continue
                if dex == 251 and Memory(memory, data).byte('sGSBallFlag') != 0x0b:
                    continue
                if row['state'] == ledger.OPEN:
                    changed |= encounter(memory, data, dex, present=True)
                    return_claims.deliver(db, dex, now)
                    if row['reasons'] != ledger.RELOADED:
                        events.append(Event('legendary_return', f'{data.species[dex]["name"]} has returned!',
                                            'Another encounter waits where it first appeared.', priority=4))
                elif row['state'] == ledger.DELIVERED and dex == 251 and celebi_spent(snapshot, data):
                    # Static and roaming misses go through Recovery. Celebi's quest needs the GS Ball again.
                    changed |= encounter(memory, data, dex, present=True)
                elif row['state'] in (ledger.CONSUMED, ledger.DECLINED):
                    # An older checkpoint cannot reopen a claim that was already caught or declined.
                    changed |= encounter(memory, data, dex, present=False)
        if value != saved:
            kv.put(db, KEY, value)
    return events, changed


def consume(db, dex):
    """Close a return in the same transaction as its verified capture receipt."""
    return_claims.consume(db, dex)
    for key, _, number, _, _ in ACTIVITIES:
        if number == dex:
            return_claims.consume_event(db, key)


decline, claims = return_claims.decline, return_claims.claims


def observe_events(store, snapshot, memory, walking=None, keeps=None):
    """Reopen Sudowoodo, Snorlax, the one-time gifts and trades after walking, once the Champion has finished the story.

    ``keeps(dex)`` says whether the PC would keep one more copy. A return or gift it would release is
    skipped until the next walking milestone and journaled once, so it is not received to be released.
    """
    data = snapshot.data
    steps = walking if walking is not None else store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not snapshot.hall_of_fame_count or not steps.get('available', True):
        return [], False
    every = event_interval()
    total = steps.get('total', 0)
    saved = store.get(EVENTS)
    value = json.loads(json.dumps(saved)) if saved else {'clocks': {}}
    clocks = value['clocks']
    events, changed = [], False
    ok = safe(snapshot, memory)
    from ..progress_events import frame
    now = frame(store)
    with store.transaction() as db:
        found = return_claims.events(db)
        for key, name, dex, room, flags in ACTIVITIES:
            here = snapshot.map == data.map_ids[room]
            clock, row = clocks.get(key), found.get(key)
            state = row['state'] if row else None
            if row is None and not snapshot.event(flags[0]):
                # The claims reset on restart, so a new game's encounter waits for its story battle.
                continue
            if clock is None:
                clock = clocks[key] = {'next_at': total + every, 'interval': every, 'cycle': 0, 'noted': 0}
            if clock['interval'] != every:
                clock.update(interval=every, next_at=total + every)
            if not ok or here:
                continue
            due = every and state not in (ledger.OPEN, ledger.DELIVERED) and total >= clock['next_at']
            if state == ledger.CONSUMED and clock.get('noted', clock['cycle']) < clock['cycle']:
                # The capture receipt closed the claim, so the journal reports it on this safe frame.
                clock.update(next_at=total + every, noted=clock['cycle'])
                events.append(Event('event_return', f'Caught the returning {name}',
                                    'The next return starts after more walking.', priority=3))
            elif state == ledger.OPEN:
                # A reload went back to before the return, so it waits again with no second notice.
                changed |= open_activity(memory, data, key, flags)
                return_claims.mark(db, key, ledger.DELIVERED, now, dex)
                state = ledger.DELIVERED
            elif state == ledger.DELIVERED and snapshot.event(flags[1]):
                # The battle ended without a capture, so the encounter waits on the next visit.
                changed |= open_activity(memory, data, key, flags)
            elif due and skipped(db, key, state, events, name, dex, keeps, now):
                clock.update(next_at=total + every)
                state = ledger.DECLINED
            elif due:
                clock['cycle'] += 1
                return_claims.mark(db, key, ledger.DELIVERED, now, dex)
                state = ledger.DELIVERED
                changed |= open_activity(memory, data, key, flags)
                events.append(Event('event_return', f'{name} has returned!',
                                    'A walking milestone brought it back to where it first appeared.', priority=3))
            elif state in (ledger.CONSUMED, ledger.DECLINED) and clock['cycle'] and not snapshot.event(flags[1]):
                # An older checkpoint cannot reopen a return that was already caught.
                for flag in flags:
                    changed |= write_flag(memory, data, flag, True)
            if key == 'sudowoodo' and state in (ledger.CONSUMED, ledger.DECLINED) and clock['cycle']:
                # Between returns the variable sprite belongs to Route 37's twins, as after the first battle.
                changed |= write_byte(memory, data, 'wVariableSprites', SPRITE_TWIN, WEIRD_TREE)
        for key, name, room, done, dexes in offers(data):
            changed |= _offer(db, found, clocks, events, snapshot, memory, ok, (key, name, room, done, dexes),
                              total, every, now, keeps if key.startswith('gift_') else None)
        if ok and (sprite := weird_tree(snapshot)) is not None:
            changed |= write_byte(memory, data, 'wVariableSprites', sprite, WEIRD_TREE)
        if value != saved:
            kv.put(db, EVENTS, value)
    return events, changed


def offers(data):
    """Gifts and NPC trades that walking brings back, as (key, name, room, done bit, counted species).

    The done bit is an event flag name for a gift and a wTradeFlags index for a trade. Only trades
    whose Pokémon has no other source come back: no wild row for it or anything that evolves into it.
    """
    cached = getattr(data, '_event_offers', None)
    if cached is not None:
        return cached
    rows = [(key, name, room, flag, dexes) for key, name, room, flag, dexes in GIFTS
            if flag in data.events and room in data.map_ids]
    if 'wTradeFlags' in data.symbols:
        from .npc_trades import trades, wild
        earlier = {}
        for species, row in data.species.items():
            for evolution in row['evolutions']:
                earlier.setdefault(evolution['species'], set()).add(species)
        for trade in trades(data.game):
            family, waiting = set(), [trade.give]
            while waiting:
                species = waiting.pop()
                if species not in family:
                    family.add(species)
                    waiting.extend(earlier.get(species, ()))
            if trade.map_name in data.map_ids and not any(wild(data, species) for species in family):
                rows.append((f'trade_{trade.index}', f"{data.species[trade.give]['name']} exchange",
                             trade.map_name, trade.index, (trade.give,)))
    cached = tuple(rows)
    try:
        data._event_offers = cached
    except AttributeError:
        pass
    return cached


def _done(snapshot, memory, data, bit):
    if isinstance(bit, str):
        return bool(snapshot.event(bit))
    return bool(Memory(memory, data).byte('wTradeFlags') >> bit & 1)


def _set(memory, data, bit, value):
    if isinstance(bit, str):
        return write_flag(memory, data, bit, value)
    flags = Memory(memory, data).byte('wTradeFlags')
    return write_byte(memory, data, 'wTradeFlags', flags | 1 << bit if value else flags & ~(1 << bit))


def population(snapshot, dexes):
    """Copies of a gift or trade Pokémon held in the party and the boxes, eggs included."""
    return sum(mon.species in dexes for mon in (*getattr(snapshot, 'party', ()), *getattr(snapshot, 'stored', ())))


def skipped(db, key, state, events, name, dex, keeps, now):
    """Whether a due return or gift is declined because the PC would release it. Journaled once per run of skips."""
    if keeps is None or keeps(dex):
        return False
    if state != ledger.DECLINED:
        return_claims.mark(db, key, ledger.DECLINED, now, dex, return_claims.SKIPPED)
        events.append(Event('event_skip', f'Skipped the {name}' if name.endswith(('gift', 'exchange'))
                            else f'Skipped the returning {name}',
                            'The PC would release it as a spare, so it waits for the next walking milestone.',
                            priority=1))
    return True


def _offer(db, found, clocks, events, snapshot, memory, ok, offer, total, every, now, keeps=None):
    """Walk one gift or trade's claim from walking to delivered to consumed."""
    key, name, room, bit, dexes = offer
    data = snapshot.data
    done, here = _done(snapshot, memory, data, bit), snapshot.map == data.map_ids[room]
    clock, row = clocks.get(key), found.get(key)
    state = row['state'] if row else None
    if row is None and not done:
        # The claims reset on restart, so a new game's gift or trade waits for its story visit.
        return False
    if clock is None:
        clock = clocks[key] = {'next_at': total + every, 'interval': every, 'cycle': 0, 'name': name, 'dex': dexes[0]}
    if clock['interval'] != every:
        clock.update(interval=every, next_at=total + every)
    if not ok:
        return False
    if state == ledger.OPEN:
        # A reload went back to before the offer, so it opens again with no second notice.
        if here:
            return False
        return_claims.mark(db, key, ledger.DELIVERED, now, dexes[0])
        return _set(memory, data, bit, False)
    if state == ledger.DELIVERED:
        if not done:
            if here:
                # Storage visits may move copies before the visit, so the gain is judged at the venue.
                clock['baseline'] = population(snapshot, dexes)
            return False
        if population(snapshot, dexes) > clock.get('baseline', 0):
            clock['next_at'] = total + every
            return_claims.mark(db, key, ledger.CONSUMED, now, dexes[0])
            events.append(Event('event_return', f'Completed the {name}',
                                'The next opportunity starts after more walking.', priority=3))
            return False
        # The bit is set without a new copy, so an older checkpoint was loaded. Offer it again.
        return _set(memory, data, bit, False) if not here else False
    if every and total >= clock['next_at'] and not here:
        if skipped(db, key, state, events, name, dexes[0], keeps, now):
            clock['next_at'] = total + every
            return False
        clock.update(cycle=clock['cycle'] + 1, baseline=population(snapshot, dexes))
        return_claims.mark(db, key, ledger.DELIVERED, now, dexes[0])
        events.append(Event('event_return', f'{name} available',
                            'A walking milestone unlocked another visit.', priority=3))
        return _set(memory, data, bit, False)
    if state in (ledger.CONSUMED, ledger.DECLINED) and clock['cycle'] and not done:
        # An older checkpoint cannot reopen a gift or trade that was already completed.
        return _set(memory, data, bit, True)
    return False


def weird_tree(snapshot):
    """The sprite the next map load should use for SPRITE_WEIRD_TREE while a returned Sudowoodo is out.

    Route 37's twins use the same variable sprite as Sudowoodo, and a map load reads it once. So the
    byte shows the twins on the approaches to Route 37 and Sudowoodo everywhere else, including the
    edge of Route 37 that leads back to Route 36.
    """
    if not snapshot.event('EVENT_FOUGHT_SUDOWOODO') or snapshot.event('EVENT_ROUTE_36_SUDOWOODO'):
        return None
    entry = snapshot.data.maps.get(snapshot.map, {})
    name = entry.get('constant')
    twins = (name == 'ECRUTEAK_CITY' or name == 'ROUTE_37' and snapshot.y < entry['height'] - 5
             or name == 'ROUTE_36' and snapshot.y < 4)
    return SPRITE_TWIN if twins else SPRITE_SUDOWOODO


def open_activity(memory, data, key, flags):
    changed = write_flag(memory, data, flags[1], False)
    return changed


def returned_events(store):
    if not event_interval():
        return set()
    ready = return_claims.delivered(store)
    found = {dex for key, _, dex, _, _ in ACTIVITIES if key in ready}
    # A reopened trade makes its Pokémon worth trading for again. Gifts need no catch, so they stay out.
    return found | {row['species'] for key, row in ready.items() if key.startswith('trade_') and row['species']}


def status(store, data=None):
    walking = store.get(STEPS) or {}
    value = store.get(KEY) or {}
    every = interval()
    total = walking.get('total', 0)
    remaining = max(0, value.get('next_at', every) - total) if every else None
    ready, _ = claims(store)
    return {'enabled': bool(every), 'available': bool(walking), 'steps': total, 'interval': every,
            'progress': max(0, every - remaining) if every else 0, 'remaining': remaining,
            'cycles': value.get('cycle', 0), 'started_at': walking.get('started_at'),
            'ready': sorted(ready)}


def event_status(store):
    total = (store.get(STEPS) or {}).get('total', 0)
    every = event_interval()
    clocks = (store.get(EVENTS) or {}).get('clocks', {})
    ready = return_claims.delivered(store)
    return {'enabled': bool(every), 'interval': every, 'activities': [
        {'key': key, 'name': clock.get('name'), 'ready': bool(every) and key in ready,
         'remaining': max(0, clock['next_at'] - total)}
        for key, clock in clocks.items()]}
