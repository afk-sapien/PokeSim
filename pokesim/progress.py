"""The headline numbers of an adventure over time: one row each time one of them changes.

Every change already reaches the journal (a new Pokédex entry, a badge, a League win), so a
row is written in the same transaction as the entry that announced it, from the same snapshot.
"""
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
  ts REAL NOT NULL,
  badges INTEGER NOT NULL,
  owned INTEGER NOT NULL,
  seen INTEGER,
  league INTEGER NOT NULL
);
"""
FIELDS = ('badges', 'owned', 'seen', 'league')


def _last(db):
    row = db.execute('SELECT badges, owned, seen, league FROM progress ORDER BY rowid DESC LIMIT 1').fetchone()
    return tuple(row) if row else None


def record(db, ts, snapshot, won=False):
    """Run in the event transaction. `won` is a League victory that was not a replay."""
    if not snapshot.valid or not snapshot.started:
        return False
    previous = _last(db)
    league = (previous[3] if previous else 0) + int(won)
    row = (bin(snapshot.badges).count('1'), len(snapshot.owned), len(snapshot.seen), league)
    if row == previous:
        return False
    db.execute('INSERT INTO progress(ts, badges, owned, seen, league) VALUES (?,?,?,?,?)', (ts, *row))
    return True


OWNED = re.compile(r'\b(\d{1,3}) owned\b')
BADGES = re.compile(r'\b([0-8])(?:/8)? badges\b')
VICTORY = re.compile(r'Champion! League victory #(\d+)')


def backfill(db):
    """Rebuild the history of an adventure recorded before this table, from its journal.

    Entries only ever described the numbers in words, so this reads those words. Seen counts
    were never written down and stay empty. A League victory replayed after a rewind counts once.
    """
    if db.execute('SELECT 1 FROM progress LIMIT 1').fetchone():
        return 0
    badges = owned = league = 0
    victories, rows, previous = set(), [], None
    for event in db.execute('SELECT id, ts, type, title, body FROM events ORDER BY id'):
        _, ts, kind, title, body = event
        if match := OWNED.search(body):
            owned = int(match[1])
        if kind in ('badge', 'playtime') and (match := BADGES.search(body)):
            badges = int(match[1])
        if kind == 'champion':
            match = VICTORY.fullmatch(title)
            token = match[1] if match else f'event:{event[0]}'
            if token not in victories:
                victories.add(token)
                league += 1
        if (badges, owned, league) != previous:
            previous = (badges, owned, league)
            rows.append((ts, badges, owned, None, league))
    db.executemany('INSERT INTO progress(ts, badges, owned, seen, league) VALUES (?,?,?,?,?)', rows)
    return len(rows)


def history(db):
    return [dict(zip(('ts', *FIELDS), row)) for row in
            db.execute('SELECT ts, badges, owned, seen, league FROM progress ORDER BY rowid')]
