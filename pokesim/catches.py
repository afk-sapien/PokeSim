"""Durable catch bookkeeping for cartridge captures and committed custom gifts."""
from __future__ import annotations

import hashlib
import re
import time

from . import progress_events
from .state import kv, tracking

KEY = 'capture-statistics-v1'
SUPPORTED = {
    'ea9bcae617fdf159b045185467ae58b2e4a48b9a',
    'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2',
}
YELLOW = 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'
# Every cartridge whose instruction sites below are verified. Yellow keeps the
# same routines one WRAM byte lower, so its operands and addresses differ.
TRACKED = SUPPORTED | {YELLOW}
BANK, ADDRESS = 3, 0x5928
SIGNATURE = bytes.fromhex('fa5ad0a7c0211dd3')
# ItemUseBall.done per cartridge, from pret/pokered and pret/pokeyellow symbols.
CAPTURE = {YELLOW: (3, 0x5687, bytes.fromhex('fa59d0a7c0211cd3'))}


def site(table, rom_sha1, default):
    return table.get(rom_sha1, default)


def status(store):
    return store.get(KEY) or {'counts': {}, 'total': 0, 'started_at': None,
                              'complete_history': False, 'available': False}


class CatchTracker:
    def __init__(self, store, rom_sha1, *, fresh=False):
        self.store = store
        self.rom_sha1 = rom_sha1
        self.supported = rom_sha1 in TRACKED
        with store.transaction() as db:
            value = kv.get(db, KEY, self.empty(fresh))
            initialize(db)
            value['available'] = self.supported
            kv.put(db, KEY, value)
            backfill_gifts(db)

    def empty(self, fresh):
        return {'counts': {}, 'total': 0, 'started_at': time.time(),
                'complete_history': fresh, 'available': self.supported}

    def attach(self, pb):
        if not self.supported:
            return
        bank, address, signature = site(CAPTURE, getattr(self, 'rom_sha1', None), (BANK, ADDRESS, SIGNATURE))
        if bytes(pb.memory[bank, address:address + len(signature)]) != signature:
            raise ValueError('Capture tracking instruction signature does not match the verified cartridge')
        pb.hook_register(bank, address, self.completed, pb)

    def completed(self, pb):
        from .strategy_data import SPECIES
        memory = pb.memory
        species = memory[0xd11c]
        if memory[0xd057] != 1 or memory[0xd05a] == 1 or species not in SPECIES:
            return
        dex = SPECIES[species]['dex']
        # Re-entering the exact saved capture completion must not count twice.
        # WRAM includes the individual, destination, game clock and random state.
        fingerprint = hashlib.sha256(bytes(memory[0xc000:0xe000])).hexdigest()
        from .shiny import shiny_bytes
        dvs = bytes(memory[0xcff1:0xcff3])
        trainer_id = int.from_bytes(bytes(memory[0xd359:0xd35b]), 'big')
        self.record(fingerprint, dex, shiny=shiny_bytes(dvs), perfect=dvs == b'\xff\xff',
                    species=species, trainer_id=trainer_id, identity=progress_events.identity(trainer_id, dvs, dex),
                    dvs=dvs)

    def record(self, fingerprint, dex, *, perfect=False, shiny=False, species=None, trainer_id=None, identity=None,
               dvs=None):
        with self.store.transaction() as db:
            new = record_receipt(db, fingerprint, dex, perfect=perfect, shiny=shiny,
                                 species=species, trainer_id=trainer_id, frame=progress_events.frame(self.store),
                                 identity=identity)
            if new and dvs is not None:
                progress_events.improved(self.store, db, dex, dvs, identity)


def record_receipt(db, fingerprint, dex, *, perfect=False, shiny=False, species=None, trainer_id=None,
                   frame=None, identity=None, progress=True):
    """Record once inside the caller transaction, and say whether the receipt was new.

    A new receipt also writes its progress row, a ``receive`` for a custom gift and a ``catch``
    otherwise. ``progress`` False skips it for a gift found again in an older journal.
    """
    if not 1 <= dex <= 151:
        raise ValueError('Capture has an invalid Pokédex number')
    if not tracking.add_capture(db, fingerprint, dex, time.time()):
        return False
    if progress:
        progress_events.record(db, 'receive' if fingerprint.startswith('gift-event:') else 'catch',
                               frame=frame, species=dex, identity=identity)
    from .activity_ledger import increment
    increment(db, 'gift' if fingerprint.startswith('gift-event:') else 'caught', dex)
    value = kv.get(db, KEY)
    key = str(dex)
    value['counts'][key] = value['counts'].get(key, 0) + 1
    value['total'] += 1
    if dex in (144, 145, 146, 150):
        from .legendary_returns import consume
        consume(db, dex)
    if shiny:
        from .shiny import record
        record(db, 'acquired', fingerprint, dex)
    if perfect:
        from .milestones import record_capture
        record_capture(db, species, trainer_id)
    kv.update(db, KEY, value)
    return True


def initialize(db):
    """Open the catch counts. The receipt table comes from the schema version (pokesim.state)."""
    kv.add(db, KEY, {'counts': {}, 'total': 0, 'started_at': time.time(),
                     'complete_history': False, 'available': False})


def record_gift(db, event_id, species, slot=None, *, frame=None, progress=True):
    """Count a committed custom gift using its durable journal identity."""
    from .strategy_data import SPECIES
    initialize(db)
    from .shiny import shiny_bytes
    dex = SPECIES[species]['dex']
    trainer_id = int.from_bytes(slot.struct[12:14], 'big') if slot else None
    record_receipt(db, f'gift-event:{event_id}', dex,
                   shiny=bool(slot and shiny_bytes(slot.struct[27:29])),
                   perfect=bool(slot and slot.struct[27:29] == bytes((255, 255))),
                   species=species, trainer_id=trainer_id, frame=frame, progress=progress,
                   identity=progress_events.identity(trainer_id, slot.struct[27:29], dex) if slot else None)


def backfill_gifts(db):
    """Recover verified journal gifts once, without guessing from current ownership."""
    from .strategy_data import SPECIES
    marker = 'capture-gift-backfill-v1'
    if kv.exists(db, marker):
        return
    names = {mon['name'].casefold(): sid for sid, mon in SPECIES.items()}
    for event_id, title in tracking.obtained(db):
        match = re.fullmatch(r'Received .+ \(([^()]+)\) for League reward #\d+', title)
        if not match:
            match = re.fullmatch(r'Received (.+) for Championship #\d+', title)
        species = names.get(match[1].casefold()) if match else None
        if title in ('Received Mew from the custom PokeSim event',
                     'Received Mew for defeating the final rival'):
            species = names.get('mew')
        if species is not None:
            record_gift(db, event_id, species, progress=False)
    kv.put(db, marker, True)
