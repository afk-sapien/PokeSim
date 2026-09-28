"""Durable Hall of Fame participation with evolution-aware individual records."""
from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
import re
import uuid

from .trade.preferences import identity
from .ram import HALL_OF_FAME_MAP
from .milestones import ancestors
from .strategy_data import SPECIES

KEY = 'league-partners-v2'
LEGACY_KEY = 'league-partners-v1'


def _read(db, key):
    row = db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def read(db):
    legacy = _read(db, LEGACY_KEY) or {}
    return _read(db, KEY) or {
        'origin': legacy.get('origin', uuid.uuid4().hex), 'victories': [], 'partners': {}}


def save(db, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (KEY, json.dumps(value)))


@lru_cache(maxsize=None)
def family(species):
    return min(sid for sid in ancestors(species) if ancestors(sid) == {sid})


def signature(mon):
    old = identity(mon)
    species = mon.get('species')
    if not old or species not in SPECIES:
        return None
    return f'{old}:{family(species)}'


@lru_cache(maxsize=None)
def default_names(root):
    return {row['name'].upper() for sid, row in SPECIES.items() if family(sid) == root}


def nickname(mon):
    name = mon.get('nick', '').upper()
    # The cartridge updates an unnicknamed partner's name when it evolves.
    defaults = default_names(family(mon['species']))
    return '' if name in defaults else name


def resolve(value, mons, *, allow_rename=True):
    """Match persistent records, using names to separate identical family/DV data.

    A unique remaining record can acquire a rename alias. Exact twins stay
    unresolved, since neither box position nor level is an individual identity.
    """
    groups = defaultdict(list)
    result = [None] * len(mons)
    for i, mon in enumerate(mons):
        sig = signature(mon)
        if sig:
            groups[sig].append(i)
    for sig, indices in groups.items():
        entries = {key: entry for key, entry in value['partners'].items() if entry['signature'] == sig}
        names = Counter(nickname(mons[i]) for i in indices)
        used = set()
        pending = []
        for i in indices:
            name = nickname(mons[i])
            matches = [key for key, entry in entries.items() if name in entry['names']]
            if names[name] > 1 or len(matches) > 1:
                if not matches:
                    key = hashlib.sha256(json.dumps([sig, name]).encode()).hexdigest()[:24]
                    value['partners'][key] = {'signature': sig, 'names': [name],
                                              'counts': {}, 'ambiguous': True}
                for key in matches:
                    entries[key]['ambiguous'] = True
                continue
            if matches:
                result[i] = matches[0]
                if matches[0] in used:
                    entries[matches[0]]['ambiguous'] = True
                used.add(matches[0])
            else:
                pending.append(i)
        remaining = set(entries) - used
        for i in pending:
            name = nickname(mons[i])
            if allow_rename and len(pending) == 1 and len(remaining) == 1 and len(indices) == len(entries):
                key = next(iter(remaining))
                entries[key]['names'].append(name)
            else:
                key = hashlib.sha256(json.dumps([sig, name]).encode()).hexdigest()[:24]
                value['partners'].setdefault(key, {'signature': sig, 'names': [name],
                                                  'counts': {}, 'ambiguous': False})
            result[i] = key
    return result


def record(db, snapshot, title, event_id, *, allow_rename=True):
    """Run in the event transaction. Replayed victory ordinals count once."""
    if not snapshot.valid or snapshot.map != HALL_OF_FAME_MAP:
        return False
    match = re.fullmatch(r'Champion! League victory #(\d+)', title)
    token = 'league:' + match[1] if match else f'event:{event_id}'
    value = read(db)
    if token in value['victories']:
        return False
    party = [asdict(mon) for mon in snapshot.party]
    keys = resolve(value, party + snapshot.storage_entries(), allow_rename=allow_rename)
    for key in set(keys[:len(party)]) - {None}:
        entry = value['partners'][key]
        if allow_rename:
            entry['counts'], entry['incomplete'] = totals(value, entry, _read(db, LEGACY_KEY) or {})
        if not entry['ambiguous']:
            origin = value['origin']
            entry['counts'][origin] = entry['counts'].get(origin, 0) + 1
    value['victories'].append(token)
    save(db, value)
    legacy = _read(db, LEGACY_KEY) or {}
    return token not in legacy.get('victories', ())


def export(store, key, mon=None):
    with store.lock:
        value = read(store.db)
        if mon is not None:
            resolved = resolve(value, [mon])[0]
        else:
            matches = [k for k, entry in value['partners'].items()
                       if entry['signature'].split(':')[0] == key]
            resolved = matches[0] if len(matches) == 1 else None
        entry = value['partners'].get(resolved)
        if entry is not None:
            with store.db:
                save(store.db, value)
            counts, incomplete = totals(value, entry, _read(store.db, LEGACY_KEY) or {})
            return {'key': key, 'version': 2, 'individual': resolved, **entry,
                    'counts': counts, 'incomplete': incomplete}
        return {'key': key, 'counts': {}, 'ambiguous': False}


def validate(incoming, key, mon=None):
    if incoming is None:
        return None
    if not isinstance(incoming, dict):
        raise ValueError('Invalid incoming Elite Four record')
    counts = incoming.get('counts')
    if (not isinstance(key, str) or not re.fullmatch('[0-9a-f]{24}', key)
            or incoming.get('key') != key or not isinstance(counts, dict)
            or len(counts) > 10000 or type(incoming.get('ambiguous')) is not bool
            or type(incoming.get('incomplete', False)) is not bool
            or any(not isinstance(origin, str) or not re.fullmatch('[0-9a-f]{32}', origin)
                   or type(count) is not int or not 0 <= count <= 10**9
                   for origin, count in counts.items())):
        raise ValueError('Invalid incoming Elite Four record')
    if incoming.get('version') == 2:
        sig = incoming.get('signature')
        names = incoming.get('names')
        individual = incoming.get('individual')
        if (not isinstance(sig, str) or not re.fullmatch(key + r':[0-9]{1,3}', sig)
                or not isinstance(individual, str) or not re.fullmatch('[0-9a-f]{24}', individual)
                or not isinstance(names, list) or not 1 <= len(names) <= 1000
                or any(not isinstance(name, str) or len(name) > 20 for name in names)
                or (mon is not None and (sig != signature(mon) or nickname(mon) not in names))):
            raise ValueError('Invalid incoming Elite Four identity')
    elif 'version' in incoming:
        raise ValueError('Unsupported incoming Elite Four record')
    return incoming


def merge(db, incoming):
    """Component maxima preserve wins through retries and return trades."""
    if incoming is None:
        return
    validate(incoming, incoming.get('key'))
    if incoming.get('version') != 2:
        # A committed pre-upgrade exchange can still finish. Retain its old
        # evidence without attaching an ambiguous signature to a new individual.
        legacy = _read(db, LEGACY_KEY) or {'origin': uuid.uuid4().hex, 'victories': [], 'partners': {}}
        entry = legacy['partners'].setdefault(incoming['key'], {'counts': {}, 'ambiguous': False})
        _merge_counts(entry, incoming)
        db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (LEGACY_KEY, json.dumps(legacy)))
        return
    value = read(db)
    matches = [key for key, entry in value['partners'].items()
               if entry['signature'] == incoming['signature'] and set(entry['names']) & set(incoming['names'])]
    if len(matches) > 1:
        raise ValueError('Conflicting incoming Elite Four identities')
    key = matches[0] if matches else incoming['individual']
    entry = value['partners'].setdefault(key, {'signature': incoming['signature'],
                                             'names': [], 'counts': {}, 'ambiguous': False})
    if entry['signature'] != incoming['signature']:
        raise ValueError('Conflicting incoming Elite Four identity')
    entry['names'] = sorted(set(entry['names']) | set(incoming['names']))
    _merge_counts(entry, incoming)
    save(db, value)


def _merge_counts(entry, incoming):
    for origin, count in incoming['counts'].items():
        entry['counts'][origin] = max(entry['counts'].get(origin, 0), count)
    entry['ambiguous'] = entry['ambiguous'] or incoming['ambiguous']
    entry['incomplete'] = entry.get('incomplete', False) or incoming.get('incomplete', False)


def totals(value, entry, legacy):
    counts = dict(entry.get('counts', {}))
    old_key = entry.get('signature', '').split(':')[0]
    old = legacy.get('partners', {}).get(old_key, {})
    candidates = [row for row in value['partners'].values()
                  if row['signature'].split(':')[0] == old_key]
    incomplete = bool(entry.get('incomplete'))
    for origin, count in old.get('counts', {}).items():
        if origin == value['origin'] and value.get('history_complete'):
            continue
        if len(candidates) == 1 and not old.get('ambiguous'):
            counts[origin] = max(counts.get(origin, 0), count)
        elif count > counts.get(origin, 0):
            incomplete = True
    if old.get('ambiguous') and not value.get('history_complete'):
        incomplete = True
    return counts, incomplete


def apply(payload, store):
    with store.lock:
        value = read(store.db)
        legacy = _read(store.db, LEGACY_KEY) or {}
    party = [dict(mon) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', ())]
    keys = resolve(value, party + boxed)
    for mon, key in zip(party + boxed, keys):
        entry = value['partners'].get(key, {})
        counts, incomplete = totals(value, entry, legacy)
        known = bool(key and not entry.get('ambiguous'))
        mon['elite_four_wins'] = sum(counts.values()) if known else None
        mon['elite_four_wins_incomplete'] = incomplete
    return {**payload, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}
