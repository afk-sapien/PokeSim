"""Walking earns one Mew opportunity, redeemed by a later League victory."""
import json

from . import config, rewards
from .legendary_returns import STEPS

KEY = 'mew-returns-v1'


def observe(store, snapshot):
    walking = store.get(STEPS) or {}
    if not snapshot.valid or not snapshot.started or not walking.get('available'):
        return
    total = walking.get('total', 0)
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000) if getattr(config, 'MEW_EVENT', False) else 0
    value = store.get(KEY)
    initial = bool(store.get('pokesim-mew-v1') or 151 in snapshot.owned)
    from .policies.collection import champion
    eligible = initial and champion(snapshot)
    if value is None:
        if not eligible:
            return
        value = {'interval': every, 'next_at': total + every, 'armed_after_win': None, 'delivered': 0}
    elif value['interval'] != every:
        value.update(interval=every, next_at=total + every, armed_after_win=None)
    if every and eligible and value['armed_after_win'] is None and total >= value['next_at']:
        with store.lock:
            value['armed_after_win'] = rewards.championship_count(rewards.ledger(store.db))
    if value != store.get(KEY):
        store.set(KEY, value)


def ready(store, wins):
    return ready_value(store.get(KEY) or {}, wins)


def ready_db(db, wins):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    return ready_value(json.loads(row[0]) if row else {}, wins)


def ready_value(value, wins):
    armed = value.get('armed_after_win')
    return bool(getattr(config, 'MEW_RETURN_STEPS', 1000000) and armed is not None and wins > armed)


def consume(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    walking = db.execute('SELECT v FROM kv WHERE k=?', (STEPS,)).fetchone()
    total = json.loads(walking[0]).get('total', 0) if walking else 0
    value = json.loads(row[0]) if row else {'delivered': 0}
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000)
    value.update(interval=every, next_at=total + every, armed_after_win=None,
                 delivered=value['delivered'] + 1)
    db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (KEY, json.dumps(value)))


def status(store):
    value = store.get(KEY) or {}
    steps = (store.get(STEPS) or {}).get('total', 0)
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000)
    enabled = bool(every and getattr(config, 'MEW_EVENT', False))
    return {'enabled': enabled, 'first_gift': not value, 'remaining': max(0, value.get('next_at', steps + every) - steps),
            'league_required': enabled and value.get('armed_after_win') is not None,
            'delivered': value.get('delivered', 0)}
