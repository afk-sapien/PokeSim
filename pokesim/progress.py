"""The headline numbers of an adventure over time: one row each time one of them changes.

Every change to the game's own counts already reaches the journal (a new Pokédex entry, a badge,
a League win), so a row is written in the same transaction as the entry that announced it, from
the same snapshot. Level 100 species and perfect finds are the long goals, recorded by the
milestone tracker; a row follows each change to them, in the transaction that stored it.
"""
import json
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
  ts REAL NOT NULL,
  badges INTEGER NOT NULL,
  owned INTEGER NOT NULL,
  seen INTEGER,
  league INTEGER NOT NULL,
  level100 INTEGER,
  perfect INTEGER
);
"""
FIELDS = ('badges', 'owned', 'seen', 'league', 'level100', 'perfect')
COLUMNS = ', '.join(FIELDS)


def migrate(db):
    # 0.4.0 tables predate the long goals; their rows keep none, so those lines start at upgrade.
    columns = {row[1] for row in db.execute('PRAGMA table_info(progress)')}
    for name in ('level100', 'perfect'):
        if name not in columns:
            db.execute(f'ALTER TABLE progress ADD COLUMN {name} INTEGER')


def _last(db):
    row = db.execute(f'SELECT {COLUMNS} FROM progress ORDER BY rowid DESC LIMIT 1').fetchone()
    return tuple(row) if row else None


def _goals(db):
    """Level 100 species and perfect finds, as the Pokédex counts them."""
    from .milestones import KEY
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    value = json.loads(row[0]) if row else {}
    return len(value.get('level_100', ())), sum(value.get('perfect_groups', {}).values())


def _write(db, ts, row, previous):
    if row == previous:
        return False
    db.execute(f'INSERT INTO progress(ts, {COLUMNS}) VALUES (?,?,?,?,?,?,?)', (ts, *row))
    return True


def record(db, ts, snapshot, won=False):
    """Run in the event transaction. `won` is a League victory that was not a replay."""
    if not snapshot.valid or not snapshot.started:
        return False
    previous = _last(db)
    league = (previous[3] if previous else 0) + int(won)
    row = (bin(snapshot.badges).count('1'), len(snapshot.owned), len(snapshot.seen), league, *_goals(db))
    return _write(db, ts, row, previous)


def goals_changed(db, ts):
    """Run in the transaction that stored new milestones. Waits for the adventure's first row,
    which carries the game's own counts."""
    previous = _last(db)
    if previous is None:
        return False
    return _write(db, ts, (*previous[:4], *_goals(db)), previous)


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
            db.execute(f'SELECT ts, {COLUMNS} FROM progress ORDER BY rowid')]
