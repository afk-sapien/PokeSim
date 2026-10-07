"""Useful Champion supplies and capped walking offers."""
import json

from .legendary_returns import STEPS
from .policies.collection import EVOS, champion
from .strategy_data import ITEMS, MOVES
from .tm_shop import PURCHASE_BAG_LIMIT, RESERVE, signature

KEY = 'champion-shop-v1'
INTERVAL = 1000000
PRICES = {ITEMS['MOON_STONE']: 5000, ITEMS['PP_UP']: 25000,
          ITEMS['ELIXER']: 5000, ITEMS['MAX_ELIXER']: 10000,
          ITEMS['MASTER_BALL']: 100000, ITEMS['RARE_CANDY']: 25000}
OFFERS = {ITEMS['MASTER_BALL']: 1, ITEMS['RARE_CANDY']: 5}
NAMES = {ITEMS[name]: label for name, label in (
    ('MOON_STONE', 'Moon Stone'), ('PP_UP', 'PP Up'), ('ELIXER', 'Elixir'),
    ('MAX_ELIXER', 'Max Elixir'), ('MASTER_BALL', 'Master Ball'), ('RARE_CANDY', 'Rare Candy'))}


def observe(store, snapshot):
    walking = store.get(STEPS) or {}
    if (store.get(KEY) is None and walking.get('available') and snapshot.valid
            and snapshot.started and champion(snapshot)):
        store.set(KEY, {str(item): {'next_at': walking['total'] + INTERVAL, 'purchased': 0}
                        for item in OFFERS})


def status(store):
    value = store.get(KEY) or {}
    walking = store.get(STEPS) or {}
    total = walking.get('total', 0)
    return {'started': bool(value), 'available': bool(walking.get('available')),
            'interval': INTERVAL, 'offers': [
                {'item': item, 'name': NAMES[item], 'quantity': quantity, 'price': PRICES[item],
                 'remaining': max(0, value.get(str(item), {}).get('next_at', total + INTERVAL) - total),
                 'purchased': value.get(str(item), {}).get('purchased', 0)}
                for item, quantity in OFFERS.items()]}


def ready(store):
    value = status(store)
    return {row['item'] for row in value['offers'] if value['started'] and value['available'] and not row['remaining']}


def consume(db, item):
    """Redeem inside the same transaction as cash, checkpoint, and item counts."""
    def read(key):
        row = db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
        return json.loads(row[0]) if row else {}
    value, walking = read(KEY), read(STEPS)
    offer = value.get(str(item))
    if not walking.get('available') or not offer or walking.get('total', 0) < offer['next_at']:
        raise ValueError('This Champion shop offer is not ready')
    offer.update(next_at=walking['total'] + INTERVAL, purchased=offer['purchased'] + 1)
    db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (KEY, json.dumps(value)))


def pp_slot(mon):
    options = []
    for slot, mid in enumerate(mon.moves):
        move = MOVES.get(mid, {})
        base = move.get('pp', 0)
        maximum = mon.max_pp[slot] if slot < len(mon.max_pp) else 0
        if (mon.level >= 60 and mon.hp > 0 and not mon.status and 0 < base <= 20
                and move.get('power', 0) >= 60 and move.get('effect') not in ('EXPLODE_EFFECT', 'OHKO_EFFECT')
                and base <= maximum < base + 3 * (base // 5)):
            options.append((move['power'], -base, -slot))
    return -max(options)[2] if options else None


def recipient(snapshot, item):
    if item == ITEMS['PP_UP']:
        candidates = [i for i, mon in enumerate(snapshot.party) if pp_slot(mon) is not None]
    elif item == ITEMS['RARE_CANDY']:
        candidates = [i for i, mon in enumerate(snapshot.party) if 30 <= mon.level < 100 and mon.hp > 0]
    elif item == ITEMS['MOON_STONE']:
        individuals = list(snapshot.party) + snapshot.storage_entries()
        needed = any(True for mon in individuals
                     for evo in EVOS.get(mon.species if hasattr(mon, 'species') else mon['species'], ())
                     if evo['method'] == 'item' and evo['requirement'] == 'MOON_STONE')
        return 0 if needed and snapshot.party else None
    else:
        candidates = [i for i, mon in enumerate(snapshot.party) if mon.level >= 35 and mon.hp > 0]
    return max(candidates, key=lambda i: snapshot.party[i].level) if candidates else None


def valid_plan(snapshot, plan, offers):
    item, target = plan['item'], plan['target']
    if (item not in PRICES or not champion(snapshot) or not 0 <= target < len(snapshot.party)
            or signature(snapshot.party[target]) != plan['signature'] or recipient(snapshot, item) is None):
        return False
    mon = snapshot.party[target]
    if item == ITEMS['PP_UP'] and pp_slot(mon) is None:
        return False
    if item == ITEMS['RARE_CANDY'] and not 30 <= mon.level < 100:
        return False
    quantity = OFFERS.get(item, 1)
    count = dict(snapshot.items).get(item, 0)
    return (not count and len(snapshot.items) < PURCHASE_BAG_LIMIT and snapshot.money >= PRICES[item] + RESERVE
            and plan.get('quantity') == quantity and (item not in OFFERS or item in offers))


def choose(snapshot, offers):
    if not champion(snapshot):
        return None
    # Capped walking offers take priority over ordinary supplies.
    for item in (*OFFERS, ITEMS['MOON_STONE'], ITEMS['PP_UP'], ITEMS['MAX_ELIXER'], ITEMS['ELIXER']):
        target = recipient(snapshot, item)
        if target is None:
            continue
        plan = {'item': item, 'target': target, 'signature': signature(snapshot.party[target]),
                'quantity': OFFERS.get(item, 1), 'supply': True}
        if valid_plan(snapshot, plan, offers):
            return plan
    return None
