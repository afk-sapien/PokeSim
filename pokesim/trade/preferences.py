"""Persistent per-partner offers, independent of box positions and training."""
from pokesim_core.identity import pokemon_identity
import json
from collections import defaultdict

from .. import individual
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
    """The trade key: trainer ID, DVs and evolution family (see pokesim.individual)."""
    return individual.key(mon.get('trainer_id'), mon.get('dvs', ()), individual.dex_of(mon))


def signature(mon):
    """The trainer and DV signature alone, as League records and older trade keys store it."""
    return pokemon_identity(mon.get('trainer_id'), mon.get('dvs', ()))


def matching(rows, key):
    """Rows answering to a stored key. A key from an older release matches on trainer and DVs."""
    return [mon for mon in rows if individual.same(identity(mon), key)]


def upgrade(db, mons):
    """Move trade settings stored under an older trainer and DV key to the family key, once.

    A setting moves only when exactly one held Pokémon answers to its old key. One that now fits
    two different species stays where it is and applies to neither. Returns False when the
    collection is not fully readable yet, so the caller tries again later.
    """
    rows = db.execute("SELECT k,v FROM kv WHERE k LIKE ? AND k NOT LIKE ?", (PREFIX + '%', PREFIX + '%-%')).fetchall()
    if not rows:
        return True
    if not mons or any(signature(mon) is None for mon in mons):
        return False
    keys = defaultdict(set)
    for mon in mons:
        # A glitch species has no family and adds None, so its old key stays unresolved.
        keys[signature(mon)].add(identity(mon))
    for stored_key, raw in rows:
        old = stored_key[len(PREFIX):]
        new = keys.get(old, set())
        if len(new) != 1 or None in new:
            continue
        target = PREFIX + next(iter(new))
        if not db.execute('SELECT 1 FROM kv WHERE k=?', (target,)).fetchone():
            db.execute('INSERT INTO kv(k,v) VALUES (?,?)', (target, raw))
        db.execute('DELETE FROM kv WHERE k=?', (stored_key,))
    return True


UNREADABLE = "This Pokémon's trainer and stats could not be read, so it cannot be picked out safely"


def blocked(mon):
    """Why a listed Pokémon cannot be picked for a trade by its key, or '' when it can."""
    if not mon.get('trade_key'):
        return UNREADABLE
    if mon.get('trade_ambiguous'):
        return mon.get('trade_ambiguous_reason') or ambiguity(mon, [mon, dict(mon)])
    return ''


def ambiguity(mon, twins):
    """Why one of several Pokémon with the same key cannot be picked out, in plain words."""
    name = mon.get('name') or 'Pokémon'
    others = [other.get('name') or 'Pokémon' for other in twins if other is not mon]
    if all(other == name for other in others):
        return f"Another {name} from the same trainer has identical stats, so the game can't tell them apart"
    other = next(other for other in others if other != name)
    return (f"{other} is from the same trainer, has identical stats and the same evolution family, "
            "so the game can't tell them apart")


def read(db):
    return {row[0][len(PREFIX):]: json.loads(row[1])
            for row in db.execute('SELECT k,v FROM kv WHERE k LIKE ?', (PREFIX + '%',))}


def apply(payload, preferences):
    """Copy a snapshot and attach preferences only to identifiable partners.

    Neither generation has a unique individual ID. Pokémon that share a trainer,
    DVs and evolution family suspend offers instead of letting a selection drift
    to another partner.
    """
    party = [dict(mon) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', ())]
    groups = defaultdict(list)
    for mon in party + boxed:
        mon['trade_key'] = key = identity(mon)
        groups[key].append(mon)
    for mon in party + boxed:
        key = mon['trade_key']
        mon['trade_ambiguous'] = bool(key and len(groups[key]) > 1)
        if mon['trade_ambiguous']:
            mon['trade_ambiguous_reason'] = ambiguity(mon, groups[key])
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
