"""Durable walking milestones and repeat legendary encounter claims.

The kv value keeps the walking clock: the milestones passed and the step count of the next one.
Each return is a ``legendary`` row in the claims ledger (return_claims).
"""
import time
from pokecore.resets import Flag, update_flags

from . import config, return_claims
from .catches import TRACKED, YELLOW, site
from .events import Event
from .legendary import ENCOUNTERS
from .ram import W_EVENT_FLAGS, W_TOGGLE_OBJECT_FLAGS
from .state import claims as ledger, kv
from .strategy_data import DATA, EVENTS, SPECIES

KEY = 'legendary-returns-v1'
STEPS = 'cartridge-steps-v1'
STEP_ADDRESS = 0x05ED
STEP_SIGNATURE = bytes.fromhex('213bd135fa2cd7cb47280b213c')
STEP = {YELLOW: (0x045E, bytes.fromhex('213ad135fa2bd7cb47280b213b'))}


def interval():
    return getattr(config, 'LEGENDARY_RETURN_STEPS', 1000000)


def status(store):
    walking = store.get(STEPS) or {}
    value = store.get(KEY) or {}
    every = interval()
    total = walking.get('total', 0)
    ready, _ = claims(store)
    remaining = max(0, value.get('next_at', every) - total) if every else None
    return {'enabled': bool(every), 'available': walking.get('available', False),
            'steps': total, 'interval': every, 'progress': max(0, every - remaining) if every else 0,
            'remaining': remaining,
            'cycles': value.get('cycle', 0), 'started_at': walking.get('started_at'),
            'ready': [dex for dex, _, _, _ in ENCOUNTERS if dex in ready]}


class StepTracker:
    def __init__(self, store, rom_sha1):
        self.store = store
        self.rom_sha1 = rom_sha1
        self.supported = rom_sha1 in TRACKED
        self.value = store.get(STEPS) or {'total': 0, 'started_at': time.time()}
        self.value['available'] = self.supported
        self.last_flush = 0
        self.flush(force=True)

    def attach(self, pb):
        if not self.supported:
            return
        address, signature = site(STEP, getattr(self, 'rom_sha1', None), (STEP_ADDRESS, STEP_SIGNATURE))
        if bytes(pb.memory[0, address:address + len(signature)]) != signature:
            raise ValueError('Walking instruction signature does not match the verified cartridge')
        pb.hook_register(0, address, self.completed, pb)

    def completed(self, pb):
        # This instruction runs once per completed, nonscripted walking tile.
        self.value['total'] += 1
        intervals = (interval(), getattr(config, 'EVENT_RETURN_STEPS', 100000),
                     getattr(config, 'MEW_RETURN_STEPS', 1000000))
        if any(every and self.value['total'] % every == 0 for every in intervals):
            self.flush(force=True)

    def flush(self, *, force=False):
        now = time.monotonic()
        if force or now - self.last_flush >= 30:
            self.store.set(STEPS, self.value)
            self.last_flush = now


consume, decline, claims = return_claims.consume, return_claims.decline, return_claims.claims


def encounter_flags(memory, room, obj, flag, *, hidden):
    return bool(update_flags(memory, (
        (Flag(W_EVENT_FLAGS, EVENTS[flag]), hidden),
        (Flag(W_TOGGLE_OBJECT_FLAGS, DATA['toggle_objects'].index([room, obj])), hidden),
    )))


def observe(store, snapshot, memory):
    """Open one claim per milestone and reconcile spent claims after restores."""
    from .progress_events import frame
    every = interval()
    if not snapshot.valid or not snapshot.started:
        return [], False
    steps = store.get(STEPS) or {}
    if not steps.get('available'):
        return [], False
    total = steps.get('total', 0)
    saved = store.get(KEY)
    value = saved or {'cycle': 0, 'interval': every, 'next_at': every}
    updated = saved is None
    if not every:
        if value['interval'] != 0 or store.get(KEY) is None:
            value.update(interval=0, next_at=0)
            store.set(KEY, value)
        return [], False
    if value['interval'] != every:
        value.update(interval=every, next_at=total + every)
        updated = True
    events, changed, now = [], False, frame(store)
    with store.transaction() as db:
        found = return_claims.rows(db)
        if total >= value['next_at']:
            passed = 1 + (total - value['next_at']) // every
            value['cycle'] += passed
            value['next_at'] += passed * every
            return_claims.earn(db, [dex for dex, _, _, _ in ENCOUNTERS if dex in snapshot.owned or dex in found], now)
            found = return_claims.rows(db)
            updated = True
        if not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu:
            for dex, room, obj, flag in ENCOUNTERS:
                row = found.get(dex)
                if row is None or snapshot.map == room:
                    continue
                if row['state'] == ledger.OPEN:
                    changed |= encounter_flags(memory, room, obj, flag, hidden=False)
                    return_claims.deliver(db, dex, now)
                    if row['reasons'] != ledger.RELOADED:
                        name = next(entry['name'].title() for entry in SPECIES.values() if entry['dex'] == dex)
                        events.append(Event('legendary_return', f'{name} has returned!',
                                            'A new expedition is available at its original home.', priority=4))
                elif row['state'] in (ledger.CONSUMED, ledger.DECLINED):
                    # An older checkpoint cannot reopen a claim that was already caught or declined.
                    changed |= encounter_flags(memory, room, obj, flag, hidden=True)
        if updated:
            kv.put(db, KEY, value)
    return events, changed
