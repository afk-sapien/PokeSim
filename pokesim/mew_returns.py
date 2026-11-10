"""Walking earns one Mew opportunity, redeemed by a later League victory."""
from . import config, rewards
from .legendary_returns import STEPS
from .state import kv

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
        with store.reading() as db:
            value['armed_after_win'] = rewards.championship_count(rewards.ledger(db))
    if value != store.get(KEY):
        store.set(KEY, value)


def ready(store, wins):
    return ready_value(store.get(KEY) or {}, wins)


def ready_db(db, wins):
    return ready_value(kv.get(db, KEY, {}), wins)


def ready_value(value, wins):
    armed = value.get('armed_after_win')
    return bool(getattr(config, 'MEW_RETURN_STEPS', 1000000) and armed is not None and wins > armed)


def consume(db):
    total = kv.get(db, STEPS, {}).get('total', 0)
    value = kv.get(db, KEY, {'delivered': 0})
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000)
    value.update(interval=every, next_at=total + every, armed_after_win=None,
                 delivered=value['delivered'] + 1)
    kv.put(db, KEY, value)


def status(store):
    value = store.get(KEY) or {}
    steps = (store.get(STEPS) or {}).get('total', 0)
    every = getattr(config, 'MEW_RETURN_STEPS', 1000000)
    enabled = bool(every and getattr(config, 'MEW_EVENT', False))
    return {'enabled': enabled, 'interval': every, 'first_gift': not value, 'remaining': max(0, value.get('next_at', steps + every) - steps),
            'league_required': enabled and value.get('armed_after_win') is not None,
            'delivered': value.get('delivered', 0)}
