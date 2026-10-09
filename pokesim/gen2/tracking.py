"""Durable captures and collection achievements for the 251-species cartridges."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import time

from .ram import Memory

CAPTURES = 'capture-statistics-v1'
MILESTONES = 'pokedex-milestones-v1'
HOOKS = {
    'gold': ((3, 27495, '21496ecd5e0ffa04'), (3, 27600, 'cdf13021496ecd5e')),
    'silver': ((3, 27493, '21476ecd5e0ffa04'), (3, 27598, 'cdf13021476ecd5e')),
    'crystal': ((3, 27384, '21f56dcd5710fa08'), (3, 27495, 'cde12f21f56dcd57')),
}


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

    def reset(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM capture_receipts')
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (CAPTURES, json.dumps({
                'counts': {}, 'total': 0, 'started_at': time.time(), 'complete_history': True, 'available': True})))
            self.store.db.execute('DELETE FROM kv WHERE k=?', (MILESTONES,))
        self.candidate = self.confirmed = None

    def attach(self, pb):
        for bank, address, signature in HOOKS[self.data.game]:
            if bytes(pb.memory[bank, address:address + 8]).hex() != signature:
                raise ValueError('The Gen II capture completion signature does not match the cartridge')
            pb.hook_register(bank, address, self.captured, pb)

    def captured(self, pb):
        mem = Memory(pb.memory, self.data)
        species = mem.byte('wWildMon')
        if not 1 <= species <= 251 or mem.byte('wBattleMode') != 1 or mem.byte('wBattleType') in (2, 3, 6):
            return
        fingerprint = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        perfect = mem.read('wEnemyMonDVs', 2) == b'\xff\xff'
        with self.store.lock, self.store.db:
            db = self.store.db
            if not db.execute('INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
                              (fingerprint, species, time.time())).rowcount:
                return
            value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (CAPTURES,)).fetchone()[0])
            value['counts'][str(species)] = value['counts'].get(str(species), 0) + 1
            value['total'] += 1
            db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), CAPTURES))
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
