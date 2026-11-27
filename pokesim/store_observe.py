"""The part of a Red, Blue or Yellow observation that an adventure store keeps: the walked steps, the
Mew, event and legendary returns, the Champion counter's offers, the legendary retries and the Pokédex
goals, with the policy inputs read back from them.

The application (Emulator._observe_snapshot) and a headless run (adapter.py) both observe through
``observe``, so a headless run plays the offers, returns and goals the application would, from a store
of its own.
"""
from __future__ import annotations

from .ram import read_snapshot


def decline_returns(store, policy):
    """Close the returned legendaries the battle refused to catch."""
    from .legendary_returns import decline
    collection = getattr(policy, 'collection', None)
    declined = getattr(collection, 'declined_returns', None)
    if isinstance(declined, set):
        for number in declined:
            decline(store, number)
        collection.declined_returns = set()


def keeps_another(policy, snapshot):
    """Whether the PC would keep one more copy of a dex number, rated with no DVs as the battle
    rates a wild copy with its own (collection.improves), or None when the policy has no PC."""
    rating = getattr(policy, 'catch_rating', None)
    if rating is None:
        return None
    from .policies.collection import improves
    from .strategy_data import SPECIES

    def keeps(number):
        species = next(sid for sid, row in SPECIES.items() if row['dex'] == number)
        return improves(snapshot, species, (), rating(snapshot))
    return keeps


def observe(host, snap, now, *, returns=True):
    """Observe ``snap`` for the store of ``host``, an application emulator or a headless run, at
    PlayClock frame ``now``. ``returns`` is False where the returns wait: a trade hold or manual play.

    Returns ``(events, snap, restored)``. A return or retry that restores an encounter writes the
    cartridge, so ``snap`` is then read again and ``restored`` is True."""
    events, restored = [], False
    if returns:
        store, policy, memory = host.store, host.policy, host.pb.memory
        collection = getattr(policy, 'collection', None)
        from . import champion_shop, mew_returns, step_events
        from .legendary_returns import claims, observe as returns_observe
        tracker = getattr(host, 'step_tracker', None)
        if tracker is not None:
            tracker.flush()
        mew_returns.observe(store, snap)
        champion_shop.observe(store, snap)
        if hasattr(policy, 'shop_offers'):
            policy.shop_offers = champion_shop.ready(store)
        events, restored = returns_observe(store, snap, memory)
        activity_events, activity_changed = step_events.observe(store, snap, memory, keeps_another(policy, snap))
        events += activity_events
        restored |= activity_changed or bool(activity_events)
        if collection is not None:
            collection.returned_events = step_events.available(store)
        if restored:
            snap = read_snapshot(memory, host.frame)
        decline_returns(store, policy)
        ready, closed = claims(store)
        if collection is not None:
            collection.returned_legendaries, collection.closed_legendaries = ready, closed
        recovery_events, recovered = host.legendary_recovery.observe(snap, memory, now, repeat=ready,
                                                                     blocked=closed)
        restored |= recovered
        events += recovery_events
        if restored:
            snap = read_snapshot(memory, host.frame)
    milestones = getattr(host, 'milestones', None)
    if milestones is not None:
        milestones.observe(snap)
        collection = getattr(host.policy, 'collection', None)
        if collection is not None:
            from .milestones import status
            collection.milestones = status(host.store)
    return events, snap, restored


def rows(db):
    """The rows ``observe`` reads, from an adventure's database handle, as a headless checkpoint
    carries them: each kv value by key and the return claims, oldest first. The League rewards stay
    out, since a headless run earns none.

    Wall-clock times stay out too, so two runs of one save write the same manifest and trace the
    same game: when the step count began and when each claim last changed. Play reads neither."""
    from .legendary_returns import STEPS
    from .return_claims import EVENT, MEW, SOURCE
    from .state import claims, domains, kv
    values = {domain.key: kv.get(db, domain.key) for domain in domains.carried(1) if kv.exists(db, domain.key)}
    if STEPS in values:
        values[STEPS] = {name: value for name, value in values[STEPS].items() if name != 'started_at'}
    return {'kv': values, 'claims': [{field: row[field] for field in claims.FIELDS if field != 'ts'}
                                     for source in (SOURCE, EVENT, MEW) for row in claims.rows(db, source)]}


def put_rows(store, carried):
    """Write the rows a checkpoint carries (``rows``) into ``store``, in one transaction. Each claim
    takes the load's time, as a claim written then would."""
    import time

    from .state import claims, domains, kv
    now = time.time()
    with store.transaction() as db:
        for domain in domains.carried(1):
            if domain.key in carried['kv']:
                kv.put(db, domain.key, carried['kv'][domain.key])
        db.executemany(f'INSERT OR REPLACE INTO claims({", ".join(claims.FIELDS)}) '
                       f'VALUES ({", ".join("?" * len(claims.FIELDS))})',
                       [tuple(now if field == 'ts' else row[field] for field in claims.FIELDS)
                        for row in carried['claims']])
