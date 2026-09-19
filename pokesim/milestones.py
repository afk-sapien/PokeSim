"""Durable Pokédex goals, independent of emulator checkpoints and box positions."""
from collections import Counter
from dataclasses import asdict
from functools import lru_cache
import json

from .game_data import load
from .pokemon import dv_rating
from .strategy_data import SPECIES

KEY = 'pokedex-milestones-v1'


def is_perfect(mon):
    dvs = mon.get('dvs')
    return isinstance(dvs, (list, tuple)) and len(dvs) == 5 and all(
        type(value) is int and value == 15 for value in dvs)


@lru_cache(maxsize=1)
def evolution_graph():
    return {int(sid): [row['species'] for row in rows]
            for sid, rows in load('collection.json')['evolutions'].items()}


def ancestors(species):
    family = {species}
    while True:
        parents = {sid for sid, children in evolution_graph().items() if family.intersection(children)}
        if parents <= family:
            return family
        family.update(parents)


def level_credit(species):
    """A terminal evolution credits its ancestors, never its sibling branches."""
    family = {species} if evolution_graph().get(species) else ancestors(species)
    return {SPECIES[sid]['dex'] for sid in family if sid in SPECIES}


def perfect_group(mon):
    # Evolution and nicknames cannot manufacture extra individual discoveries.
    roots = [sid for sid in ancestors(mon['species'])
             if not any(sid in children for children in evolution_graph().values())]
    return f"{mon.get('trainer_id')}:{min(roots)}"


def empty():
    return {'level_100': [], 'perfect_species': [], 'high_quality_species': [],
            'perfect_groups': {}, 'perfect_catches': 0}


def status(store):
    value = {**empty(), **(store.get(KEY) or {})}
    value['high_quality_species'] = sorted(set(value['high_quality_species']) | set(value['perfect_species']))
    return {**value, 'perfect_found': sum(value['perfect_groups'].values()),
            'perfect_count_is_minimum': True}


def record_capture(db, species, trainer_id):
    """Called in the same transaction as a new verified perfect capture receipt."""
    row = db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
    value = json.loads(row[0]) if row else empty()
    group = perfect_group({'species': species, 'trainer_id': trainer_id})
    value['perfect_groups'][group] = value['perfect_groups'].get(group, 0) + 1
    value['perfect_catches'] += 1
    value['perfect_species'] = sorted(set(value['perfect_species']) | {SPECIES[species]['dex']})
    db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))


class MilestoneTracker:
    def __init__(self, store):
        self.store = store
        self.previous = None
        self.confirmed = None

    def reset(self):
        self.store.set(KEY, empty())
        self.previous = self.confirmed = None

    def observe(self, snapshot):
        if not snapshot.started or not snapshot.valid or self.store.get('trade_hold'):
            self.previous = None
            return
        rows = [asdict(mon) for mon in snapshot.party] + snapshot.storage_entries()
        maxed = set()
        perfect_species = set()
        high_quality_species = set()
        groups = Counter()
        for mon in rows:
            if mon['species'] not in SPECIES or type(mon['level']) is not int or not 1 <= mon['level'] <= 100:
                continue
            if mon['level'] == 100:
                maxed.update(level_credit(mon['species']))
            if (dv_rating(mon)['dv_stars'] or 0) >= 3:
                high_quality_species.add(SPECIES[mon['species']]['dex'])
            if is_perfect(mon):
                perfect_species.add(SPECIES[mon['species']]['dex'])
                if type(mon.get('trainer_id')) is int and 0 <= mon['trainer_id'] <= 65535:
                    groups[perfect_group(mon)] += 1
        token = (tuple(sorted(maxed)), tuple(sorted(perfect_species)), tuple(sorted(groups.items())),
                 tuple(sorted(high_quality_species)))
        # Confirm across consecutive observations to ignore partial party/PC writes.
        if token != self.previous:
            self.previous = token
            return
        if token == self.confirmed:
            return
        with self.store.lock, self.store.db:
            row = self.store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
            value = json.loads(row[0]) if row else empty()
            value['level_100'] = sorted(set(value['level_100']) | maxed)
            value['perfect_species'] = sorted(set(value['perfect_species']) | perfect_species)
            value['high_quality_species'] = sorted(set(value.get('high_quality_species', ()))
                                                   | high_quality_species | set(value['perfect_species']))
            for group, count in groups.items():
                value['perfect_groups'][group] = max(count, value['perfect_groups'].get(group, 0))
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))
        self.confirmed = token


def apply(payload, store):
    value = status(store)
    # Keep internal identity groups out of the public API.
    value.pop('perfect_groups')
    party = [dict(mon, perfect_dvs=is_perfect(mon), **dv_rating(mon)) for mon in payload.get('party', ())]
    storage = payload.get('storage')
    boxed = [dict(mon, perfect_dvs=is_perfect(mon), **dv_rating(mon)) for mon in (storage or {}).get('pokemon', ())]
    value['perfect_held'] = sum(mon['perfect_dvs'] for mon in party + boxed)
    value['three_star_held'] = sum(mon['dv_stars'] == 3 for mon in party + boxed)
    return {**payload, 'milestones': value, 'party': party,
            'storage': {**storage, 'pokemon': boxed} if storage else None}
