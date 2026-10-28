"""Durable per-species counts for verified completed exchanges."""
import hashlib
import json
import time

from .activity_ledger import increment
from .strategy_data import SPECIES

KEY = 'trade-statistics-v1'


def record(db, identity, sent, received, generation=1):
    """Record both sides once inside the transaction that publishes the trade.

    Red, Blue and Yellow name species by their internal index. Gold, Silver and Crystal
    (``generation=2``) use the National Pokédex number itself.
    """
    if type(sent) is not int or type(received) is not int:
        return False
    if generation == 2:
        if not (1 <= sent <= 251 and 1 <= received <= 251):
            return False
        outgoing, incoming = sent, received
    else:
        if sent not in SPECIES or received not in SPECIES:
            return False
        outgoing, incoming = SPECIES[sent]['dex'], SPECIES[received]['dex']
    if db.execute('INSERT OR IGNORE INTO pokemon_trade_receipts VALUES (?,?,?)',
                  (identity, outgoing, incoming)).rowcount:
        increment(db, 'traded_out', outgoing)
        increment(db, 'traded_in', incoming)
    return True


def record_gen2(db, identity, sent, received):
    return record(db, identity, sent, received, generation=2)


def _outgoing(raw):
    """(generation, species) of a released outgoing struct, or None."""
    if not isinstance(raw, str):
        return None
    try:
        struct = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(struct) in (33, 44):
        return 1, struct[0]
    # A Gold, Silver or Crystal party struct, cable or Time Capsule, opens with its Pokédex number.
    return (2, struct[0]) if len(struct) == 48 else None


def sent_species(raw):
    outgoing = _outgoing(raw)
    return outgoing[1] if outgoing else None


def _managed(db, identity, raw, received):
    outgoing = _outgoing(raw)
    if not isinstance(identity, str) or outgoing is None:
        return False
    return record(db, 'managed:' + identity, outgoing[1], received, generation=outgoing[0])


def managed(db, receipt):
    if receipt.get('decision') != 'COMMIT' or receipt.get('phase') != 'released':
        return
    outgoing = receipt.get('outgoing')
    staged = receipt.get('staged')
    evidence = staged.get('evidence') if isinstance(staged, dict) else None
    # The incoming struct describes the offered Pokémon before trade evolution.
    received = evidence.get('received_species') if isinstance(evidence, dict) else None
    _managed(db, receipt.get('id'), outgoing.get('struct') if isinstance(outgoing, dict) else None, received)


def _history(db):
    """Record every released managed trade not yet counted. Returns how many cannot be."""
    missing = 0
    # Extract only the verified species and identity. Historical rows can contain
    # large policy snapshots, which must not be loaded to recover these counts.
    for identity, raw, received in db.execute(
            "SELECT json_extract(v, '$.id'), json_extract(v, '$.outgoing.struct'), "
            "json_extract(v, '$.staged.evidence.received_species') FROM kv "
            "WHERE k LIKE 'managed_interaction:%' AND json_extract(v, '$.decision')='COMMIT' "
            "AND json_extract(v, '$.phase')='released'").fetchall():
        if not _managed(db, identity, raw, received):
            missing += 1
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='completed_trades'").fetchone():
        missing += db.execute('SELECT COUNT(*) FROM completed_trades').fetchone()[0]
    return missing


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS pokemon_trade_receipts ('
               'id TEXT PRIMARY KEY, sent INTEGER NOT NULL, received INTEGER NOT NULL)')
    if db.execute('SELECT 1 FROM kv WHERE k=?', (KEY,)).fetchone():
        return
    db.execute('INSERT INTO kv VALUES (?,?)', (KEY, json.dumps({'npc_since': None, 'missing_history': _history(db)})))


def backfill_gen2(db):
    """Count the Gold, Silver and Crystal cable trades released before they could be counted."""
    value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
    value['missing_history'] = _history(db)
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))


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
