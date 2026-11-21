"""Persistent per-partner offers, independent of box positions and training."""
from pokecore.identity import pokemon_identity
import hashlib
import json
from collections import defaultdict

from pokecore import identity as individual
from ..shiny import is_shiny
from ..state import kv
from pokecore.dvs import is_perfect

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

# Copies that share a trainer, DVs and evolution family ("twins") are told apart by nickname: the
# trade key adds TWIN and the copy's tag to the family key. Neither game stores anything else that
# stays the same while a Pokémon is played, so nothing is ever written to the game to mark one.
# Twins with the same nickname whose stats differ add a third part, their stamp (see stamp). A
# boxed copy keeps its stats, and a trade follows a picked copy by its party slot once it is held.
TWIN = '~'
# The tag of a copy that carries its species' own name, or is an Egg. The game renames such a Pokémon
# when it evolves or hatches, so the tag must not follow that name.
DEFAULT = 'd'
# Marks the family key row that stands in for the twins' own rows for 0.7.4, which reads no other key:
# Never trade when any twin is kept, so a rollback keeps every copy. This release ignores such rows.
TWINS = 'twins'
# Twins that agree on all of these are interchangeable: a trade may send either one.
FINGERPRINT = ('dex', 'species', 'nick', 'level', 'experience', 'stat_exp', 'moves', 'max_pp', 'held_item',
               'friendship', 'caught', 'pokerus', 'egg')


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
    if kv.exists(db, MIGRATED):
        return 0
    changed = 0
    for key, raw in kv.starting(db, PREFIX):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(value, dict) or value.get('state') not in ('withdrawn', 'unlocked'):
            continue
        value['state'] = KEEP if value['state'] == 'withdrawn' else AUTO
        kv.update(db, key, value)
        changed += 1
    kv.put(db, MIGRATED, True)
    return changed


def identity(mon):
    """The trade key: trainer ID, DVs and evolution family (see pokecore.identity)."""
    return individual.family_key(mon.get('trainer_id'), mon.get('dvs', ()), individual.dex_of(mon))


def signature(mon):
    """The trainer and DV signature alone, as League records and older trade keys store it."""
    return pokemon_identity(mon.get('trainer_id'), mon.get('dvs', ()))


def _letters(text):
    return ''.join(char for char in str(text or '').upper() if char.isascii() and char.isalnum())


def _species_name(mon):
    """The species name a record shows. Red, Blue and Yellow cartridge records carry only the species index."""
    if mon.get('name'):
        return mon['name']
    from ..ram import SPECIES_NAMES
    species = mon.get('species')
    if not isinstance(species, int):
        species = individual.GEN1_INDEX.get(mon.get('dex'))
    return SPECIES_NAMES.get(species, '')


def tag(mon):
    """Which of several twins a Pokémon or a saved setting is: its nickname, hashed, or DEFAULT."""
    nick = _letters(mon.get('nick'))
    if not nick or mon.get('egg') or nick == 'EGG' or nick == _letters(_species_name(mon)):
        return DEFAULT
    return 'n' + hashlib.sha256(nick.encode()).hexdigest()[:8]


def base(key):
    """The family key a trade key starts with. A key without a twin tag is its own family key."""
    return key.split(TWIN, 1)[0] if isinstance(key, str) else key


def tagged(key):
    """A trade key without its stamp: the family key and nickname tag of the copies it names."""
    return TWIN.join(key.split(TWIN)[:2]) if isinstance(key, str) else key


def stamped(key):
    """Whether a trade key names a copy by its stats as well as its nickname."""
    return isinstance(key, str) and key.count(TWIN) == 2


def fingerprint(mon):
    return tuple(json.dumps(mon.get(field), sort_keys=True, default=str) for field in FINGERPRINT)


def stamp(mon):
    """The stats part of a key: 'f' and 8 hex digits of the SHA-256 of the fingerprint, which every
    process and release gives alike."""
    return 'f' + hashlib.sha256(json.dumps(fingerprint(mon)).encode()).hexdigest()[:8]


def answers(mon, key):
    """Whether a held Pokémon is one the key names. A twin key names the copies with its nickname tag,
    and a stamped key only those whose stats give its stamp too."""
    if isinstance(key, str) and TWIN in key:
        root, mark, *stats = key.split(TWIN)
        return identity(mon) == root and tag(mon) == mark and (not stats or stats == [stamp(mon)])
    return individual.same(identity(mon), key)


def matching(rows, key):
    """Rows answering to a stored key. A key from an older release matches on trainer and DVs."""
    return [mon for mon in rows if answers(mon, key)]


def find(rows, wanted, field='trade_key'):
    """pokecore.identity.find, where interchangeable twins share a key and the first of them answers."""
    exact = [row for row in rows if row.get(field) and row.get(field) == wanted]
    if (len(exact) > 1 and isinstance(wanted, str) and TWIN in wanted
            and not any(row.get('trade_ambiguous') or row.get('blocked') for row in exact)):
        return exact[0]
    return individual.find(rows, wanted, field)


def assign(rows):
    """Set each row's trade_key and trade_ambiguous in place, as apply lists them.

    A Pokémon alone in its family group keeps the family key. Twins get a twin key each. Twins that
    share a nickname share the key too when they are interchangeable. When their stats differ, each
    adds its stamp, and copies are ambiguous only if two different sets of stats give one stamp.
    """
    groups = defaultdict(list)
    for mon in rows:
        groups[identity(mon)].append(mon)
    for root, members in groups.items():
        for mon in members:
            mon['trade_key'] = f'{root}{TWIN}{tag(mon)}' if root and len(members) > 1 else root
    buckets = defaultdict(list)
    for mon in rows:
        buckets[mon['trade_key']].append(mon)
    for key, members in list(buckets.items()):
        if key and len(members) > 1 and len({fingerprint(mon) for mon in members}) > 1:
            del buckets[key]
            for mon in members:
                mon['trade_key'] = f'{key}{TWIN}{stamp(mon)}'
                buckets[mon['trade_key']].append(mon)
    for key, members in buckets.items():
        ambiguous = bool(key) and len(members) > 1 and len({fingerprint(mon) for mon in members}) > 1
        for mon in members:
            mon['trade_ambiguous'] = ambiguous
            if ambiguous:
                mon['trade_ambiguous_reason'] = ambiguity(mon, members)
            else:
                mon.pop('trade_ambiguous_reason', None)
    return groups


def interchangeable(rows, key):
    """The rows a trade key names when they are one Pokémon or interchangeable twins, else [].

    ``rows`` carry the keys assign gives. A twin key may name several copies. Any other key must
    name exactly one.
    """
    found = [mon for mon in rows if answers(mon, key)]
    if not found or any(mon.get('trade_ambiguous') for mon in found):
        return []
    if len(found) > 1 and not (isinstance(key, str) and TWIN in key and all(mon.get('trade_key') == key for mon in found)):
        return []
    return found


def sendable(rows, slot, key):
    """Whether party row ``slot`` may go for the trade key: it answers to the key, and the key names it
    alone or interchangeable twins. ``rows`` hold the party first, then the boxed Pokémon.

    The preparation followed a copy picked by a stamped key to its party slot, and its stats change as
    it is played, so the slot need only hold an unambiguous copy with that family key and nickname.
    """
    listed = [dict(row) for row in rows]
    assign(listed)
    if not 0 <= slot < len(listed) or not answers(listed[slot], tagged(key)):
        return False
    return not listed[slot]['trade_ambiguous'] if stamped(key) else bool(interchangeable(listed, key))


def answering(key, roots, listed):
    """The indices of the held Pokémon a release request's key names.

    ``roots`` are their family keys, party first, and ``listed(index)`` gives one as the PC page lists
    it, which a twin key's nickname tag and stamp are read from. Only a twin family's copies are listed.
    """
    if not isinstance(key, str):
        return []
    root = base(key)
    return [index for index, mine in enumerate(roots)
            if mine == root and (TWIN not in key or answers(listed(index), key))]


def picked(requests, roots, listed):
    """{index: key} for each release request whose key names exactly one held Pokémon (answering).

    A key that several copies answer names none: a family key saved before twins were told apart, or
    the key of twins alike in every stat. Such a request takes no Pokémon and is dropped, so it never
    widens to the other copies.
    """
    named = {}
    for key in requests:
        found = answering(key, roots, listed)
        if len(found) == 1:
            named[found[0]] = key
    return named


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
    current = kv.text(db, target)
    if current is not None and not force and not is_mirror(_value(current)):
        return
    values = [value for _, raw in kv.starting(db, PREFIX + old + '-') if isinstance(value := _value(raw), dict)]
    states = [LEGACY.get(value.get('state'), value.get('state')) for value in values]
    if KEEP in states:
        source = values[states.index(KEEP)]
    elif states and len(set(states)) == 1 and states[0] != AUTO:
        source = values[0]
    else:
        kv.delete(db, target)
        return
    state = KEEP if KEEP in states else states[0]
    kv.put(db, target, {**source, 'state': state, MIRROR: True})


def upgrade(db, mons):
    """Move trade settings stored under an older trainer and DV key to the family key, once.

    A setting moves only when exactly one held Pokémon answers to its old key. One that now fits
    two different species stays where it is and applies to neither. The older row stays behind as
    a copy for a rollback to 0.4.x (see sync_legacy). Returns False when the collection is not
    fully readable yet, so the caller tries again later.
    """
    # Family keys hold a dash after the trainer and DV signature. These rows are under the older key alone.
    rows = [(k, raw) for k, raw in kv.starting(db, PREFIX)
            if '-' not in k[len(PREFIX):] and not is_mirror(_value(raw))]
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
        existing = kv.exists(db, target)
        value = _value(raw)
        locked = isinstance(value, dict) and value.get('state') in ('locked', 'withdrawn')
        # A family key already set wins, except over a lock written since, by 0.4.x after a rollback.
        if existing and locked:
            kv.put(db, target, {**value, 'state': KEEP})
        elif not existing:
            kv.put_text(db, target, raw)
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
    alike = 'no nickname' if tag(mon) == DEFAULT else 'the same nickname'
    if all(other == name for other in others):
        return f"Another {name} from the same trainer has the same DVs and {alike}, so this one can't be picked out safely"
    other = next(other for other in others if other != name)
    return (f"{other} is from the same trainer, has the same DVs, the same evolution family and {alike}, "
            "so this one can't be picked out safely")


def read(db):
    """Saved settings by key, without the copies kept for 0.4.x."""
    return parse(kv.starting(db, PREFIX))


def parse(rows):
    """read's settings from the (key, JSON text) rows kv.starting returns for PREFIX."""
    saved = {key[len(PREFIX):]: json.loads(raw) for key, raw in rows}
    return {key: value for key, value in saved.items()
            if not is_mirror(value) and not (isinstance(value, dict) and value.get(TWINS) is True)}


def _state(value):
    raw = (value or {}).get('state', AUTO)
    state = LEGACY.get(raw, raw)
    return state if state in NAMES else AUTO


def _saved_tag(value):
    """The tag of the copy a saved family key row names, or None when it saved no nickname."""
    return tag(value) if isinstance(value, dict) and value.get('nick') else None


def _twin_rows(preferences):
    """The twins' own rows: {family key: {tag: row}}."""
    rows = defaultdict(dict)
    for key, value in preferences.items():
        if isinstance(key, str) and TWIN in key:
            root, mark = key.split(TWIN, 1)
            rows[root][mark] = value
    return rows


def _group_states(members, own_rows, saved):
    """The saved state of each copy in one family group, in order.

    A twin's own row wins. A family key row counts for a copy alone in its group, as in 0.7.4. Among
    twins it names the copy it saved the nickname of, and every copy when it saved none. Never trade
    on a twin that is not held now, being in the Day-Care or renamed, keeps every copy without a row
    of its own, since it could be any of them. A Never trade under the family key that 0.7.4 wrote
    after a rollback keeps the copies it names over their own rows.
    """
    marks = [tag(mon) for mon in members]
    held = set(marks)
    named = _saved_tag(saved)
    alone = len(members) == 1
    lost_keep = (any(_state(value) == KEEP for mark, value in own_rows.items() if mark not in held)
                 or (not alone and named is not None and named not in held and _state(saved) == KEEP))
    states = []
    for mon, mark in zip(members, marks):
        names_this = saved is not None and (alone or named == mark)
        if mark in own_rows:
            state = _state(own_rows[mark])
            if names_this and _state(saved) == KEEP:
                state = KEEP
        elif names_this:
            state = KEEP if lost_keep else _state(saved)
        else:
            loose_keep = saved is not None and named is None and _state(saved) == KEEP
            state = KEEP if lost_keep or loose_keep else AUTO
        if mon.get('trade_ambiguous') and (lost_keep or (saved is not None and _state(saved) == KEEP)):
            state = KEEP
        states.append(state)
    return states


def apply(payload, preferences):
    """Copy a snapshot and attach preferences only to identifiable partners.

    Neither generation has a unique individual ID. Pokémon that share a trainer, DVs and evolution
    family are told apart by nickname (assign). Twins that share a nickname too suspend offers
    instead of letting a selection drift to another partner, unless they are interchangeable.
    """
    party = [dict(mon) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon) for mon in (storage or {}).get('pokemon', ())]
    groups = assign(party + boxed)
    twin_rows = _twin_rows(preferences)
    for root, members in groups.items():
        states = (_group_states(members, twin_rows.get(root, {}), preferences.get(root)) if root
                  else [AUTO] * len(members))
        for mon, state in zip(members, states):
            mon['trade_preference'] = KEEP if legacy_lock(preferences, mon) else state
            mon['trade_setting'] = name(mon['trade_preference'])
            mon['trade_locked'] = mon['trade_preference'] == KEEP
    return {**payload, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}


RANK = {AUTO: 0, FIRST: 1, KEEP: 2}


def merged(preferences):
    """Settings for code that looks a Pokémon up by its family key alone, as policies do.

    A twin's own setting counts for every copy: Never trade on one keeps them all from a release or a
    training swap, then Prefer to trade. The twin rows stay, for code that reads them by twin key.
    """
    out = dict(preferences)
    for root, rows in _twin_rows(preferences).items():
        strongest = max(rows.values(), key=lambda value: RANK[_state(value)])
        if RANK[_state(strongest)] > RANK[_state(out.get(root))]:
            out[root] = {**strongest, 'state': _state(strongest)}
    return out


def changes(preferences, rows, key, value):
    """The rows update writes, {key: row or None to remove}, for a new setting on one copy.

    A copy alone in its family group keeps its setting under the family key, as 0.7.4 does. Once twins
    are held, each keeps its own row under its twin key. A family key row saved by 0.7.4 then moves to
    the copy whose nickname it saved, and one that saved none keeps a Never trade on every other copy.
    The family key row becomes the TWINS stand-in for 0.7.4.
    """
    root = base(key)
    group = [mon for mon in rows if identity(mon) == root]
    own_rows = _twin_rows(preferences).get(root, {})
    # A stamped copy's setting is its nickname group's, since its stats move as it is played.
    mark = key.split(TWIN)[1] if TWIN in key else tag(group[0])
    if len(group) <= 1 and not any(other != mark for other in own_rows):
        return {root: value, **({f'{root}{TWIN}{mark}': None} if mark in own_rows else {})}
    current = dict(own_rows)
    saved = preferences.get(root)
    named = _saved_tag(saved)
    if saved is not None and named is not None:
        if named not in current:
            current[named] = saved
        elif _state(saved) == KEEP:
            # A Never trade 0.7.4 wrote after a rollback wins, as upgrade decides.
            current[named] = {**current[named], 'state': KEEP}
    elif saved is not None and _state(saved) == KEEP:
        for mon in group:
            current.setdefault(tag(mon), {'state': KEEP, 'name': mon.get('name'), 'nick': mon.get('nick'),
                                          'dex': mon.get('dex')})
    current[mark] = value
    out = {f'{root}{TWIN}{other}': row for other, row in current.items() if own_rows.get(other) != row}
    kept = any(_state(row) == KEEP for row in current.values())
    out[root] = ({'state': KEEP, TWINS: True, 'name': value.get('name'), 'nick': '', 'dex': value.get('dex')}
                 if kept else None)
    return out


def update(store, payload, key, state):
    state = stored(state)
    rows = [dict(mon) for mon in payload.get('party', []) + (payload.get('storage') or {}).get('pokemon', [])]
    assign(rows)
    matches = [mon for mon in rows if mon['trade_key'] == key]
    if not matches or matches[0]['trade_ambiguous']:
        raise ValueError('This Pokémon left the collection or cannot be identified uniquely. Refresh and try again.')
    mon = matches[0]
    if state == FIRST and is_shiny(mon):
        raise ValueError('Shiny Pokémon are never traded automatically, so they cannot be set to Prefer to trade.')
    if state == FIRST and is_perfect(mon):
        raise ValueError('Perfect DV Pokémon are never traded automatically, so they cannot be set to Prefer to trade.')
    value = {'state': state, 'name': mon['name'], 'nick': mon['nick'], 'dex': mon['dex']}
    store.set_trade_preferences(changes(store.trade_preferences(), rows, key, value))
