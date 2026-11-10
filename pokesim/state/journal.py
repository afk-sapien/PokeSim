"""The adventure journal, the events table.

Each function runs inside its caller's transaction, so an entry commits with the ledger change it
tells of. Slice R1 adds the entry a committed trade, gift or purchase writes. Slice R3 brings the
rest of the journal here. See docs/design/adventure-state-store.md.
"""


def add(db, ts, kind, title, body, notable, priority, place, playtime='', detail=None):
    """Write one journal entry and return its id. ``detail`` is JSON text or None."""
    return db.execute('INSERT INTO events(ts,type,title,body,notable,priority,map,playtime,detail) '
                      'VALUES (?,?,?,?,?,?,?,?,?)',
                      (ts, kind, title, body, notable, priority, place, playtime, detail)).lastrowid
