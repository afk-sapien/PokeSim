"""Repeat native gifts and exchanges through durable walking opportunities.

Each activity's return is an ``event`` row in the claims ledger (return_claims). The kv value
keeps each activity's walking clock, its fossil and dojo choice, the count at the venue, and the
guards that keep a spent room closed.
"""
from dataclasses import dataclass
import json
from functools import lru_cache
from pokecore.gen1 import W_COMPLETED_IN_GAME_TRADE_FLAGS
from pokecore.resets import Flag, update_flags

from . import config, return_claims
from .events import Event
from .state import claims as ledger, kv
from .game_data import current_variant
from .legendary_returns import STEPS
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .strategy_data import DATA, EVENTS, ITEMS, MAPS, SPECIES, WORLD, event_set

KEY = 'step-events-v1'
TRADE_FLAGS = W_COMPLETED_IN_GAME_TRADE_FLAGS
FOSSILS = {'helix': (138, 'HELIX_FOSSIL'), 'dome': (140, 'DOME_FOSSIL'), 'amber': (142, 'OLD_AMBER')}
# In-game trades for species with no other source, as indexes into TradeMons.
TRADES = ((1, 122, 'ROUTE_2_TRADE_HOUSE'), (4, 83, 'VERMILION_TRADE_HOUSE'),
          (5, 108, 'ROUTE_18_GATE_2F'), (6, 124, 'CERULEAN_TRADE_HOUSE'))
if current_variant() == 'yellow':
    # Yellow trades Mr. Mime only. Its other trades offer species found in the wild.
    TRADES = ((1, 122, 'ROUTE_2_TRADE_HOUSE'),)


def snorlax():
    """The Route 12 Snorlax's beaten flag and object bit.

    The route script hides Snorlax as the battle starts and sets the beaten flag once it ends. A
    blackout skips the flag, so either bit alone means the encounter was spent.
    """
    return flag('EVENT_BEAT_ROUTE12_SNORLAX'), toggle('ROUTE_12', named('ROUTE_12', 'SNORLAX'))


def named(room, label):
    """The index of the room object whose text names it, since Yellow adds objects before some."""
    objects = WORLD[MAPS[room]]['objects']
    return next(i for i, row in enumerate(objects) if label in row[4])


def flag(name):
    return W_EVENT_FLAGS, EVENTS[name]


def toggle(room, obj):
    return W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([MAPS[room], obj])


def read(memory, bit):
    base, index = bit
    return bool(memory[base + index // 8] & (1 << (index % 8)))


def write(memory, bit, value):
    return bool(update_flags(memory, ((Flag(*bit), bool(value)),)))


@dataclass(frozen=True)
class Activity:
    key: str
    name: str
    room: int
    dex: int
    bits: tuple
    done: tuple
    item: str | None = None
    # A wild encounter is judged after leaving its room, once the room script has finished.
    encounter: bool = False


@lru_cache(maxsize=6)
def activities(choice='helix', dojo=106):
    rows = [Activity('eevee', 'Eevee gift', MAPS['CELADON_MANSION_ROOF_HOUSE'], 133,
                     (toggle('CELADON_MANSION_ROOF_HOUSE', 1),),
                     (toggle('CELADON_MANSION_ROOF_HOUSE', 1),)),
            Activity('dojo', 'Dojo rematch', MAPS['FIGHTING_DOJO'], dojo,
                     tuple(flag(n) for n in ('EVENT_BEAT_KARATE_MASTER', 'EVENT_DEFEATED_FIGHTING_DOJO',
                                             'EVENT_GOT_HITMONLEE', 'EVENT_GOT_HITMONCHAN'))
                     + (toggle('FIGHTING_DOJO', 5), toggle('FIGHTING_DOJO', 6)),
                     (flag('EVENT_GOT_HITMONLEE'), flag('EVENT_GOT_HITMONCHAN'))),
            Activity('snorlax', 'Snorlax', MAPS['ROUTE_12'], 143, snorlax(), snorlax(), encounter=True)]
    dex, item = FOSSILS[choice]
    if choice == 'amber':
        bits = (flag('EVENT_GOT_OLD_AMBER'), toggle('MUSEUM_1F', 4))
        rows.append(Activity('fossil', 'Fossil expedition', MAPS['MUSEUM_1F'], dex, bits, bits[:1], item))
    else:
        bits = (flag('EVENT_GOT_HELIX_FOSSIL'), flag('EVENT_GOT_DOME_FOSSIL'),
                toggle('MT_MOON_B2F', named('MT_MOON_B2F', 'DOME_FOSSIL')),
                toggle('MT_MOON_B2F', named('MT_MOON_B2F', 'HELIX_FOSSIL')))
        rows.append(Activity('fossil', 'Fossil expedition', MAPS['MT_MOON_B2F'], dex, bits, bits[:2], item))
    rows.extend(Activity(f'trade_{index}', f'{SPECIES[next(s for s in SPECIES if SPECIES[s]["dex"] == dex)]["name"].title()} exchange',
                         MAPS[room], dex, ((TRADE_FLAGS, index),), ((TRADE_FLAGS, index),))
                for index, dex, room in TRADES)
    return tuple(rows)


def choices(snapshot):
    """Prefer missing families, then the weakest known natural potential."""
    from dataclasses import asdict
    mons = [asdict(mon) for mon in snapshot.party] + snapshot.storage_entries()
    def rank(dexes):
        owned = sum(dex in snapshot.owned for dex in dexes)
        qualities = [sum(mon.get('dvs', ())) for mon in mons if SPECIES[mon['species']]['dex'] in dexes]
        complete = owned == len(dexes)
        return complete, (0 if complete else owned), max(qualities, default=0)
    fossil = getattr(config, 'FOSSIL_PREFERENCE', 'auto')
    if fossil == 'auto':
        fossil = min(FOSSILS, key=lambda key: rank({'helix': (138, 139), 'dome': (140, 141), 'amber': (142,)}[key]))
    dojo = getattr(config, 'DOJO_PREFERENCE', 'auto')
    return fossil, (min((106, 107), key=lambda dex: rank((dex,))) if dojo == 'auto'
                    else 106 if dojo == 'hitmonlee' else 107)


def observe(store, snapshot, memory, keeps=None):
    """Open, close and journal each activity's walking return, and say whether the cartridge changed.

    ``keeps(dex)`` says whether the PC would keep one more copy, rated with no DVs as the battle rates
    one with its own (collection.improves). A returning encounter it would release is skipped until the
    next walking milestone and journaled once, as Gen II skips one (gen2/returns.py). Snorlax's DVs are
    rolled in the battle, which catches only a copy the PC keeps. Blue and Yellow walked to Route 12
    for every return, knocked out the copy they met and found Snorlax back the moment they left.
    """
    walking = store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not walking.get('available'):
        return [], False
    from .policies.collection import champion
    if not champion(snapshot):
        return [], False
    from .progress_events import frame
    every = getattr(config, 'EVENT_RETURN_STEPS', 100000)
    total = walking.get('total', 0)
    saved = store.get(KEY) or {'clocks': {}}
    value = json.loads(json.dumps(saved))
    fossil, dojo = 'helix', 106
    clocks = value['clocks']
    events, changed, now = [], False, frame(store)
    safe = not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu
    with store.transaction() as db:
        found = return_claims.events(db)
        for default in activities(fossil, dojo):
            clock, row = clocks.get(default.key), found.get(default.key)
            state = row['state'] if row else None
            if row is None:
                # The claims reset on restart, so a new game's activity waits for its story.
                eligible = any(read(memory, bit) for bit in default.done)
                if default.key == 'fossil':
                    eligible = bool(snapshot.owned & {138, 139, 140, 141, 142})
                if not eligible:
                    continue
            if clock is None:
                clock = clocks[default.key] = {'next_at': total + every, 'interval': every, 'cycle': 0,
                                               'choice': fossil, 'dojo': dojo}
            spec = next(a for a in activities(clock['choice'], clock['dojo']) if a.key == default.key)
            if clock['interval'] != every:
                clock.update(interval=every, next_at=total + every)
            if state == ledger.OPEN and safe and snapshot.map not in (default.room, spec.room):
                # A reload went back to before the visit opened, so it opens again with no second notice.
                for bit in spec.bits:
                    changed |= write(memory, bit, False)
                return_claims.mark(db, spec.key, ledger.DELIVERED, now, spec.dex)
                state = ledger.DELIVERED
            if (state == ledger.DELIVERED and safe and snapshot.map == spec.room
                    and not any(read(memory, bit) for bit in spec.done)):
                # PC preparation may release a spare before the visit. Compare the
                # acquisition with inventory at the venue, not at the walking milestone.
                clock['baseline'] = population(snapshot, spec)
            if (state == ledger.DELIVERED and safe and any(read(memory, bit) for bit in spec.done)
                    and not (spec.encounter and snapshot.map == spec.room)):
                acquired = population(snapshot, spec) > clock.get('baseline', 0)
                if not acquired:
                    if snapshot.map != spec.room and skipped(db, spec, state, events, keeps, now):
                        # The battle met a copy the PC would release, so the encounter stays spent.
                        clock['next_at'] = total + every
                        hold_closed(value, spec, memory)
                    elif snapshot.map != spec.room:
                        for bit in spec.bits:
                            changed |= write(memory, bit, False)
                    continue
                clock['next_at'] = total + every
                return_claims.mark(db, spec.key, ledger.CONSUMED, now, spec.dex)
                state = ledger.CONSUMED
                hold_closed(value, spec, memory)
                events.append(Event('event_return', f'Caught the returning {spec.name}' if spec.encounter
                                    else f'Completed {spec.name.lower()}',
                                    'The next opportunity starts after more walking.', priority=3))
            if (every and state not in (ledger.OPEN, ledger.DELIVERED) and total >= clock['next_at']
                    and safe and snapshot.map not in (default.room, spec.room)):
                # Finish any fossil already in the bag or lab before offering another.
                if default.key == 'fossil' and (any(dict(snapshot.items).get(ITEMS[item]) for _, item in FOSSILS.values())
                        or event_set(snapshot.event_flags, 'EVENT_GAVE_FOSSIL_TO_LAB')):
                    continue
                fossil, dojo = choices(snapshot)
                spec = next(a for a in activities(fossil, dojo) if a.key == default.key)
                if snapshot.map == spec.room:
                    continue
                if skipped(db, spec, state, events, keeps, now):
                    clock['next_at'] = total + every
                    continue
                clock.update(choice=fossil, dojo=dojo, cycle=clock['cycle'] + 1, baseline=population(snapshot, spec))
                return_claims.mark(db, spec.key, ledger.DELIVERED, now, spec.dex)
                for bit in spec.bits:
                    changed |= write(memory, bit, False)
                events.append(Event('event_return', f'{spec.name} has returned!' if spec.encounter
                                    else f'{spec.name} available',
                                    'A walking milestone unlocked another visit.', priority=3))
        if safe:
            opened = {key for key, row in return_claims.events(db).items()
                      if row['state'] in (ledger.OPEN, ledger.DELIVERED)}
            opened_bits = {bit for key, clock in clocks.items() if key in opened
                           for activity in activities(clock['choice'], clock['dojo']) if activity.key == key
                           for bit in activity.bits}
            for guard in value.get('guards', {}).values():
                if snapshot.map != guard['room']:
                    for bit, closed in zip(guard['bits'], guard['closed']):
                        if tuple(bit) not in opened_bits:
                            changed |= write(memory, bit, closed)
        if value != saved:
            kv.put(db, KEY, value)
    return events, changed


def skipped(db, spec, state, events, keeps, now):
    """Whether a returning encounter is declined because the PC would release it, journaled once per run of skips."""
    if keeps is None or not spec.encounter or keeps(spec.dex):
        return False
    if state != ledger.DECLINED:
        return_claims.mark(db, spec.key, ledger.DECLINED, now, spec.dex, return_claims.SKIPPED)
        events.append(Event('event_skip', f'Skipped the returning {spec.name}',
                            'The PC would release it as a spare, so it waits for the next walking milestone.',
                            priority=1))
    return True


def hold_closed(value, spec, memory):
    """Keep the activity's bits as they are now while it is closed, so an older checkpoint cannot reopen it."""
    value.setdefault('guards', {})[f'{spec.key}:{spec.room}'] = {
        'room': spec.room, 'bits': spec.bits, 'closed': [int(read(memory, bit)) for bit in spec.bits]}


def population(snapshot, spec):
    dexes = (106, 107) if spec.key == 'dojo' else (spec.dex,)
    count = sum(SPECIES[p.species]['dex'] in dexes for p in snapshot.party)
    count += sum(SPECIES[sid]['dex'] in dexes for box, sid, level, nick in snapshot.stored_pokemon)
    if spec.item:
        count += dict(snapshot.items).get(ITEMS[spec.item], 0)
        count += bool(event_set(snapshot.event_flags, 'EVENT_GAVE_FOSSIL_TO_LAB'))
    return count


def available(store):
    """The activities whose flags wait cleared in the cartridge, with the Pokémon, room and item each gives."""
    if not getattr(config, 'EVENT_RETURN_STEPS', 100000):
        return {}
    clocks = (store.get(KEY) or {}).get('clocks', {})
    rows = {}
    for key in return_claims.delivered(store):
        if (clock := clocks.get(key)) is not None:
            spec = next(a for a in activities(clock['choice'], clock['dojo']) if a.key == key)
            rows[key] = {'dex': spec.dex, 'room': spec.room, 'item': spec.item}
    return rows


def status(store):
    total = (store.get(STEPS) or {}).get('total', 0)
    enabled = bool(getattr(config, 'EVENT_RETURN_STEPS', 100000))
    ready = return_claims.delivered(store)
    return {'enabled': enabled, 'interval': getattr(config, 'EVENT_RETURN_STEPS', 100000), 'activities': [
        {'key': key, 'ready': enabled and key in ready, 'remaining': max(0, clock['next_at'] - total)}
        for key, clock in (store.get(KEY) or {}).get('clocks', {}).items()]}
