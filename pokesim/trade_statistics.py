"""Durable per-species counts for verified completed exchanges."""
import hashlib
import json
import time

from .activity_ledger import increment
from .strategy_data import SPECIES

KEY = 'trade-statistics-v1'


def record(db, identity, sent, received):
    """Record both sides once inside the transaction that publishes the trade."""
    if (type(sent) is not int or type(received) is not int
            or sent not in SPECIES or received not in SPECIES):
        return False
    outgoing, incoming = SPECIES[sent]['dex'], SPECIES[received]['dex']
    if db.execute('INSERT OR IGNORE INTO pokemon_trade_receipts VALUES (?,?,?)',
                  (identity, outgoing, incoming)).rowcount:
        increment(db, 'traded_out', outgoing)
        increment(db, 'traded_in', incoming)
    return True


def sent_species(raw):
    if not isinstance(raw, str):
        return None
    try:
        struct = bytes.fromhex(raw)
    except ValueError:
        return None
    return struct[0] if len(struct) in (33, 44) else None


def managed(db, receipt):
    if receipt.get('decision') != 'COMMIT' or receipt.get('phase') != 'released':
        return
    outgoing = receipt.get('outgoing')
    staged = receipt.get('staged')
    evidence = staged.get('evidence') if isinstance(staged, dict) else None
    sent = sent_species(outgoing.get('struct')) if isinstance(outgoing, dict) else None
    # The incoming struct describes the offered Pokémon before trade evolution.
    received = evidence.get('received_species') if isinstance(evidence, dict) else None
    record(db, 'managed:' + receipt['id'], sent, received)


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS pokemon_trade_receipts ('
               'id TEXT PRIMARY KEY, sent INTEGER NOT NULL, received INTEGER NOT NULL)')
    if db.execute('SELECT 1 FROM kv WHERE k=?', (KEY,)).fetchone():
        return
    missing = 0
    # Extract only the verified species and identity. Historical rows can contain
    # large policy snapshots, which must not be loaded to recover these counts.
    for identity, raw, received in db.execute(
            "SELECT json_extract(v, '$.id'), json_extract(v, '$.outgoing.struct'), "
            "json_extract(v, '$.staged.evidence.received_species') FROM kv "
            "WHERE k LIKE 'managed_interaction:%' AND json_extract(v, '$.decision')='COMMIT' "
            "AND json_extract(v, '$.phase')='released'"):
        if not isinstance(identity, str) or not record(db, 'managed:' + identity, sent_species(raw), received):
            missing += 1
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='completed_trades'").fetchone():
        missing += db.execute('SELECT COUNT(*) FROM completed_trades').fetchone()[0]
    db.execute('INSERT INTO kv VALUES (?,?)', (KEY, json.dumps({'npc_since': None, 'missing_history': missing})))


def npc(store, memory):
    # TradeText THANKS is written only after the replacement and evolution finish.
    count = memory[0xd163]
    if memory[0xcd12] != 3 or not 1 <= count <= 6:
        return
    sent = memory[0xcd0f]
    received = memory[0xd16b + (count - 1) * 44]
    identity = 'npc:' + hashlib.sha256(bytes(memory[0xc000:0xe000])).hexdigest()
    with store.lock, store.db:
        record(store.db, identity, sent, received)


def tracking(db):
    value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
    if value['npc_since'] is None:
        value['npc_since'] = time.time()
        db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))
