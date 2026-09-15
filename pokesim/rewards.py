"""Persistent Championship reward claims, independent of checkpoint rewinds."""
import json
import random
import secrets

KEY = 'league-rewards-v1'
POOL = (153, 176, 177, 102, 98, 90, 171, 21)


def ledger(db):
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    return (json.loads(row[0]) if row else None) or {'earned': 0, 'delivered': 0}


def save(db, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (KEY, json.dumps(value)))


def earn(store, count):
    with store.lock, store.db:
        value = ledger(store.db)
        value.setdefault('seed', secrets.token_hex(16))
        value['earned'] = max(value['earned'], count)
        save(store.db, value)


def status(store):
    with store.lock:
        value = ledger(store.db)
    return {key: value[key] for key in ('earned', 'delivered')} | {
        'pending': max(0, value['earned'] - value['delivered'])}


def selection(value):
    ordinal = value['delivered'] + 1
    seed = f"{value['seed']}:{ordinal}"
    return ordinal, random.Random(seed).choice(POOL), seed
