"""Durable Hall of Fame participation, carried with identifiable partners."""
from collections import Counter
from dataclasses import asdict
import json
import re
import uuid

from .trade.preferences import identity
from .ram import HALL_OF_FAME_MAP

KEY = 'league-partners-v1'


def read(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else {
        'origin': uuid.uuid4().hex, 'victories': [], 'partners': {}}


def save(db, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (KEY, json.dumps(value)))


def record(db, snapshot, title, event_id):
    """Run in the event transaction. Replayed victory ordinals count once."""
    if not snapshot.valid or snapshot.map != HALL_OF_FAME_MAP:
        return False
    match = re.fullmatch(r'Champion! League victory #(\d+)', title)
    token = 'league:' + match[1] if match else f'event:{event_id}'
    value = read(db)
    if token in value['victories']:
        return False
    party = [asdict(mon) for mon in snapshot.party]
    counts = Counter(identity(mon) for mon in party + snapshot.storage_entries())
    for key in {identity(mon) for mon in party} - {None}:
        entry = value['partners'].setdefault(key, {'counts': {}, 'ambiguous': False})
        if counts[key] != 1:
            entry['ambiguous'] = True
        elif not entry['ambiguous']:
            origin = value['origin']
            entry['counts'][origin] = entry['counts'].get(origin, 0) + 1
    value['victories'].append(token)
    save(db, value)
    return True


def export(store, key):
    with store.lock:
        entry = read(store.db)['partners'].get(key, {'counts': {}, 'ambiguous': False})
    return {'key': key, **entry}


def validate(incoming, key):
    if incoming is None:
        return None
    if not isinstance(incoming, dict):
        raise ValueError('Invalid incoming Elite Four record')
    counts = incoming.get('counts')
    if (not isinstance(key, str) or not re.fullmatch('[0-9a-f]{24}', key)
            or incoming.get('key') != key or not isinstance(counts, dict)
            or len(counts) > 10000 or type(incoming.get('ambiguous')) is not bool
            or any(not isinstance(origin, str) or not re.fullmatch('[0-9a-f]{32}', origin)
                   or type(count) is not int or not 0 <= count <= 10**9
                   for origin, count in counts.items())):
        raise ValueError('Invalid incoming Elite Four record')
    return incoming


def merge(db, incoming):
    """Component maxima preserve wins through retries and return trades."""
    if incoming is None:
        return
    validate(incoming, incoming.get('key'))
    value = read(db)
    entry = value['partners'].setdefault(incoming['key'], {'counts': {}, 'ambiguous': False})
    for origin, count in incoming['counts'].items():
        entry['counts'][origin] = max(entry['counts'].get(origin, 0), count)
    entry['ambiguous'] = entry['ambiguous'] or incoming['ambiguous']
    save(db, value)


def apply(payload, store):
    with store.lock:
        entries = read(store.db)['partners']
    party = [dict(mon) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', ())]
    counts = Counter(identity(mon) for mon in party + boxed)
    for mon in party + boxed:
        key = identity(mon)
        entry = entries.get(key, {})
        known = bool(key and counts[key] == 1 and not entry.get('ambiguous'))
        mon['elite_four_wins'] = sum(entry.get('counts', {}).values()) if known else None
    return {**payload, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}
