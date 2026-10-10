"""Persistent per-partner offers, independent of box positions and training."""
from pokesim_core.identity import pokemon_identity
import json
from collections import Counter

from ..shiny import is_shiny
from ..dvs import is_perfect

PREFIX = 'trade_offer:'
MIGRATED = 'trade_settings_v1'

# One trade setting per Pokémon. The stored strings predate the three named
# settings and stay the same so an older release can still read them.
AUTO = 'auto'
FIRST = 'offered'
KEEP = 'locked'
SETTINGS = {'auto': AUTO, 'first': FIRST, 'keep': KEEP}
NAMES = {AUTO: 'auto', FIRST: 'first', KEEP: 'keep'}
# Older names a client may still send.
LEGACY = {'offered': FIRST, 'locked': KEEP, 'withdrawn': KEEP, 'unlocked': AUTO}


def stored(setting):
    """Map an API setting name (or an older state name) to the stored state."""
    if setting in SETTINGS:
        return SETTINGS[setting]
    if setting in LEGACY:
        return LEGACY[setting]
    raise ValueError('Choose Auto decides, Trade first or Keep.')


def name(state):
    return NAMES.get(LEGACY.get(state, state), 'auto')


def migrate(db):
    """Fold the older lock and withdraw states into Keep, once.

    Idempotent: a marker row records the run, and a second run changes nothing
    even without the marker because only 'withdrawn' rows are rewritten.
    """
    if db.execute('SELECT 1 FROM kv WHERE k=?', (MIGRATED,)).fetchone():
        return 0
    changed = 0
    for key, raw in db.execute('SELECT k,v FROM kv WHERE k LIKE ?', (PREFIX + '%',)).fetchall():
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(value, dict) or value.get('state') not in ('withdrawn', 'unlocked'):
            continue
        value['state'] = KEEP if value['state'] == 'withdrawn' else AUTO
        db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), key))
        changed += 1
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (MIGRATED, json.dumps(True)))
    return changed


def identity(mon):
    return pokemon_identity(mon.get('trainer_id'), mon.get('dvs', ()))


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
        raw = preferences.get(key, {}).get('state', AUTO)
        state = LEGACY.get(raw, raw)
        mon['trade_preference'] = state if state in NAMES else AUTO
        mon['trade_setting'] = name(mon['trade_preference'])
        mon['trade_locked'] = mon['trade_preference'] == KEEP
    return {**payload, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}


def update(store, payload, key, state):
    state = stored(state)
    rows = payload.get('party', []) + (payload.get('storage') or {}).get('pokemon', [])
    matches = [mon for mon in rows if identity(mon) == key]
    if len(matches) != 1:
        raise ValueError('This Pokémon left the collection or cannot be identified uniquely. Refresh and try again.')
    mon = matches[0]
    if state == FIRST and is_shiny(mon):
        raise ValueError('Shiny Pokémon are never traded automatically, so they cannot be set to Trade first.')
    if state == FIRST and is_perfect(mon):
        raise ValueError('Perfect DV Pokémon are never traded automatically, so they cannot be set to Trade first.')
    store.set_trade_preference(key, {'state': state, 'name': mon['name'],
                                    'nick': mon['nick'], 'dex': mon['dex']})
