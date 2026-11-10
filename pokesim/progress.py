"""The headline numbers of an adventure over time: one row each time one of them changes.

Every change to the game's own counts already reaches the journal (a new Pokédex entry, a badge,
a League win), so a row is written in the same transaction as the entry that announced it, from
the same snapshot. Level 100 species and perfect finds are the long goals, recorded by the
milestone tracker; a row follows each change to them, in the transaction that stored it.
"""
import re

from .state import journal, kv, tracking
from .state.tracking import PROGRESS_FIELDS as FIELDS

# The progress table comes from the schema version (pokesim.state).
COLUMNS = ', '.join(FIELDS)


def _goals(db):
    """Level 100 species and perfect finds, as the Pokédex counts them."""
    value = kv.get(db, 'pokedex-milestones-v1', {})
    return len(value.get('level_100', ())), sum(value.get('perfect_groups', {}).values())


def _write(db, ts, row, previous):
    if row == previous:
        return False
    tracking.add_progress_row(db, ts, row)
    return True


def record(db, ts, snapshot, won=False):
    """Run in the event transaction. `won` is a League victory that was not a replay."""
    if not snapshot.valid or not snapshot.started:
        return False
    previous = tracking.last_progress(db)
    league = (previous[3] if previous else 0) + int(won)
    row = (bin(snapshot.badges).count('1'), len(snapshot.owned), len(snapshot.seen), league, *_goals(db))
    return _write(db, ts, row, previous)


def goals_changed(db, ts):
    """Run in the transaction that stored new milestones. Waits for the adventure's first row,
    which carries the game's own counts."""
    previous = tracking.last_progress(db)
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
    if tracking.has_progress(db):
        return 0
    badges = owned = league = 0
    victories, rows, previous = set(), [], None
    for event in journal.every_entry(db):
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
    tracking.backfill_progress(db, rows)
    return len(rows)


def history(db):
    return [dict(zip(('ts', *FIELDS), row)) for row in tracking.progress_history(db)]
