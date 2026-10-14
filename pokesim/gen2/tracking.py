"""Durable captures and collection achievements for the 251-species cartridges."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import time

from .. import shiny
from .ram import Memory

CAPTURES = 'capture-statistics-v1'
MILESTONES = 'pokedex-milestones-v1'
HOOKS = {
    'gold': ((3, 27495, '21496ecd5e0ffa04'), (3, 27600, 'cdf13021496ecd5e')),
    'silver': ((3, 27493, '21476ecd5e0ffa04'), (3, 27598, 'cdf13021476ecd5e')),
    'crystal': ((3, 27384, '21f56dcd5710fa08'), (3, 27495, 'cde12f21f56dcd57')),
}


def encounter_hook(pb, data):
    """(bank, address) of BattleStartMessage.wild, where every wild battle checks for a shiny.

    The local label is not in the symbol table, so it is found from the ``jr z`` that the routine
    opens with and both instruction sequences are verified on the cartridge.
    """
    bank, address = data.symbols['BattleStartMessage']
    _, mode = data.symbols['wBattleMode']
    _, check = data.symbols['BattleCheckEnemyShininess']
    head = bytes(pb.memory[bank, address:address + 6])
    if head[:5] != bytes((0xFA, mode & 0xFF, mode >> 8, 0x3D, 0x28)):
        raise ValueError('The Gen II wild battle signature does not match the cartridge')
    wild = address + 6 + (head[5] ^ 0x80) - 0x80
    if bytes(pb.memory[bank, wild:wild + 4]) != bytes((0xCD, check & 0xFF, check >> 8, 0x30)):
        raise ValueError('The Gen II shiny check signature does not match the cartridge')
    return bank, wild


def empty_goals():
    return {'level_100': [], 'perfect_species': [], 'high_quality_species': [],
            'perfect_groups': {}, 'perfect_catches': 0}


@lru_cache(maxsize=1024)
def ancestors(data, species):
    family = {species}
    while True:
        parents = {sid for sid, row in data.species.items()
                   if any(evo['species'] in family for evo in row['evolutions'])}
        if parents <= family:
            return frozenset(family)
        family.update(parents)


def level_credit(data, species):
    return {species} if data.species[species]['evolutions'] else ancestors(data, species)


class Tracker:
    def __init__(self, store, data, *, fresh):
        self.store, self.data = store, data
        self.candidate = self.confirmed = None
        with store.lock, store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS capture_receipts '
                             '(fingerprint TEXT PRIMARY KEY, dex INTEGER NOT NULL, recorded_at REAL NOT NULL)')
            store.db.execute('INSERT OR IGNORE INTO kv VALUES (?, ?)', (CAPTURES, json.dumps({
                'counts': {}, 'total': 0, 'started_at': time.time(), 'complete_history': fresh, 'available': True})))
            shiny.start(store.db, 2, available=True, fresh=fresh)

    def reset(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM capture_receipts')
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (CAPTURES, json.dumps({
                'counts': {}, 'total': 0, 'started_at': time.time(), 'complete_history': True, 'available': True})))
            self.store.db.execute('DELETE FROM kv WHERE k=?', (MILESTONES,))
            shiny.clear(self.store.db, 2)
        self.candidate = self.confirmed = None

    def attach(self, pb):
        for bank, address, signature in HOOKS[self.data.game]:
            if bytes(pb.memory[bank, address:address + 8]).hex() != signature:
                raise ValueError('The Gen II capture completion signature does not match the cartridge')
            pb.hook_register(bank, address, self.captured, pb)
        pb.hook_register(*encounter_hook(pb, self.data), self.encountered, pb)

    def encountered(self, pb):
        """A wild battle opens. Count it once when the opponent is shiny."""
        mem = Memory(pb.memory, self.data)
        species = mem.byte('wEnemyMonSpecies')
        # The catching tutorial is the guide's battle and the debug battle is not an encounter.
        if (not 1 <= species <= 251 or mem.byte('wBattleMode') != 1 or mem.byte('wBattleType') in (2, 3)
                or not shiny.shiny_bytes(mem.read('wEnemyMonDVs', 2))):
            return
        fingerprint = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        with self.store.lock, self.store.db:
            shiny.record(self.store.db, 'seen', fingerprint, species, generation=2)

    def captured(self, pb):
        mem = Memory(pb.memory, self.data)
        species = mem.byte('wWildMon')
        if not 1 <= species <= 251 or mem.byte('wBattleMode') != 1 or mem.byte('wBattleType') in (2, 3, 6):
            return
        fingerprint = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        # The capture routine has already restored a transformed Ditto's own DVs here.
        dvs = mem.read('wEnemyMonDVs', 2)
        perfect = dvs == b'\xff\xff'
        with self.store.lock, self.store.db:
            db = self.store.db
            if not db.execute('INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
                              (fingerprint, species, time.time())).rowcount:
                return
            from .returns import consume
            consume(db, species)
            value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (CAPTURES,)).fetchone()[0])
            value['counts'][str(species)] = value['counts'].get(str(species), 0) + 1
            value['total'] += 1
            db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), CAPTURES))
            if shiny.shiny_bytes(dvs):
                shiny.record(db, 'acquired', fingerprint, species, generation=2)
            if perfect:
                row = db.execute('SELECT v FROM kv WHERE k=?', (MILESTONES,)).fetchone()
                goals = {**empty_goals(), **(json.loads(row[0]) if row else {})}
                goals['perfect_catches'] += 1
                goals['perfect_species'] = sorted(set(goals['perfect_species']) | {species})
                db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (MILESTONES, json.dumps(goals)))

    def observe(self, snapshot):
        if not snapshot.valid or not snapshot.started or self.store.get('trade_hold'):
            self.candidate = None
            return
        rows = snapshot.party + snapshot.stored
        token = tuple((mon.species, mon.level, mon.dvs, mon.trainer_id, mon.egg) for mon in rows)
        if token == self.confirmed:
            return
        if token != self.candidate:
            self.candidate = token
            return
        goals = {**empty_goals(), **(self.store.get(MILESTONES) or {})}
        maxed, perfect, quality = (set(goals[key]) for key in ('level_100', 'perfect_species', 'high_quality_species'))
        groups = Counter()
        for mon in rows:
            if mon.egg:
                continue
            if mon.level == 100:
                maxed.update(level_credit(self.data, mon.species))
            if sum(mon.dvs) >= 60:
                quality.add(mon.species)
            if sum(mon.dvs) == 75:
                perfect.add(mon.species)
                groups[f'{mon.trainer_id}:{min(ancestors(self.data, mon.species))}'] += 1
        for group, count in groups.items():
            goals['perfect_groups'][group] = max(count, goals['perfect_groups'].get(group, 0))
        goals.update(level_100=sorted(maxed), perfect_species=sorted(perfect), high_quality_species=sorted(quality))
        self.store.set(MILESTONES, goals)
        self.confirmed = token


def apply(payload, store):
    goals = {**empty_goals(), **(store.get(MILESTONES) or {})}
    groups = goals.pop('perfect_groups')
    held = [mon for mon in payload['party'] + (payload.get('storage') or {}).get('pokemon', []) if not mon.get('egg')]
    goals.update(perfect_found=max(goals['perfect_catches'], sum(groups.values())), perfect_count_is_minimum=True,
                 perfect_held=sum(mon.get('dv_total') == 75 for mon in held),
                 three_star_held=sum(mon.get('dv_stars') == 3 for mon in held))
    return {**payload, 'milestones': goals, 'catches': store.get(CAPTURES) or {'available': False}}
