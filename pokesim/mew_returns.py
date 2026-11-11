"""Walking earns one Mew return, redeemed by a later League victory.

The kv value is the walking clock: the interval, the step total the walk ends at, and the League
wins counted when it ended. The next win opens a ``mew`` claim (return_claims.py), the gift delivers
it, and the clock waits in between.
"""
from . import config, return_claims, rewards
from .legendary_returns import STEPS
from .state import kv

KEY = 'mew-returns-v1'


def observe(store, snapshot):
    walking = store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not walking.get('available'):
        return
    total = walking.get('total', 0)
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000) if getattr(config, 'MEW_EVENT', False) else 0
    stored = store.get(KEY)
    value = stored
    initial = bool(store.get('pokesim-mew-v1') or 151 in snapshot.owned)
    from .policies.collection import champion
    eligible = initial and champion(snapshot)
    if value is None:
        if not eligible:
            return
        value = {'interval': every, 'next_at': total + every, 'armed_after_win': None}
    elif value['interval'] != every:
        value = {**value, 'interval': every, 'next_at': total + every, 'armed_after_win': None}
    if (every and eligible and value['armed_after_win'] is None and value['next_at'] is not None
            and total >= value['next_at']):
        with store.reading() as db:
            value = {**value, 'armed_after_win': rewards.championship_count(rewards.ledger(db))}
    if value != stored:
        store.set(KEY, value)
    if every and (armed := value['armed_after_win']) is not None:
        if rewards.championship_count(store.get(rewards.KEY) or {}) > armed:
            earn(store)


def earn(store):
    """Open the Mew claim once a League win follows the finished walk."""
    from .progress_events import frame
    with store.transaction() as db:
        return_claims.earn_mew(db, 1, frame(store))


def ready(store):
    with store.reading() as db:
        return ready_db(db)


def ready_db(db):
    """The open Mew claim, while Mew returns are on."""
    return return_claims.open_mew(db) if getattr(config, 'MEW_RETURN_STEPS', 1000000) else None


def deliver(db, number, *, frame, seed, reward_id=None, reasons=''):
    """Mark claim ``number`` delivered in the gift's transaction, and walk again from here."""
    total = kv.get(db, STEPS, {}).get('total', 0)
    return_claims.deliver_mew(db, number, 1, frame=frame, seed=seed, reward_id=reward_id, total=total,
                              every=getattr(config, 'MEW_RETURN_STEPS', 1000000), reasons=reasons)


def status(store):
    value = store.get(KEY) or {}
    steps = (store.get(STEPS) or {}).get('total', 0)
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000)
    enabled = bool(every and getattr(config, 'MEW_EVENT', False))
    with store.reading() as db:
        waiting, delivered = return_claims.open_mew(db), return_claims.mew_delivered(db)
    due = value.get('next_at', steps + every)
    return {'enabled': enabled, 'interval': every, 'first_gift': not value,
            'remaining': 0 if due is None else max(0, due - steps),
            'league_required': enabled and (value.get('armed_after_win') is not None or waiting is not None),
            'delivered': delivered}
