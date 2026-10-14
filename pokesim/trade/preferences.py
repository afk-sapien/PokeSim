"""Persistent per-partner offers, independent of box positions and training."""
from pokesim_core.identity import pokemon_identity
import json
from collections import defaultdict

from .. import individual
from ..shiny import is_shiny
from ..dvs import is_perfect

PREFIX = 'trade_offer:'
MIGRATED = 'trade_settings_v1'
# Marks a row under the older trainer and DV key that only copies the family keys' setting for
# 0.4.x, which reads nothing else. This release ignores such rows; see sync_legacy.
MIRROR = 'mirror'

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
    raise ValueError('Choose Can trade, Prefer to trade or Never trade.')


def name(state):
    return NAMES.get(LEGACY.get(state, state), 'auto')


def migrate(db):
    """Fold the older lock and withdraw states into Never trade (stored as locked), once.

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


def legacy_lock(preferences, mon):
    """Whether a lock still stored under this Pokémon's older trainer and DV key answers to it.

    The upgrade leaves such a key where it is when it fits two species or the collection could not
    be read yet. A lock fails safe, so it keeps every Pokémon it could mean.
    """
    old = signature(mon)
    return bool(old) and (preferences.get(old) or {}).get('state') in ('locked', 'withdrawn')


def is_mirror(value):
    return isinstance(value, dict) and value.get(MIRROR) is True


def _value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return None


def sync_legacy(db, old, force=False):
    """Keep the older trainer and DV row in step with the family keys that start with it.

    0.4.x looks a setting up only under the older key, so a rollback without a backup would drop
    every Never trade lock moved to a family key and could then trade or release a locked Pokémon.
    The older row therefore stays as a copy: Never trade when any family key with that signature
    is locked (a lock fails safe), otherwise the one setting they share, and removed when there is
    none. A row an older release wrote itself is left alone unless ``force`` is set.
    """
    if not old or not individual.is_legacy(old):
        return
    target = PREFIX + old
    current = db.execute('SELECT v FROM kv WHERE k=?', (target,)).fetchone()
    if current and not force and not is_mirror(_value(current[0])):
        return
    start = PREFIX + old + '-'
    values = [value for (raw,) in db.execute('SELECT v FROM kv WHERE substr(k, 1, ?) = ?', (len(start), start))
              if isinstance(value := _value(raw), dict)]
    states = [LEGACY.get(value.get('state'), value.get('state')) for value in values]
    if KEEP in states:
        source = values[states.index(KEEP)]
    elif states and len(set(states)) == 1 and states[0] != AUTO:
        source = values[0]
    else:
        db.execute('DELETE FROM kv WHERE k=?', (target,))
        return
    state = KEEP if KEEP in states else states[0]
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)',
               (target, json.dumps({**source, 'state': state, MIRROR: True})))


def upgrade(db, mons):
    """Move trade settings stored under an older trainer and DV key to the family key, once.

    A setting moves only when exactly one held Pokémon answers to its old key. One that now fits
    two different species stays where it is and applies to neither. The older row stays behind as
    a copy for a rollback to 0.4.x (see sync_legacy). Returns False when the collection is not
    fully readable yet, so the caller tries again later.
    """
    rows = [(k, raw) for k, raw in db.execute("SELECT k,v FROM kv WHERE k LIKE ? AND k NOT LIKE ?",
                                              (PREFIX + '%', PREFIX + '%-%')).fetchall()
            if not is_mirror(_value(raw))]
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
        existing = db.execute('SELECT v FROM kv WHERE k=?', (target,)).fetchone()
        value = _value(raw)
        locked = isinstance(value, dict) and value.get('state') in ('locked', 'withdrawn')
        # A family key already set wins, except over a lock written since, by 0.4.x after a rollback.
        if not existing or locked:
            db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)',
                       (target, json.dumps({**value, 'state': KEEP}) if existing else raw))
        sync_legacy(db, old, force=True)
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
    """Saved settings by key, without the copies kept for 0.4.x."""
    saved = {row[0][len(PREFIX):]: json.loads(row[1])
             for row in db.execute('SELECT k,v FROM kv WHERE k LIKE ?', (PREFIX + '%',))}
    return {key: value for key, value in saved.items() if not is_mirror(value)}


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
        mon['trade_preference'] = KEEP if legacy_lock(preferences, mon) else state if state in NAMES else AUTO
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
        raise ValueError('Shiny Pokémon are never traded automatically, so they cannot be set to Prefer to trade.')
    if state == FIRST and is_perfect(mon):
        raise ValueError('Perfect DV Pokémon are never traded automatically, so they cannot be set to Prefer to trade.')
    store.set_trade_preference(key, {'state': state, 'name': mon['name'],
                                    'nick': mon['nick'], 'dex': mon['dex']})
