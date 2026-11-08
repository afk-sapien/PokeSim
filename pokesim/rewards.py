"""Persistent Championship reward claims, independent of checkpoint rewinds."""
import hashlib
import json
import random
import secrets

KEY = 'league-rewards-v1'
# Mew has its own walking and victory requirement, outside the starter pool.
BASE_POOL = (153, 176, 177)
UNLOCK_POOLS = {
    'eevee': (102,),
    'fossils': (98, 90, 171),
    'dojo': (43, 44),
    'mr_mime': (42,),
    'jynx': (72,),
}
POOL = BASE_POOL


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
    return BASE_POOL


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


def staged_shiny(seed, generation=1):
    """Whether the League gift drawn from ``seed`` has shiny DVs. A shiny gift is always sent."""
    from .shiny import shiny_bytes
    _, first, second = _draw(seed, generation)
    return shiny_bytes(bytes((first, second)))


def staged_mark(seed, generation=1):
    """The reward mark of the League gift drawn from ``seed``, before the ledger counts it delivered."""
    trainer, first, second = _draw(seed, generation)
    return mark(trainer, (first >> 4, first & 15, second >> 4, second & 15))


def wasted(policy, snapshot, slot, seed, generation=1):
    """Whether the gift staged at ``slot`` from ``seed`` only costs a release: a spare by the PC value
    rules (pcvalue.py), or any copy short of the best when the boxes, with it, are below the reserve
    that starts a release visit. Such a gift either goes itself or pushes out the cheapest other copy,
    so sending it turns every League win into a gift and a release.

    The gift is rated as the League reward it is. Until the ledger counts it, its mark is unknown, and
    an unmarked gift rates as a Pokémon traded in, the best copy of its species. The mark is passed to
    the rating, so the PC tab and other readers never see it.
    """
    from .planning.ledger import box_wanted
    marks = frozenset({staged_mark(seed, generation)})
    if hasattr(policy, 'pc_rated'):
        rated = policy.pc_rated(snapshot, marks=marks)
    elif generation == 2:
        from .gen2.release import release_rated
        rated = release_rated(policy, snapshot, marks=marks)
    else:
        rated = ()
    row = next((row for row in rated if row.entry.slot == slot), None)
    if row is None:
        return False
    # Both generations hold 20 Pokémon per box.
    short = box_wanted(sum(20 - count for count in snapshot.box_counts), False) > 0
    return row.status == 'spare' or row.status != 'floor' and short


def skip(store, ordinal):
    """Settle League reward ``ordinal`` without a gift, as rewards earned while they were off are."""
    with store.lock, store.db:
        value = ledger(store.db)
        if value['delivered'] + 1 != ordinal or value['earned'] < ordinal:
            raise ValueError('The League gift claim changed')
        value['delivered'] = ordinal
        value['skipped'] = value.get('skipped', 0) + 1
        save(store.db, value)


_MARKS = {}


def _draw(seed, generation):
    """The trainer ID and DV bytes a reward gift drew from its seed."""
    if generation == 2:
        # Core's Gen II box_gift draws the trainer ID, then the two DV bytes, from Random(seed).
        rng = random.Random(seed)
        trainer = rng.randrange(65536)
        return trainer, rng.randrange(256), rng.randrange(256)
    # trade/event.py gift_slot takes the DV bytes and then the trainer ID from the seed's digest.
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[2:4], 'big'), digest[0], digest[1]


def mark(trainer_id, dvs):
    """A stored copy's reward mark: its trainer ID and Attack, Defense, Speed and Special DVs."""
    return trainer_id, tuple(dvs[-4:])


def marks(value, generation=1):
    """The marks of every League reward already delivered, from the ledger alone.

    This also finds rewards delivered before releases knew about them. A random trainer ID and DV pair
    matches another Pokémon about once in four billion.
    """
    seed, delivered = (value or {}).get('seed'), (value or {}).get('delivered', 0)
    if not seed or not delivered:
        return frozenset()
    # One entry per adventure seed, since several adventures can share a process.
    if _MARKS.get((seed, generation), (None,))[0] != delivered:
        found = set()
        for ordinal in range(1, delivered + 1):
            trainer, first, second = _draw(f'{seed}:{ordinal}', generation)
            found.add(mark(trainer, (first >> 4, first & 15, second >> 4, second & 15)))
        _MARKS[seed, generation] = delivered, frozenset(found)
    return _MARKS[seed, generation][1]


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
