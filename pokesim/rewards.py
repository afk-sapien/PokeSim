"""Persistent Championship reward claims, independent of checkpoint rewinds.

Each League win earns one claim in the claims ledger (pokesim/state/claims.py), keyed by the gift's
seed. The kv value keeps only what the source needs to earn them: the adventure's reward seed, the
wins already counted and the unlocked families. Both generations deliver through the same steps
here: the oldest open claim is drawn, a copy the cartridge already holds settles it with no write,
the worth oracle may decline it, and the commit marks it delivered. A reload to a save from before
a delivery sends that claim back to open.
"""
from dataclasses import asdict
import functools
import hashlib
import random
import secrets

from .state import claims, kv

KEY = 'league-rewards-v1'
SOURCE = 'league'
# The kv value's shape once the claims are rows.
VERSION = 3
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
# Gen II gifts one of the three Johto starters.
JOHTO_POOL = (152, 155, 158)


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
    with store.transaction() as db:
        if 151 in snapshot.owned:
            # Remember acquisition from older rewards or trades across rewinds.
            if not kv.get(db, 'pokesim-mew-v1'):
                kv.put(db, 'pokesim-mew-v1', {'source': 'observed_ownership'})
        value = ledger(db)
        unlocked = set(value.get('unlocks', ())) | observed
        if unlocked != set(value.get('unlocks', ())):
            value['unlocks'] = sorted(unlocked)
            save(db, value)


def eligible_pool(value):
    return BASE_POOL


def ledger(db):
    """The kv value: the reward ``seed``, the ``observed`` wins and the ``unlocks``."""
    return kv.get(db, KEY) or {'observed': 0, 'version': VERSION}


def save(db, value):
    kv.put(db, KEY, value)


def championship_count(value):
    return value.get('observed', 0)


def adopt(db):
    """Move a League ledger from before claims rows into rows, and return the kv value left.

    The rewards it settled become delivered claims with no frame, which never reopen. It did not
    keep which of them it skipped, and its marks counted those as delivered too. The rest it earned
    become open claims. A ledger from before version 2 first drops the victories it counted while
    rewards were off, as that version did. Schema version 2 runs this once, and the writers run it
    again for a ledger put back in the old shape. Returns None when there is no ledger.
    """
    value = kv.get(db, KEY)
    if not value or value.get('version') == VERSION:
        return value
    if value.get('version') != 2:
        value = {**value, 'observed': value.get('earned', 0), 'earned': value.get('delivered', 0)}
    if seed := value.get('seed'):
        for ordinal in range(1, value.get('earned', 0) + 1):
            key = f'{seed}:{ordinal}'
            if claims.get(db, SOURCE, key) is None:
                state = claims.DELIVERED if ordinal <= value.get('delivered', 0) else claims.OPEN
                claims.put(db, SOURCE, key, state, seed=key)
    value = {name: value[name] for name in ('seed', 'observed', 'unlocks') if name in value}
    value = {'observed': 0, **value, 'version': VERSION}
    save(db, value)
    return value


def initialize(store, count):
    """Baseline existing victories without awarding retrospective League gifts."""
    with store.transaction() as db:
        value = adopt(db) or ledger(db)
        value['observed'] = max(value['observed'], count)
        save(db, value)


def earn(store, count, *, enabled=True):
    """Open one claim for each League win past the ones already counted, while gifts are on."""
    from .progress_events import frame
    with store.transaction() as db:
        value = adopt(db) or ledger(db)
        value.setdefault('seed', secrets.token_hex(16))
        if enabled:
            open_claims(db, value['seed'], max(0, count - value['observed']), frame=frame(store))
        value['observed'] = max(value['observed'], count)
        save(db, value)


def open_claims(db, seed, count, *, frame=None):
    """Open ``count`` League claims after the ones already made, each keyed by its gift's seed."""
    made = sum(claims.counts(db, SOURCE).values())
    for ordinal in range(made + 1, made + 1 + count):
        key = f'{seed}:{ordinal}'
        claims.put(db, SOURCE, key, claims.OPEN, frame=frame, seed=key)


def ordinal(seed):
    """The League reward number a claim's seed ends with."""
    return int(seed.rsplit(':', 1)[1])


def next_claim(db, generation=1):
    """The oldest open League claim as (ordinal, species, seed), or None."""
    row = next(iter(claims.rows(db, SOURCE, claims.OPEN)), None)
    if row is None:
        return None
    seed = row['key']
    return ordinal(seed), draw(seed, generation, ledger(db)), seed


def draw(seed, generation=1, value=None):
    """The species the League claim ``seed`` gifts, from the pool its ledger ``value`` opens."""
    pool = JOHTO_POOL if generation == 2 else eligible_pool(value or {})
    return random.Random(seed).choice(pool)


def settle(db, seed, state, *, frame=None, species=None, reward_id=None, reasons=''):
    """Mark the open claim ``seed`` delivered or declined inside the caller's transaction."""
    row = claims.get(db, SOURCE, seed)
    if row is None or row['state'] != claims.OPEN:
        raise ValueError('The League gift claim changed')
    claims.put(db, SOURCE, seed, state, frame=frame, species=species, seed=seed,
               reward_id=reward_id, reasons=reasons)


def decline(store, seed, reasons):
    """Settle claim ``seed`` without a gift, for the worth oracle's ``reasons``."""
    from .progress_events import frame
    with store.transaction() as db:
        settle(db, seed, claims.DECLINED, frame=frame(store), reasons=reasons)


def found_held(store, seed, species):
    """Settle claim ``seed`` as delivered with no write, since the cartridge already holds its gift."""
    from .progress_events import frame
    with store.transaction() as db:
        settle(db, seed, claims.DELIVERED, frame=frame(store), species=species,
               reasons='Already held')


def held(snapshot, seed, generation=1):
    """Whether the party or the boxes already hold the League gift drawn from ``seed``, found by its
    mark as the release rules find it. A claim reopened by a reload can find its gift still there,
    and then it is settled with no second copy."""
    wanted = staged_mark(seed, generation)
    if generation == 2:
        found = ((mon.trainer_id, mon.dvs) for mon in (*snapshot.party, *snapshot.stored))
    else:
        found = ((mon.get('trainer_id'), mon.get('dvs'))
                 for mon in (*map(asdict, snapshot.party), *snapshot.storage_entries()))
    return any(trainer is not None and dvs and mark(trainer, dvs) == wanted for trainer, dvs in found)


def rewound(store, metadata):
    """Send the League claims delivered after the save ``metadata`` describes back to open.

    The ownership barrier refuses most saves from before a gift, so this covers the ones it lets
    through. The gift's own result checkpoint carries its reward id and never reopens its claim.
    """
    frames = ((metadata or {}).get('play_clock') or {}).get('frames')
    if frames is None:
        return ()
    with store.transaction() as db:
        return claims.reopen_after(db, frames, keep=(metadata or {}).get('reward_id'))


def staged_shiny(seed, generation=1):
    """Whether the League gift drawn from ``seed`` has shiny DVs. A shiny gift is always sent."""
    from .shiny import shiny_bytes
    _, first, second = _draw(seed, generation)
    return shiny_bytes(bytes((first, second)))


@functools.lru_cache(maxsize=4096)
def staged_mark(seed, generation=1):
    """The reward mark of the League gift drawn from ``seed``, before the ledger counts it delivered."""
    trainer, first, second = _draw(seed, generation)
    return mark(trainer, (first >> 4, first & 15, second >> 4, second & 15))


def refusal(policy, snapshot, slot, seed, generation=1):
    """Why the gift staged at ``slot`` from ``seed`` only costs a release, or '' when it is kept.
    The worth oracle (pcvalue.worth) refuses it as it would refuse the same copy caught. Such a gift
    either goes itself or pushes out a rarer copy, so sending it turns every League win into a gift
    and a release.

    The gift is rated as the League reward it is. Until the ledger counts it, its mark is unknown, and
    an unmarked gift rates as a Pokémon traded in, the best copy of its species. The mark is passed to
    the rating, so the PC tab and other readers never see it.
    """
    from .pcvalue import worth
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
        return ''
    # Both generations hold 20 Pokémon per box, and the staged gift already fills one slot.
    free = sum(20 - count for count in snapshot.box_counts) + 1
    found = worth([*(other for other in rated if other is not row), row], headroom=free,
                  active_box=getattr(snapshot, 'active_box', None))
    return '' if found.keep else found.reason or 'Not worth a slot'


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


def marks(db, generation=1):
    """The marks of every League reward delivered so far, from the claims alone.

    This also finds rewards delivered before releases knew about them. A random trainer ID and DV pair
    matches another Pokémon about once in four billion.
    """
    return frozenset(staged_mark(row['key'], generation) for row in claims.rows(db, SOURCE, claims.DELIVERED))


def status(store):
    """The League gifts earned, delivered, declined and still open, with the wins and unlocks."""
    with store.reading() as db:
        value, found = ledger(db), claims.counts(db, SOURCE)
    return {'earned': sum(found.values()), 'delivered': found[claims.DELIVERED],
            'declined': found[claims.DECLINED], 'pending': found[claims.OPEN],
            'wins': championship_count(value), 'unlocks': sorted(value.get('unlocks', ()))}


def mew_enabled(policy):
    return bool(policy.get('league_rewards', False) or policy.get('mew_event', False))
