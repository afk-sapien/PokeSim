"""Durable walking milestones and repeat legendary encounter claims."""
import json
import time

from . import config
from .catches import SUPPORTED
from .events import Event
from .legendary import ENCOUNTERS
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .strategy_data import DATA, EVENTS, SPECIES

KEY = 'legendary-returns-v1'
STEPS = 'cartridge-steps-v1'
STEP_ADDRESS = 0x05ED
STEP_SIGNATURE = bytes.fromhex('213bd135fa2cd7cb47280b213c')


def interval():
    return getattr(config, 'LEGENDARY_RETURN_STEPS', 1000000)


def status(store):
    walking = store.get(STEPS) or {}
    value = store.get(KEY) or {}
    every = interval()
    total = walking.get('total', 0)
    tickets = value.get('tickets', {})
    remaining = max(0, value.get('next_at', every) - total) if every else None
    return {'enabled': bool(every), 'available': walking.get('available', False),
            'steps': total, 'interval': every, 'progress': max(0, every - remaining) if every else 0,
            'remaining': remaining,
            'cycles': value.get('cycle', 0), 'started_at': walking.get('started_at'),
            'ready': [dex for dex, _, _, _ in ENCOUNTERS
                      if tickets.get(str(dex), {}).get('state') == 'available']}


class StepTracker:
    def __init__(self, store, rom_sha1):
        self.store = store
        self.supported = rom_sha1 in SUPPORTED
        self.value = store.get(STEPS) or {'total': 0, 'started_at': time.time()}
        self.value['available'] = self.supported
        self.last_flush = 0
        self.flush(force=True)

    def attach(self, pb):
        if not self.supported:
            return
        if bytes(pb.memory[0, STEP_ADDRESS:STEP_ADDRESS + len(STEP_SIGNATURE)]) != STEP_SIGNATURE:
            raise ValueError('Walking instruction signature does not match the verified cartridge')
        pb.hook_register(0, STEP_ADDRESS, self.completed, pb)

    def completed(self, pb):
        # This instruction runs once per completed, nonscripted walking tile.
        self.value['total'] += 1
        every = interval()
        if every and self.value['total'] % every == 0:
            self.flush(force=True)

    def flush(self, *, force=False):
        now = time.monotonic()
        if force or now - self.last_flush >= 30:
            self.store.set(STEPS, self.value)
            self.last_flush = now


def consume(db, dex):
    """Consume a return in the same transaction as its verified capture receipt."""
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    if not row:
        return
    value = json.loads(row[0])
    ticket = value.get('tickets', {}).get(str(dex))
    if ticket and ticket['state'] == 'available':
        ticket['state'] = 'caught'
        db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))


def claims(store):
    tickets = (store.get(KEY) or {}).get('tickets', {})
    ready = {int(dex) for dex, ticket in tickets.items() if ticket['state'] == 'available'}
    closed = {int(dex) for dex, ticket in tickets.items() if ticket['state'] == 'caught'}
    return (ready if interval() else set()), closed


def encounter_flags(memory, room, obj, flag, *, hidden):
    changed = False
    for base, bit in ((W_EVENT_FLAGS, EVENTS[flag]),
                     (W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj]))):
        address = base + bit // 8
        before = memory[address]
        memory[address] = before | (1 << (bit % 8)) if hidden else before & ~(1 << (bit % 8))
        changed |= memory[address] != before
    return changed


def observe(store, snapshot, memory):
    """Open one claim per milestone and reconcile spent claims after restores."""
    every = interval()
    if not snapshot.valid or not snapshot.started:
        return [], False
    steps = store.get(STEPS) or {}
    if not steps.get('available'):
        return [], False
    total = steps.get('total', 0)
    saved = store.get(KEY)
    value = saved or {'cycle': 0, 'tickets': {}, 'interval': every, 'next_at': every}
    updated = saved is None
    if not every:
        if value['interval'] != 0 or store.get(KEY) is None:
            value.update(interval=0, next_at=0)
            store.set(KEY, value)
        return [], False
    if value['interval'] != every:
        value.update(interval=every, next_at=total + every)
        updated = True
    if total >= value['next_at']:
        passed = 1 + (total - value['next_at']) // every
        cycle = value['cycle'] + passed
        value['next_at'] += passed * every
        for dex, _, _, _ in ENCOUNTERS:
            if dex in snapshot.owned or str(dex) in value['tickets']:
                ticket = value['tickets'].get(str(dex), {})
                value['tickets'][str(dex)] = {'cycle': cycle, 'state':
                    ticket['state'] if ticket.get('state') in ('pending', 'available') else 'pending'}
        value['cycle'] = cycle
        updated = True
    events, changed = [], False
    if not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu:
        for dex, room, obj, flag in ENCOUNTERS:
            ticket = value['tickets'].get(str(dex), {})
            if snapshot.map == room:
                continue
            if ticket.get('state') == 'pending':
                changed |= encounter_flags(memory, room, obj, flag, hidden=False)
                ticket['state'] = 'available'
                updated = True
                name = next(row['name'].title() for row in SPECIES.values() if row['dex'] == dex)
                events.append(Event('legendary_return', f'{name} has returned!',
                                    'A new expedition is available at its original home.', priority=4))
            elif ticket.get('state') == 'caught':
                # An older checkpoint cannot reopen a claim that was already caught.
                changed |= encounter_flags(memory, room, obj, flag, hidden=True)
    if updated:
        store.set(KEY, value)
    return events, changed
