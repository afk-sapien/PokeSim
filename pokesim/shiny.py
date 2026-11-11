"""Generation II shiny DVs, protection, and durable verified encounter receipts.

Red, Blue and Yellow keep their receipts under ``KEY``. Gold, Silver and Crystal keep theirs
apart under ``GEN2_KEY`` with their own table and the 251-species Pokédex.
"""
import hashlib
import time

from pokecore.gen1 import (W_ENEMY_BATTLE_STATUS3, W_ENEMY_DVS, W_ENEMY_MON, W_IS_IN_BATTLE,
                           WRAM_END, WRAM_START)

from .state import kv, tracking

KEY = 'shiny-statistics-v1'
GEN2_KEY = 'gen2-shiny-statistics-v1'
# generation: (kv key, receipt table, Pokédex size)
LEDGERS = {1: (KEY, tracking.SHINY_RECEIPTS[1], 151), 2: (GEN2_KEY, tracking.SHINY_RECEIPTS[2], 251)}
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
    """Open the ledger's counts. The receipt table comes from the schema version (pokesim.state)."""
    kv.add(db, LEDGERS[generation][0], empty())


def log(db, generation, names, limit=200):
    """The newest shinies seen and acquired, with their dates where known, oldest first. Receipts
    from before dates were kept stay undated."""
    rows = tracking.shiny_receipts(db, generation, limit)
    return [{'kind': kind, 'dex': dex, 'name': names.get(dex, f'#{dex:03d}'), 'ts': when}
            for kind, dex, when in reversed(rows)]


def record(db, kind, fingerprint, dex, *, generation=1):
    """Count one verified shiny once inside the caller transaction. Returns whether it was new."""
    key, _, size = LEDGERS[generation]
    if kind not in {'seen', 'acquired'} or type(dex) is not int or not 1 <= dex <= size:
        raise ValueError('Invalid shiny receipt')
    initialize(db, generation)
    if not tracking.add_shiny(db, generation, kind, fingerprint, dex, time.time()):
        return False
    value = {**empty(), **kv.get(db, key)}
    value[kind] += 1
    value[kind + '_species'] = sorted(set(value[kind + '_species']) | {dex})
    value['started_at'] = value['started_at'] or time.time()
    kv.update(db, key, value)
    return True


def start(db, generation, *, available, fresh=False):
    """Open a ledger for a cartridge that tracks shinies, keeping any receipts already counted."""
    key = LEDGERS[generation][0]
    initialize(db, generation)
    value = {**empty(), **kv.get(db, key)}
    if value['started_at'] is None:
        value['complete_history'] = fresh
    value.update(started_at=value['started_at'] or time.time(), available=available)
    kv.update(db, key, value)


def fresh(available):
    """The ledger of a new game, which counts every shiny it meets. A restart writes it."""
    return {**empty(), 'started_at': time.time(), 'available': available, 'complete_history': True}


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
        with store.transaction() as db:
            initialize(db)
            value = {**empty(), **kv.get(db, KEY)}
            value.update(started_at=value['started_at'] or time.time(), available=self.supported)
            kv.update(db, KEY, value)
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
        if mem[W_IS_IN_BATTLE] != 1 or mem[W_ENEMY_BATTLE_STATUS3] & 8:
            return
        species = mem[W_ENEMY_MON]
        if species not in SPECIES:
            return
        dvs = bytes(mem[W_ENEMY_DVS:W_ENEMY_DVS + 2])
        from . import progress_events
        progress_events.encounter(self.store, SPECIES[species]['dex'], dvs)
        if not shiny_bytes(dvs):
            return
        fingerprint = hashlib.sha256(bytes(mem[WRAM_START:WRAM_END])).hexdigest()
        with self.store.transaction() as db:
            record(db, 'seen', fingerprint, SPECIES[species]['dex'])
