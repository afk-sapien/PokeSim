"""Cartridge walking counts and repeat Mew claims independent of save rewinds."""
import json
import time

from .. import config, rewards
from .ram import Memory

STEPS = 'cartridge-steps-v1'
RETURNS = 'gen2-mew-returns-v1'
SIGNATURES = {'gold': 'fa42d0a7204a3e24', 'silver': 'fa42d0a7204a3e24', 'crystal': 'fadcc2a7204a3e24'}


class StepTracker:
    def __init__(self, store, data):
        self.store, self.data = store, data
        self.value = store.get(STEPS) or {'total': 0, 'started_at': time.time(), 'available': True}
        self.last_flush = 0

    def attach(self, pb):
        bank, address = self.data.symbols['CountStep']
        if bytes(pb.memory[bank, address:address + 8]).hex() != SIGNATURES[self.data.game]:
            raise ValueError('The Gen II walking instruction signature does not match the cartridge')
        pb.hook_register(bank, address, self.completed, pb)

    def completed(self, pb):
        if not Memory(pb.memory, self.data).byte('wLinkMode'):
            self.value['total'] += 1

    def flush(self, *, force=False):
        now = time.monotonic()
        if force or now - self.last_flush >= 30:
            self.store.set(STEPS, self.value)
            self.last_flush = now


def observe_mew(store, snapshot, total):
    if not snapshot.valid or not snapshot.started or not snapshot.hall_of_fame_count:
        return
    if 151 not in snapshot.owned and not store.get('gen2-mythical-gift-v1'):
        return
    every = config.MEW_RETURN_STEPS if getattr(config, 'MEW_EVENT', False) else 0
    value = store.get(RETURNS)
    if not value:
        value = {'interval': every, 'next_at': total + every, 'armed_after_win': None, 'delivered': 0}
    if value['interval'] != every:
        value.update(interval=every, next_at=total + every, armed_after_win=None)
    if every and value['armed_after_win'] is None and total >= value['next_at']:
        with store.lock:
            value['armed_after_win'] = rewards.championship_count(rewards.ledger(store.db))
    if value != store.get(RETURNS):
        store.set(RETURNS, value)


def ready(value, wins):
    armed = (value or {}).get('armed_after_win')
    return bool(getattr(config, 'MEW_EVENT', False) and config.MEW_RETURN_STEPS and armed is not None and wins > armed)


def consume(db, total):
    row = db.execute('SELECT v FROM kv WHERE k=?', (RETURNS,)).fetchone()
    value = json.loads(row[0])
    value.update(next_at=total + config.MEW_RETURN_STEPS, armed_after_win=None, delivered=value['delivered'] + 1)
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), RETURNS))


def status(store):
    value = store.get(RETURNS) or {}
    total = (store.get(STEPS) or {}).get('total', 0)
    every = config.MEW_RETURN_STEPS
    enabled = bool(every and getattr(config, 'MEW_EVENT', False))
    return {'enabled': enabled, 'interval': every, 'first_gift': not value,
            'remaining': max(0, value.get('next_at', total + every) - total),
            'league_required': enabled and value.get('armed_after_win') is not None,
            'delivered': value.get('delivered', 0)}
