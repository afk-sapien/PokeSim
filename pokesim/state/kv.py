"""Single kv values read and written inside a caller's transaction.

``Store.get`` and ``Store.set`` each take the store's lock and commit on their own. These take the
handle ``Store.transaction()`` or ``Store.reading()`` yields, so several changes commit together.
"""
import json


def get(db, key, default=None):
    row = db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def exists(db, key):
    return db.execute('SELECT 1 FROM kv WHERE k=?', (key,)).fetchone() is not None


def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (key, json.dumps(value)))


def update(db, key, value):
    """Change the value ``key`` already has. A key with no value stays without one."""
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), key))


def add(db, key, value):
    """Write ``value`` only when ``key`` has none yet."""
    db.execute('INSERT OR IGNORE INTO kv(k,v) VALUES (?,?)', (key, json.dumps(value)))


def delete(db, key):
    db.execute('DELETE FROM kv WHERE k=?', (key,))


# For a caller that parses a stored value itself, so a value it cannot read stays as it is.
def text(db, key):
    """The JSON text stored under ``key``, or None."""
    row = db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()
    return row[0] if row else None


def starting(db, prefix):
    """(key, JSON text) of every key that starts with ``prefix``."""
    return db.execute('SELECT k,v FROM kv WHERE substr(k, 1, ?) = ?', (len(prefix), prefix)).fetchall()


def put_text(db, key, raw):
    """Write JSON text as ``text`` or ``starting`` read it."""
    db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (key, raw))
