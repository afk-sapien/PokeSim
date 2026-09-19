"""Persistent Championship reward claims, independent of checkpoint rewinds."""
import json
import random
import secrets

KEY = 'league-rewards-v1'
# Mew belongs exclusively to the one-time event, never the repeatable pool.
BASE_POOL = (153, 176, 177)
UNLOCK_POOLS = {
    'eevee': (102,),
    'fossils': (98, 90, 171),
    'dojo': (43, 44),
    'mr_mime': (42,),
    'jynx': (72,),
}
POOL = BASE_POOL + tuple(species for group in UNLOCK_POOLS.values() for species in group)


def progress_unlocks(snapshot):
    """Normal acquisition opens repeat gifts for that family in this adventure."""
    from .strategy_data import event_set
    owned = snapshot.owned
    unlocked = set()
    if owned & {133, 134, 135, 136}:
        unlocked.add('eevee')
    if owned & {138, 139, 140, 141, 142}:
        unlocked.add('fossils')
    if any(event_set(snapshot.event_flags, flag) for flag in (
            'EVENT_BEAT_KARATE_MASTER', 'EVENT_GOT_HITMONLEE', 'EVENT_GOT_HITMONCHAN')):
        unlocked.add('dojo')
    for dex, group in ((122, 'mr_mime'), (124, 'jynx')):
        if dex in owned:
            unlocked.add(group)
    return unlocked


def observe_progress(store, snapshot):
    """Keep unlocks through trades and restores without creating reward claims."""
    if not snapshot.valid or not snapshot.started:
        return
    observed = progress_unlocks(snapshot)
    with store.lock, store.db:
        if 151 in snapshot.owned:
            # Remember acquisition from older rewards or trades across rewinds.
            row = store.db.execute("SELECT v FROM kv WHERE k='pokesim-mew-v1'").fetchone()
            if not row or not json.loads(row[0]):
                store.db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)',
                                 ('pokesim-mew-v1', json.dumps({'source': 'observed_ownership'})))
        value = ledger(store.db)
        unlocked = set(value.get('unlocks', ())) | observed
        if unlocked != set(value.get('unlocks', ())):
            value['unlocks'] = sorted(unlocked)
            save(store.db, value)


def eligible_pool(value):
    unlocked = set(value.get('unlocks', ()))
    return BASE_POOL + tuple(species for group, pool in UNLOCK_POOLS.items()
                             if group in unlocked for species in pool)


def ledger(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    return (json.loads(row[0]) if row else None) or {'earned': 0, 'delivered': 0}


def save(db, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (KEY, json.dumps(value)))


def championship_count(value):
    return value.get('observed', value['earned'])


def _upgrade(value):
    if value.get('version') != 2:
        # Old claims included victories earned with rewards disabled.
        value = {**value, 'version': 2, 'observed': value['earned'],
                 'skipped': max(0, value['earned'] - value['delivered']),
                 'earned': value['delivered']}
    return value


def initialize(store, count):
    """Baseline existing victories without awarding retrospective League gifts."""
    with store.lock, store.db:
        value = _upgrade(ledger(store.db))
        value['observed'] = max(value['observed'], count)
        save(store.db, value)


def earn(store, count, *, enabled=True):
    with store.lock, store.db:
        value = _upgrade(ledger(store.db))
        value.setdefault('seed', secrets.token_hex(16))
        if enabled:
            value['earned'] += max(0, count - value['observed'])
        value['observed'] = max(value['observed'], count)
        save(store.db, value)


def status(store):
    with store.lock:
        value = ledger(store.db)
    return {key: value[key] for key in ('earned', 'delivered')} | {
        'pending': max(0, value['earned'] - value['delivered']),
        'wins': championship_count(value), 'unlocks': sorted(value.get('unlocks', ()))}


def selection(value):
    ordinal = value['delivered'] + 1
    seed = f"{value['seed']}:{ordinal}"
    return ordinal, random.Random(seed).choice(eligible_pool(value)), seed


def mew_enabled(policy):
    return bool(policy.get('league_rewards', False) or policy.get('mew_event', False))
