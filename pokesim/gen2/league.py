"""Durable individual League records for Gen II partners and exchanges."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import re
import uuid

from ..trade.preferences import identity
from .tracking import ancestors

KEY = 'gen2-league-partners-v1'


def read(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    return (json.loads(row[0]) if row else None) or {'origin': uuid.uuid4().hex, 'victories': [], 'partners': {}}


def save(db, value):
    db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))


@lru_cache(maxsize=1024)
def family(data, species):
    root = min(ancestors(data, species))
    return root, {row['name'].upper() for sid, row in data.species.items() if root in ancestors(data, sid)}


def signature(data, mon):
    root, names = family(data, mon['species'])
    name = mon.get('nick', '').upper()
    return identity(mon) + ':' + str(root), '' if name in names else name


def resolve(data, value, mons):
    signatures = [signature(data, mon) for mon in mons]
    counts = Counter(signatures)
    families = Counter(sig for sig, _ in signatures)
    keys = []
    for sig, name in signatures:
        matches = [(key, row) for key, row in value['partners'].items() if row['signature'] == sig]
        exact = [(key, row) for key, row in matches if name in row['names']]
        selected = exact if exact else matches if len(matches) == 1 and families[sig] == 1 else []
        if len(selected) == 1:
            key, row = selected[0]
            if name not in row['names']:
                row['names'].append(name)
        else:
            key = hashlib.sha256(json.dumps([sig, name]).encode()).hexdigest()[:24]
            row = value['partners'].setdefault(key, {'signature': sig, 'names': [name], 'counts': {}, 'ambiguous': False})
        row['ambiguous'] |= counts[sig, name] > 1 or len(exact) > 1
        keys.append(key)
    return keys


def record(store, data, snapshot):
    with store.lock, store.db:
        value = read(store.db)
        token = str(snapshot.hall_of_fame_count)
        if token in value['victories']:
            return
        if not value['victories'] and snapshot.hall_of_fame_count > 1:
            value['incomplete'] = True
        mons = [mon.to_dict() for mon in snapshot.party + snapshot.stored if not mon.egg]
        keys = resolve(data, value, mons)
        for key in set(keys[:sum(not mon.egg for mon in snapshot.party)]):
            row = value['partners'][key]
            if not row['ambiguous']:
                row['counts'][value['origin']] = row['counts'].get(value['origin'], 0) + 1
        value['victories'].append(token)
        save(store.db, value)


def apply(payload, store, data):
    party = [dict(mon) for mon in payload.get('party', [])]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', [])]
    with store.lock:
        value = read(store.db)
    mons = [mon for mon in party + boxed if not mon.get('egg')]
    keys = resolve(data, value, mons)
    for mon, key in zip(mons, keys):
        row = value['partners'][key]
        mon['elite_four_wins'] = None if row['ambiguous'] else sum(row['counts'].values())
        mon['elite_four_wins_incomplete'] = bool(value.get('incomplete') or row.get('incomplete'))
    return {**payload, 'party': party, 'storage': {**storage, 'pokemon': boxed} if storage else None}


def export(store, data, mon):
    with store.lock, store.db:
        value = read(store.db)
        key = resolve(data, value, [mon])[0]
        save(store.db, value)
        return {**value['partners'][key], 'key': identity(mon), 'individual': key,
                'version': 'gen2-1', 'incomplete': bool(value.get('incomplete'))}


def validate(incoming, data=None, mon=None):
    if incoming is None:
        return None
    if (not isinstance(incoming, dict) or incoming.get('version') != 'gen2-1'
            or not isinstance(incoming.get('key'), str) or not re.fullmatch('[a-f0-9]{24}', incoming['key'])
            or not isinstance(incoming.get('individual'), str) or not re.fullmatch('[a-f0-9]{24}', incoming['individual'])
            or not isinstance(incoming.get('signature'), str)
            or not re.fullmatch(incoming['key'] + ':[0-9]{1,3}', incoming['signature'])
            or type(incoming.get('ambiguous')) is not bool or type(incoming.get('incomplete')) is not bool
            or not isinstance(incoming.get('names'), list) or not 1 <= len(incoming['names']) <= 1000
            or any(not isinstance(name, str) or len(name) > 20 for name in incoming['names'])
            or not isinstance(incoming.get('counts'), dict) or len(incoming['counts']) > 10000
            or any(not isinstance(origin, str) or not re.fullmatch('[a-f0-9]{32}', origin)
                   or type(count) is not int or not 0 <= count <= 10**9 for origin, count in incoming['counts'].items())):
        raise ValueError('Invalid incoming Gen II League record')
    if mon is not None:
        sig, name = signature(data, mon)
        if sig != incoming['signature'] or name not in incoming['names']:
            raise ValueError('The League record belongs to a different Gen II partner')
    return incoming


def merge(db, incoming):
    if validate(incoming) is None:
        return
    value = read(db)
    matches = [key for key, row in value['partners'].items() if row['signature'] == incoming['signature']
               and set(row['names']) & set(incoming['names'])]
    if len(matches) > 1:
        raise ValueError('Conflicting Gen II League identities')
    key = matches[0] if matches else incoming['individual']
    row = value['partners'].setdefault(key, {'signature': incoming['signature'], 'names': [], 'counts': {}, 'ambiguous': False})
    if row['signature'] != incoming['signature']:
        raise ValueError('Conflicting Gen II League identity')
    row['names'] = sorted(set(row['names']) | set(incoming['names']))
    for origin, count in incoming['counts'].items():
        row['counts'][origin] = max(row['counts'].get(origin, 0), count)
    row['ambiguous'] |= incoming['ambiguous']
    row['incomplete'] = row.get('incomplete', False) or incoming['incomplete']
    save(db, value)
