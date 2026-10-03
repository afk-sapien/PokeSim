"""Repeat native gifts and exchanges through durable walking opportunities."""
from dataclasses import dataclass
import json
from functools import lru_cache
from pokesim_core.resets import Flag, update_flags

from . import config
from .events import Event
from .legendary_returns import STEPS
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .strategy_data import DATA, EVENTS, ITEMS, MAPS, SPECIES, event_set

KEY = 'step-events-v1'
TRADE_FLAGS = 0xD737
FOSSILS = {'helix': (138, 'HELIX_FOSSIL'), 'dome': (140, 'DOME_FOSSIL'), 'amber': (142, 'OLD_AMBER')}
TRADES = ((1, 122, 'ROUTE_2_TRADE_HOUSE'), (4, 83, 'VERMILION_TRADE_HOUSE'),
          (5, 108, 'ROUTE_18_GATE_2F'), (6, 124, 'CERULEAN_TRADE_HOUSE'))


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


@lru_cache(maxsize=6)
def activities(choice='helix', dojo=106):
    rows = [Activity('eevee', 'Eevee gift', MAPS['CELADON_MANSION_ROOF_HOUSE'], 133,
                     (toggle('CELADON_MANSION_ROOF_HOUSE', 1),),
                     (toggle('CELADON_MANSION_ROOF_HOUSE', 1),)),
            Activity('dojo', 'Dojo rematch', MAPS['FIGHTING_DOJO'], dojo,
                     tuple(flag(n) for n in ('EVENT_BEAT_KARATE_MASTER', 'EVENT_DEFEATED_FIGHTING_DOJO',
                                             'EVENT_GOT_HITMONLEE', 'EVENT_GOT_HITMONCHAN'))
                     + (toggle('FIGHTING_DOJO', 5), toggle('FIGHTING_DOJO', 6)),
                     (flag('EVENT_GOT_HITMONLEE'), flag('EVENT_GOT_HITMONCHAN')))]
    dex, item = FOSSILS[choice]
    if choice == 'amber':
        bits = (flag('EVENT_GOT_OLD_AMBER'), toggle('MUSEUM_1F', 4))
        rows.append(Activity('fossil', 'Fossil expedition', MAPS['MUSEUM_1F'], dex, bits, bits[:1], item))
    else:
        bits = (flag('EVENT_GOT_HELIX_FOSSIL'), flag('EVENT_GOT_DOME_FOSSIL'),
                toggle('MT_MOON_B2F', 5), toggle('MT_MOON_B2F', 6))
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


def observe(store, snapshot, memory):
    walking = store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not walking.get('available'):
        return [], False
    from .policies.collection import champion
    if not champion(snapshot):
        return [], False
    every = getattr(config, 'EVENT_RETURN_STEPS', 100000)
    total = walking.get('total', 0)
    saved = store.get(KEY) or {'tickets': {}}
    value = json.loads(json.dumps(saved))
    fossil, dojo = 'helix', 106
    tickets = value['tickets']
    events, changed = [], False
    safe = not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu
    for default in activities(fossil, dojo):
        ticket = tickets.get(default.key)
        if ticket is None:
            eligible = any(read(memory, bit) for bit in default.done)
            if default.key == 'fossil':
                eligible = bool(snapshot.owned & {138, 139, 140, 141, 142})
            if not eligible:
                continue
            ticket = tickets[default.key] = {'state': 'walking', 'next_at': total + every,
                'interval': every, 'cycle': 0, 'choice': fossil, 'dojo': dojo}
        spec = next(a for a in activities(ticket['choice'], ticket['dojo']) if a.key == default.key)
        if ticket['interval'] != every:
            ticket.update(interval=every, next_at=total + every)
        if (ticket['state'] == 'available' and safe and snapshot.map == spec.room
                and not any(read(memory, bit) for bit in spec.done)):
            # PC preparation may release a spare before the visit. Compare the
            # acquisition with inventory at the venue, not at the walking milestone.
            ticket['baseline'] = population(snapshot, spec)
        if ticket['state'] == 'available' and safe and any(read(memory, bit) for bit in spec.done):
            acquired = population(snapshot, spec) > ticket.get('baseline', 0)
            if not acquired:
                if snapshot.map != spec.room:
                    for bit in spec.bits:
                        changed |= write(memory, bit, False)
                continue
            ticket.update(state='walking', next_at=total + every)
            value.setdefault('guards', {})[f'{spec.key}:{spec.room}'] = {
                'room': spec.room, 'bits': spec.bits,
                'closed': [int(read(memory, bit)) for bit in spec.bits]}
            events.append(Event('event_return', f'Completed {spec.name.lower()}',
                                'The next opportunity starts after more walking.', priority=3))
        if (every and ticket['state'] == 'walking' and total >= ticket['next_at']
                and safe and snapshot.map not in (default.room, spec.room)):
            # Finish any fossil already in the bag or lab before offering another.
            if default.key == 'fossil' and (any(dict(snapshot.items).get(ITEMS[item]) for _, item in FOSSILS.values())
                    or event_set(snapshot.event_flags, 'EVENT_GAVE_FOSSIL_TO_LAB')):
                continue
            fossil, dojo = choices(snapshot)
            spec = next(a for a in activities(fossil, dojo) if a.key == default.key)
            if snapshot.map == spec.room:
                continue
            ticket.update(state='available', choice=fossil, dojo=dojo, cycle=ticket['cycle'] + 1,
                          baseline=population(snapshot, spec))
            for bit in spec.bits:
                changed |= write(memory, bit, False)
            events.append(Event('event_return', f'{spec.name} available',
                                'A walking milestone unlocked another visit.', priority=3))
    if safe:
        opened_bits = {bit for key, ticket in tickets.items() if ticket['state'] == 'available'
                       for activity in activities(ticket['choice'], ticket['dojo']) if activity.key == key
                       for bit in activity.bits}
        for guard in value.get('guards', {}).values():
            if snapshot.map != guard['room']:
                for bit, closed in zip(guard['bits'], guard['closed']):
                    if tuple(bit) not in opened_bits:
                        changed |= write(memory, bit, closed)
    if value != saved:
        store.set(KEY, value)
    return events, changed


def population(snapshot, spec):
    dexes = (106, 107) if spec.key == 'dojo' else (spec.dex,)
    count = sum(SPECIES[p.species]['dex'] in dexes for p in snapshot.party)
    count += sum(SPECIES[sid]['dex'] in dexes for box, sid, level, nick in snapshot.stored_pokemon)
    if spec.item:
        count += dict(snapshot.items).get(ITEMS[spec.item], 0)
        count += bool(event_set(snapshot.event_flags, 'EVENT_GAVE_FOSSIL_TO_LAB'))
    return count


def available(store):
    if not getattr(config, 'EVENT_RETURN_STEPS', 100000):
        return {}
    rows = {}
    for key, ticket in (store.get(KEY) or {}).get('tickets', {}).items():
        if ticket['state'] == 'available':
            spec = next(a for a in activities(ticket['choice'], ticket['dojo']) if a.key == key)
            rows[key] = {'dex': spec.dex, 'room': spec.room, 'item': spec.item}
    return rows


def status(store):
    total = (store.get(STEPS) or {}).get('total', 0)
    enabled = bool(getattr(config, 'EVENT_RETURN_STEPS', 100000))
    return {'enabled': enabled, 'interval': getattr(config, 'EVENT_RETURN_STEPS', 100000), 'activities': [
        {'key': key, 'ready': enabled and ticket['state'] == 'available',
         'remaining': max(0, ticket['next_at'] - total)}
        for key, ticket in (store.get(KEY) or {}).get('tickets', {}).items()]}
