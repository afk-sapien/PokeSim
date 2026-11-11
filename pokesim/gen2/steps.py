"""Cartridge walking counts and repeat Mew claims independent of save rewinds."""
import time

from .. import config, return_claims, rewards
from pokecore.gen2.hooks import step_hook
from pokecore.gen2.ram import Memory

STEPS = 'cartridge-steps-v1'
RETURNS = 'gen2-mew-returns-v1'


class StepTracker:
    def __init__(self, store, data):
        self.store, self.data = store, data
        self.value = store.get(STEPS) or {'total': 0, 'started_at': time.time(), 'available': True}
        self.last_flush = 0

    def attach(self, pb):
        pb.hook_register(*step_hook(pb.memory, self.data), self.completed, pb)

    def completed(self, pb):
        if not Memory(pb.memory, self.data).byte('wLinkMode'):
            self.value['total'] += 1

    def flush(self, *, force=False):
        now = time.monotonic()
        if force or now - self.last_flush >= 30:
            self.store.set(STEPS, self.value)
            self.last_flush = now


def observe_mew(store, snapshot, total):
    """Keep the Mew walking clock, and open the Mew claim once a League win follows its walk
    (return_claims.py). The clock waits while the claim is open."""
    if not snapshot.valid or not snapshot.started or not snapshot.hall_of_fame_count:
        return
    if 151 not in snapshot.owned and not store.get('gen2-mythical-gift-v1'):
        return
    every = config.MEW_RETURN_STEPS if getattr(config, 'MEW_EVENT', False) else 0
    stored = store.get(RETURNS)
    value = stored
    if not value:
        value = {'interval': every, 'next_at': total + every, 'armed_after_win': None}
    if value['interval'] != every:
        value = {**value, 'interval': every, 'next_at': total + every, 'armed_after_win': None}
    if every and value['armed_after_win'] is None and value['next_at'] is not None and total >= value['next_at']:
        with store.reading() as db:
            value = {**value, 'armed_after_win': rewards.championship_count(rewards.ledger(db))}
    if value != stored:
        store.set(RETURNS, value)
    if every and (armed := value['armed_after_win']) is not None:
        if rewards.championship_count(store.get(rewards.KEY) or {}) > armed:
            from ..progress_events import frame
            with store.transaction() as db:
                return_claims.earn_mew(db, 2, frame(store))


def ready(db):
    """The open Mew claim, while Mew returns are on."""
    if getattr(config, 'MEW_EVENT', False) and config.MEW_RETURN_STEPS:
        return return_claims.open_mew(db)
    return None


def deliver(db, number, total, *, frame, seed, reward_id=None, reasons=''):
    """Mark claim ``number`` delivered in the gift's transaction, and walk again from step ``total``."""
    return_claims.deliver_mew(db, number, 2, frame=frame, seed=seed, reward_id=reward_id, total=total,
                              every=config.MEW_RETURN_STEPS, reasons=reasons)


def status(store):
    value = store.get(RETURNS) or {}
    total = (store.get(STEPS) or {}).get('total', 0)
    every = config.MEW_RETURN_STEPS
    enabled = bool(every and getattr(config, 'MEW_EVENT', False))
    with store.reading() as db:
        waiting, delivered = return_claims.open_mew(db), return_claims.mew_delivered(db)
    due = value.get('next_at', total + every)
    return {'enabled': enabled, 'interval': every, 'first_gift': not value,
            'remaining': 0 if due is None else max(0, due - total),
            'league_required': enabled and (value.get('armed_after_win') is not None or waiting is not None),
            'delivered': delivered}
