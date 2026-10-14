"""Generation II shiny DVs, protection, and durable verified encounter receipts.

Red, Blue and Yellow keep their receipts under ``KEY``. Gold, Silver and Crystal keep theirs
apart under ``GEN2_KEY`` with their own table and the 251-species Pokédex.
"""
import hashlib
import json
import time

KEY = 'shiny-statistics-v1'
GEN2_KEY = 'gen2-shiny-statistics-v1'
# generation: (kv key, receipt table, Pokédex size)
LEDGERS = {1: (KEY, 'shiny_receipts', 151), 2: (GEN2_KEY, 'gen2_shiny_receipts', 251)}
# LoadEnemyMonData.storeDVs writes both DV bytes before loading the enemy level.
# Scan only the verified English Red/Blue bank, then verify the complete instruction sequence.
BANK = 15
SIGNATURE = bytes.fromhex('21f1cf227011f3cffa27d112')
YELLOW_SIGNATURE = bytes.fromhex('21f0cf227011f2cffa26d112')


def shiny_bytes(raw):
    return len(raw) == 2 and raw[0] & 0x2f == 0x2a and raw[1] == 0xaa


def is_shiny(mon):
    dvs = mon.get('dvs', ())
    return (isinstance(dvs, (tuple, list)) and len(dvs) == 5
            and all(type(v) is int and 0 <= v <= 15 for v in dvs)
            and bool(dvs[1] & 2) and dvs[2:] in ([10, 10, 10], (10, 10, 10)))


def empty():
    return {'seen': 0, 'acquired': 0, 'seen_species': [], 'acquired_species': [],
            'started_at': None, 'available': False, 'complete_history': False}


def status(store, generation=1):
    return {**empty(), **(store.get(LEDGERS[generation][0]) or {})}


def initialize(db, generation=1):
    key, table, _ = LEDGERS[generation]
    db.execute(f'CREATE TABLE IF NOT EXISTS {table} '
               '(kind TEXT NOT NULL, fingerprint TEXT NOT NULL, dex INTEGER NOT NULL, '
               'PRIMARY KEY(kind,fingerprint))')
    db.execute('INSERT OR IGNORE INTO kv VALUES (?, ?)', (key, json.dumps(empty())))


def record(db, kind, fingerprint, dex, *, generation=1):
    """Count one verified shiny once inside the caller transaction. Returns whether it was new."""
    key, table, size = LEDGERS[generation]
    if kind not in {'seen', 'acquired'} or type(dex) is not int or not 1 <= dex <= size:
        raise ValueError('Invalid shiny receipt')
    initialize(db, generation)
    if not db.execute(f'INSERT OR IGNORE INTO {table} VALUES (?,?,?)', (kind, fingerprint, dex)).rowcount:
        return False
    value = {**empty(), **json.loads(db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()[0])}
    value[kind] += 1
    value[kind + '_species'] = sorted(set(value[kind + '_species']) | {dex})
    value['started_at'] = value['started_at'] or time.time()
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), key))
    return True


def start(db, generation, *, available, fresh=False):
    """Open a ledger for a cartridge that tracks shinies, keeping any receipts already counted."""
    key = LEDGERS[generation][0]
    initialize(db, generation)
    value = {**empty(), **json.loads(db.execute('SELECT v FROM kv WHERE k=?', (key,)).fetchone()[0])}
    if value['started_at'] is None:
        value['complete_history'] = fresh
    value.update(started_at=value['started_at'] or time.time(), available=available)
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), key))


def clear(db, generation):
    """Forget every receipt when the adventure restarts from a new game."""
    key, table, _ = LEDGERS[generation]
    initialize(db, generation)
    db.execute(f'DELETE FROM {table}')
    value = {**empty(), 'started_at': time.time(), 'available': True, 'complete_history': True}
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), key))


class ShinyTracker:
    def __init__(self, store, rom_sha1):
        from .catches import TRACKED, YELLOW
        self.store = store
        self.signature = YELLOW_SIGNATURE if rom_sha1 == YELLOW else SIGNATURE
        self.supported = rom_sha1 in TRACKED
        with store.lock, store.db:
            initialize(store.db)
            value = {**empty(), **json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])}
            value.update(started_at=value['started_at'] or time.time(), available=self.supported)
            store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))

    def attach(self, pb):
        if not self.supported:
            return
        bank = bytes(pb.memory[BANK, 0x4000:0x7fff])
        signature = getattr(self, 'signature', SIGNATURE)
        if bank.count(signature) != 1:
            raise ValueError('Shiny encounter tracking does not match the verified cartridge')
        pb.hook_register(BANK, 0x4000 + bank.index(signature) + 5, self.encounter, pb)

    def encounter(self, pb):
        from .strategy_data import SPECIES
        mem = pb.memory
        # Trainer battles and Transform do not create wild encounters.
        if mem[0xd057] != 1 or mem[0xd069] & 8 or not shiny_bytes(bytes(mem[0xcff1:0xcff3])):
            return
        species = mem[0xcfe5]
        if species not in SPECIES:
            return
        fingerprint = hashlib.sha256(bytes(mem[0xc000:0xe000])).hexdigest()
        with self.store.lock, self.store.db:
            record(self.store.db, 'seen', fingerprint, SPECIES[species]['dex'])

    def reset(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM shiny_receipts')
            value = {**empty(), 'started_at': time.time(), 'available': self.supported, 'complete_history': True}
            self.store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))
