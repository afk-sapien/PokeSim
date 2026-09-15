"""Persistent per-partner offers, independent of box positions and training."""
import hashlib
import json
from collections import Counter

PREFIX = 'trade_offer:'


def identity(mon):
    trainer = mon.get('trainer_id')
    dvs = mon.get('dvs', ())
    if trainer is None or len(dvs) != 5:
        return None
    return hashlib.sha256(json.dumps([trainer, list(dvs)]).encode()).hexdigest()[:24]


def read(db):
    return {row[0][len(PREFIX):]: json.loads(row[1])
            for row in db.execute('SELECT k,v FROM kv WHERE k LIKE ?', (PREFIX + '%',))}


def apply(payload, preferences):
    """Copy a snapshot and attach preferences only to identifiable partners.

    Generation I has no unique individual ID. Identical trainer/DV signatures
    suspend offers instead of letting a selection drift to another partner.
    """
    party = [dict(mon) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', ())]
    counts = Counter(identity(mon) for mon in party + boxed)
    for mon in party + boxed:
        key = identity(mon)
        mon['trade_key'] = key
        mon['trade_ambiguous'] = bool(key and counts[key] > 1)
        mon['trade_preference'] = preferences.get(key, {}).get('state', 'auto')
        mon['trade_locked'] = mon['trade_preference'] == 'locked'
    return {**payload, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}


def update(store, payload, key, state):
    rows = payload.get('party', []) + (payload.get('storage') or {}).get('pokemon', [])
    matches = [mon for mon in rows if identity(mon) == key]
    if len(matches) != 1:
        raise ValueError('This Pokémon left the collection or cannot be identified uniquely. Refresh and try again.')
    mon = matches[0]
    store.set_trade_preference(key, {'state': state, 'name': mon['name'],
                                    'nick': mon['nick'], 'dex': mon['dex']})
