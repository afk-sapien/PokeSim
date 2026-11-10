"""The statements of the trade and reward ledgers that go past a single kv value.

The managed exchange records, the trade receipts and the upkeep that recovery runs at boot. Each
function runs on the handle ``Store.transaction()``, ``Store.reading()`` or ``Store.durable()``
yields. The ledgers decide what to write. Their single kv values go through pokesim/state/kv.py.
See docs/design/adventure-state-store.md, slice R1.
"""
# Each managed exchange keeps its record under this prefix and its id.
INTERACTIONS = 'managed_interaction:'
# An exchange in one of these phases never promotes its snapshot again.
FINISHED = ('released', 'aborted')


# --- managed exchanges ---
def unreleased(db):
    """The JSON text of every exchange record not yet released.

    A record keeps the whole policy snapshot it was staged from, so the caller parses the
    text after it lets the lock go.
    """
    return [row[0] for row in db.execute(
        "SELECT v FROM kv WHERE k LIKE ? AND COALESCE(json_extract(v, '$.phase'), '') <> 'released'",
        (INTERACTIONS + '%',)).fetchall()]


def compact_finished(db, limit):
    """Drop the staged snapshot of up to ``limit`` finished exchanges, without parsing them here."""
    db.execute(
        "UPDATE kv SET v = json_remove(v, '$.source_metadata') WHERE k IN ("
        "  SELECT k FROM kv WHERE k LIKE ?"
        "   AND json_extract(v, '$.phase') IN (?, ?)"
        "   AND json_extract(v, '$.source_metadata') IS NOT NULL"
        "   LIMIT ?)", (INTERACTIONS + '%', *FINISHED, limit))


def finished(db):
    """The ids of every finished exchange."""
    return {row[0][len(INTERACTIONS):] for row in db.execute(
        "SELECT k FROM kv WHERE k LIKE ? AND json_extract(v, '$.phase') IN (?, ?)",
        (INTERACTIONS + '%', *FINISHED))}


def released_trades(db):
    """The id, outgoing struct and species evidence of every released managed trade.

    Only these fields leave SQLite, since a record can still hold a large policy snapshot.
    """
    return db.execute(
        "SELECT json_extract(v, '$.id'), json_extract(v, '$.outgoing.struct'), "
        "json_extract(v, '$.staged.evidence.received_species'), json_extract(v, '$.staged.evidence.sent_species'), "
        "json_extract(v, '$.staged.evidence.received') FROM kv "
        "WHERE k LIKE 'managed_interaction:%' AND json_extract(v, '$.decision')='COMMIT' "
        "AND json_extract(v, '$.phase')='released'").fetchall()


# --- trade receipts ---
def add_trade_receipt(db, identity, outgoing, incoming):
    """Keep one receipt per exchange. Returns whether it is new, so a replayed exchange counts once."""
    return bool(db.execute('INSERT OR IGNORE INTO pokemon_trade_receipts VALUES (?,?,?)',
                           (identity, outgoing, incoming)).rowcount)


def legacy_trades(db):
    """The rows in the completed_trades table of older versions, or 0 where it was never made."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='completed_trades'").fetchone():
        return db.execute('SELECT COUNT(*) FROM completed_trades').fetchone()[0]
    return 0


# --- the legacy pair trade (pokesim/trade) ---
def complete_pair_trade(db, key):
    """Mark a pair trade done. False when it already was, so its journal entry is written once."""
    return db.execute('INSERT OR IGNORE INTO completed_trades(id) VALUES (?)', (key,)).rowcount > 0


def complete_pair_event(db, transaction):
    """Mark a pair gift transaction done. False when it already was."""
    return db.execute('INSERT OR IGNORE INTO completed_events(id) VALUES (?)', (transaction,)).rowcount > 0


# --- upkeep ---
def free_bytes(db):
    """The bytes SQLite keeps in free pages and never gives back on its own."""
    free, size = (db.execute(f'PRAGMA {name}').fetchone()[0] for name in ('freelist_count', 'page_size'))
    return free * size


def vacuum(db):
    """Rebuild the file without its free pages. It runs outside any transaction."""
    db.execute('VACUUM')
