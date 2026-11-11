"""Legendary and event returns as rows in the claims ledger, for both generations
(docs/design/goal-system.md section 7).

A walking milestone opens one ``legendary`` claim per returning Pokémon. Writing its encounter into
the cartridge delivers the claim, the verified capture receipt consumes it, and a battle that
refuses the catch declines it. A consumed or declined claim stays closed until the next milestone
opens it again. A reload to a save from before the delivery sends the claim back to open
(``claims.reopen_after``), so the encounter is written again.

An ``event`` claim is keyed by its activity, such as ``snorlax``, ``fossil`` or ``trade_6``. Clearing
its flags in the cartridge delivers it, a completed visit or a capture consumes it, and a gift the
PC would release declines it. Each activity's walking clock stays in its generation's kv value.
"""
from . import config
from .state import claims as ledger

SOURCE = 'legendary'
EVENT = 'event'
REFUSED = 'Not better than the copy the PC holds'
SKIPPED = 'The PC would release it as a spare'
# The kv keys whose tickets schema version 3 moved into rows.
KEYS = ('legendary-returns-v1', 'gen2-legendary-returns-v1')
STATES = {'pending': ledger.OPEN, 'available': ledger.DELIVERED, 'caught': ledger.CONSUMED,
          'declined': ledger.DECLINED}
# The kv keys whose event tickets schema version 4 moved into rows. Gen II notes a capture on its
# next safe frame, so its clocks also keep the last cycle the journal reported.
EVENT_KEYS = (('step-events-v1', False), ('gen2-event-returns-v1', True))


def rows(db):
    """Each return's claim by dex number."""
    return {int(row['key']): row for row in ledger.rows(db, SOURCE)}


def earn(db, dexes, frame):
    """Open a claim for each of ``dexes`` at a walking milestone. One still open or delivered stays."""
    for dex in dexes:
        row = ledger.get(db, SOURCE, str(dex))
        if row is None or row['state'] not in (ledger.OPEN, ledger.DELIVERED):
            ledger.put(db, SOURCE, str(dex), ledger.OPEN, frame=frame, species=dex)


def deliver(db, dex, frame):
    """The encounter is in the cartridge from PlayClock ``frame`` on."""
    ledger.put(db, SOURCE, str(dex), ledger.DELIVERED, frame=frame, species=dex)


def consume(db, dex):
    """Close a delivered return in the same transaction as its verified capture receipt."""
    row = ledger.get(db, SOURCE, str(dex))
    if row and row['state'] == ledger.DELIVERED:
        ledger.put(db, SOURCE, str(dex), ledger.CONSUMED, frame=row['frame'], species=dex)


def decline(store, dex):
    """Close a delivered return the PC would not keep, until the next walking milestone."""
    from .progress_events import frame
    with store.transaction() as db:
        row = ledger.get(db, SOURCE, str(dex))
        if row and row['state'] == ledger.DELIVERED:
            ledger.put(db, SOURCE, str(dex), ledger.DECLINED, frame=frame(store), species=dex, reasons=REFUSED)


def claims(store):
    """The dex numbers whose return waits in the cartridge, and those closed until the next milestone."""
    with store.reading() as db:
        found = ledger.rows(db, SOURCE)
    ready = {int(row['key']) for row in found if row['state'] == ledger.DELIVERED}
    closed = {int(row['key']) for row in found if row['state'] in (ledger.CONSUMED, ledger.DECLINED)}
    return (ready if getattr(config, 'LEGENDARY_RETURN_STEPS', 1000000) else set()), closed


def adopt(db):
    """Move each kv ticket into a row once. A moved row has no frame, so a reload never reopens it."""
    from .state import kv
    for key in KEYS:
        value = kv.get(db, key)
        if not value or 'tickets' not in value:
            continue
        for dex, ticket in value.pop('tickets').items():
            if ledger.get(db, SOURCE, dex) is None:
                ledger.put(db, SOURCE, dex, STATES.get(ticket.get('state'), ledger.OPEN), species=int(dex))
        kv.put(db, key, value)


def events(db):
    """Each event return's claim by activity key."""
    return {row['key']: row for row in ledger.rows(db, EVENT)}


def mark(db, key, state, frame, dex=None, reasons=''):
    """Write an event claim's state at PlayClock ``frame``."""
    ledger.put(db, EVENT, key, state, frame=frame, species=dex, reasons=reasons)


def consume_event(db, key):
    """Close a delivered event return in the same transaction as its verified capture receipt."""
    row = ledger.get(db, EVENT, key)
    if row and row['state'] == ledger.DELIVERED:
        ledger.put(db, EVENT, key, ledger.CONSUMED, frame=row['frame'], species=row['species'])


def delivered(store):
    """The event claims whose flags wait cleared in the cartridge, by activity key."""
    with store.reading() as db:
        return {row['key']: row for row in ledger.rows(db, EVENT, ledger.DELIVERED)}


def adopt_events(db):
    """Move each event ticket's state into a row once, and keep the rest of it as the activity's clock.

    A ticket still walking after a return becomes consumed, and a skipped one declined. A moved row
    has no frame, so a reload never reopens it.
    """
    from .state import kv
    for key, notes in EVENT_KEYS:
        value = kv.get(db, key)
        if not value or 'tickets' not in value:
            continue
        clocks = value.setdefault('clocks', {})
        for name, ticket in value.pop('tickets').items():
            state, skipped = ticket.pop('state', 'walking'), ticket.pop('skipped', False)
            cycle = ticket.get('cycle', 0)
            claim = {'available': ledger.DELIVERED, 'caught': ledger.CONSUMED}.get(state)
            if state == 'walking':
                claim = ledger.DECLINED if skipped else ledger.CONSUMED if cycle else None
            if notes:
                # A capture the journal has not reported yet is reported on the next safe frame.
                ticket['noted'] = cycle - 1 if state == 'caught' else cycle
            clocks[name] = ticket
            if claim and ledger.get(db, EVENT, name) is None:
                ledger.put(db, EVENT, name, claim, species=ticket.get('dex'),
                           reasons=SKIPPED if claim == ledger.DECLINED else '')
        kv.put(db, key, value)
