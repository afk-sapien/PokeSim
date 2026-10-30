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


def _dated(db, table):
    return 'ts' in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def initialize(db, generation=1):
    key, table, _ = LEDGERS[generation]
    db.execute(f'CREATE TABLE IF NOT EXISTS {table} '
               '(kind TEXT NOT NULL, fingerprint TEXT NOT NULL, dex INTEGER NOT NULL, '
               'PRIMARY KEY(kind,fingerprint))')
    if not _dated(db, table):
        # Receipts from before dates were kept stay undated. Their dates are never guessed.
        db.execute(f'ALTER TABLE {table} ADD COLUMN ts REAL')
    db.execute('INSERT OR IGNORE INTO kv VALUES (?, ?)', (key, json.dumps(empty())))


def log(db, generation, names, limit=200):
    """The newest shinies seen and acquired, with their dates where known, oldest first."""
    _, table, _ = LEDGERS[generation]
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    ts = 'ts' if _dated(db, table) else 'NULL'
    rows = db.execute(f'SELECT kind, dex, {ts} FROM {table} ORDER BY {ts} IS NOT NULL DESC, {ts} DESC, rowid DESC '
                      'LIMIT ?', (limit,)).fetchall()
    return [{'kind': kind, 'dex': dex, 'name': names.get(dex, f'#{dex:03d}'), 'ts': when}
            for kind, dex, when in reversed(rows)]


def record(db, kind, fingerprint, dex, *, generation=1):
    """Count one verified shiny once inside the caller transaction. Returns whether it was new."""
    key, table, size = LEDGERS[generation]
    if kind not in {'seen', 'acquired'} or type(dex) is not int or not 1 <= dex <= size:
        raise ValueError('Invalid shiny receipt')
    initialize(db, generation)
    if not db.execute(f'INSERT OR IGNORE INTO {table}(kind, fingerprint, dex, ts) VALUES (?,?,?,?)',
                      (kind, fingerprint, dex, time.time())).rowcount:
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


def store_dvs(pb, signature):
    """The bank 15 address right after storeDVs writes both wild DV bytes."""
    bank = bytes(pb.memory[BANK, 0x4000:0x7fff])
    if bank.count(signature) != 1:
        raise ValueError('Shiny encounter tracking does not match the verified cartridge')
    return 0x4000 + bank.index(signature) + 5


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
        from . import fair_dvs
        # The reroll shares this hook so it lands before CalcStats and before the shiny check.
        self.fair_key = fair_dvs.secret(store) if self.supported and fair_dvs.enabled() else None

    def attach(self, pb):
        if not self.supported:
            return
        pb.hook_register(BANK, store_dvs(pb, getattr(self, 'signature', SIGNATURE)), self.encounter, pb)

    def encounter(self, pb):
        from .strategy_data import SPECIES
        mem = pb.memory
        if getattr(self, 'fair_key', None):
            from .fair_dvs import reroll
            reroll(mem, self.fair_key)
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
