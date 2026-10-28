"""Durable captures and collection achievements for the 251-species cartridges."""
from collections import Counter
import hashlib
import json
import time

from .. import shiny
from pokecore.gen2.hooks import capture_hooks, contest_hook, encounter_hook, hatch_hook
from pokecore.gen2.ram import Memory

CAPTURES = 'capture-statistics-v1'
MILESTONES = 'pokedex-milestones-v1'
EGG = 0xFD


def empty_goals():
    return {'level_100': [], 'perfect_species': [], 'high_quality_species': [],
            'perfect_groups': {}, 'perfect_catches': 0}


def data_cache(data, name):
    """A cache that lives and dies with one loaded copy of the game data.

    Gen I workers load a fresh copy for each Time Capsule trade, and caches keyed by the copy
    kept every one of them alive (issue #111).
    """
    return vars(data).setdefault(name, {})


def ancestors(data, species):
    cache = data_cache(data, '_ancestors')
    if species not in cache:
        family = {species}
        while True:
            parents = {sid for sid, row in data.species.items()
                       if any(evo['species'] in family for evo in row['evolutions'])}
            if parents <= family:
                break
            family.update(parents)
        cache[species] = frozenset(family)
    return cache[species]


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
        for bank, address in capture_hooks(pb.memory, self.data):
            pb.hook_register(bank, address, self.captured, pb)
        pb.hook_register(*encounter_hook(pb.memory, self.data), self.encountered, pb)
        pb.hook_register(*contest_hook(pb.memory, self.data), self.contest_caught, pb)
        pb.hook_register(*contest_keep_hook(pb.memory, self.data), self.contest_kept, pb)
        pb.hook_register(*hatch_hook(pb.memory, self.data), self.hatching, pb)

    def hatching(self, pb):
        """The overworld is about to hatch Eggs. Count each shiny one as acquired, once.

        HatchEggs hatches every party Egg whose cycle count (the happiness byte) is zero. The
        fingerprint is the RAM at this call plus the slot, so a reload that replays it counts nothing.
        """
        mem = Memory(pb.memory, self.data)
        species = mem.read('wPartySpecies', 6)
        hatching = []
        for slot, kind in enumerate(species):
            if kind == 0xFF:
                break
            raw = mem.read('wPartyMons', 48, slot * 48)
            if kind == EGG and not raw[27] and 1 <= raw[0] <= 251 and shiny.shiny_bytes(raw[21:23]):
                hatching.append((slot, raw[0]))
        if not hatching:
            return
        ram = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        with self.store.lock, self.store.db:
            for slot, dex in hatching:
                shiny.record(self.store.db, 'acquired', f'hatch:{slot}:{ram}', dex, generation=2)

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

    def contest_caught(self, pb):
        """A Bug-Catching Contest catch is kept. Count a shiny one as acquired, once."""
        mem = Memory(pb.memory, self.data)
        species = mem.byte('wEnemyMonSpecies')
        if (not 1 <= species <= 251 or mem.byte('wBattleMode') != 1 or mem.byte('wBattleType') != 6
                or not shiny.shiny_bytes(mem.read('wEnemyMonDVs', 2))):
            return
        fingerprint = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        with self.store.lock, self.store.db:
            shiny.record(self.store.db, 'acquired', fingerprint, species, generation=2)

    def contest_kept(self, pb):
        """The contest is over and the Pokémon the player held at the end goes to the party or box.

        Count it toward caught once, as a receipt of its own. Catches the player let go for a
        later one never reach this point.
        """
        species = Memory(pb.memory, self.data).byte('wContestMonSpecies')
        if not 1 <= species <= 251:
            return
        fingerprint = 'contest:' + hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).hexdigest()
        with self.store.lock, self.store.db:
            db = self.store.db
            if not db.execute('INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
                              (fingerprint, species, time.time())).rowcount:
                return
            from ..activity_ledger import increment
            increment(db, 'caught', species)
            value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (CAPTURES,)).fetchone()[0])
            value['counts'][str(species)] = value['counts'].get(str(species), 0) + 1
            value['total'] += 1
            db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), CAPTURES))

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
            from ..activity_ledger import increment
            increment(db, 'caught', species)
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
        from .. import progress
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (MILESTONES, json.dumps(goals)))
            # The progress lines for level 100 species and perfect finds follow each change.
            progress.goals_changed(self.store.db, time.time())
        self.confirmed = token


def contest_keep_hook(memory, data):
    """(bank, address) of CheckPartyFullAfterContest, checked against its opening
    ``ld a, [wContestMonSpecies] / and a / jp z``. ValueError on a mismatch."""
    bank, address = data.symbols['CheckPartyFullAfterContest']
    species = data.symbols['wContestMonSpecies'][1]
    signature = bytes((0xFA, species & 0xFF, species >> 8, 0xA7, 0xCA))
    if bytes(memory[bank, address:address + len(signature)]) != signature:
        raise ValueError('Gen II contest keep signature mismatch')
    return bank, address


def record_gift(db, event_id, species):
    """Count a committed custom gift toward Total caught, as Red, Blue and Yellow do.

    Keyed by its journal entry, so the recent catch counts date it the same way."""
    row = db.execute('SELECT v FROM kv WHERE k=?', (CAPTURES,)).fetchone()
    if row is None or not 1 <= species <= 251 or not db.execute(
            'INSERT OR IGNORE INTO capture_receipts VALUES (?, ?, ?)',
            (f'gift-event:{event_id}', species, time.time())).rowcount:
        return
    value = json.loads(row[0])
    value['counts'][str(species)] = value['counts'].get(str(species), 0) + 1
    value['total'] += 1
    db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), CAPTURES))


def apply(payload, store, data=None):
    goals = {**empty_goals(), **(store.get(MILESTONES) or {})}
    groups = goals.pop('perfect_groups')
    held = [mon for mon in payload['party'] + (payload.get('storage') or {}).get('pokemon', []) if not mon.get('egg')]
    goals.update(perfect_found=max(goals['perfect_catches'], sum(groups.values())), perfect_count_is_minimum=True,
                 perfect_held=sum(mon.get('dv_total') == 75 for mon in held),
                 three_star_held=sum(mon.get('dv_stars') == 3 for mon in held))
    # The Pokédex marks shiny species as Red, Blue and Yellow do: acquired or held now, with final
    # evolutions crediting earlier forms. Seen-only species carry their own marker.
    shinies = shiny.status(store, 2)
    shinies['held'] = sum(bool(mon.get('shiny')) for mon in held)
    shinies['held_species'] = sorted({mon['dex'] for mon in held if mon.get('shiny') and mon.get('dex')})
    found = set(shinies['acquired_species']) | set(shinies['held_species'])
    shinies['collection_species'] = sorted({dex for species in found
                                            for dex in (level_credit(data, species) if data else {species})})
    return {**payload, 'milestones': goals, 'catches': store.get(CAPTURES) or {'available': False}, 'shiny': shinies}
