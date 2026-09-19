"""Durable capture receipts from verified cartridge capture completion."""
from __future__ import annotations

import hashlib
import json
import time

KEY = 'capture-statistics-v1'
SUPPORTED = {
    'ea9bcae617fdf159b045185467ae58b2e4a48b9a',
    'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2',
}
BANK, ADDRESS = 3, 0x5928
SIGNATURE = bytes.fromhex('fa5ad0a7c0211dd3')


def status(store):
    return store.get(KEY) or {'counts': {}, 'total': 0, 'started_at': None,
                              'complete_history': False, 'available': False}


class CatchTracker:
    def __init__(self, store, rom_sha1, *, fresh=False):
        self.store = store
        self.supported = rom_sha1 in SUPPORTED
        with store.lock, store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS capture_receipts '
                             '(fingerprint TEXT PRIMARY KEY, dex INTEGER NOT NULL, recorded_at REAL NOT NULL)')
            row = store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
            value = json.loads(row[0]) if row else self.empty(fresh)
            value['available'] = self.supported
            store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))

    def empty(self, fresh):
        return {'counts': {}, 'total': 0, 'started_at': time.time(),
                'complete_history': fresh, 'available': self.supported}

    def reset(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM capture_receipts')
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)',
                                 (KEY, json.dumps(self.empty(True))))

    def attach(self, pb):
        if not self.supported:
            return
        if bytes(pb.memory[BANK, ADDRESS:ADDRESS + len(SIGNATURE)]) != SIGNATURE:
            raise ValueError('Capture tracking instruction signature does not match the verified cartridge')
        pb.hook_register(BANK, ADDRESS, self.completed, pb)

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
        self.record(fingerprint, dex, perfect=bytes(memory[0xcff1:0xcff3]) == b'\xff\xff',
                    species=species, trainer_id=int.from_bytes(bytes(memory[0xd359:0xd35b]), 'big'))

    def record(self, fingerprint, dex, *, perfect=False, species=None, trainer_id=None):
        if not 1 <= dex <= 151:
            raise ValueError('Capture has an invalid Pokédex number')
        with self.store.lock, self.store.db:
            inserted = self.store.db.execute('INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
                                            (fingerprint, dex, time.time())).rowcount
            if not inserted:
                return
            value = json.loads(self.store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
            key = str(dex)
            value['counts'][key] = value['counts'].get(key, 0) + 1
            value['total'] += 1
            if perfect:
                from .milestones import record_capture
                record_capture(self.store.db, species, trainer_id)
            self.store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))
