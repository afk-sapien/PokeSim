"""Durable Pokédex goals, independent of emulator checkpoints and box positions."""
from collections import Counter
from functools import lru_cache
import json
import time

from . import progress
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
    progress.goals_changed(db, time.time())


def _goal_row(species, level, dvs, trainer_id):
    """Keep only milestone inputs, preserving strict integer validation."""
    level = level if type(level) is int else None
    dvs = tuple(dvs) if isinstance(dvs, (list, tuple)) and all(type(v) is int for v in dvs) else ()
    trainer_id = trainer_id if type(trainer_id) is int else None
    return species, level, dvs, trainer_id


def _goal_inputs(snapshot):
    rows = [_goal_row(mon.species, mon.level, mon.dvs, mon.trainer_id) for mon in snapshot.party]
    if snapshot.stored_details and snapshot.stored_pokemon == tuple(
            (mon.box, mon.species, mon.level, mon.nick) for mon in snapshot.stored_details):
        rows.extend(_goal_row(mon.species, mon.level, mon.dvs, mon.trainer_id)
                    for mon in snapshot.stored_details)
    else:
        rows.extend(_goal_row(mon['species'], mon['level'], mon.get('dvs'), mon.get('trainer_id'))
                    for mon in snapshot.storage_entries())
    return tuple(rows)


def _goal_token(rows):
    maxed, perfect_species, high_quality_species = set(), set(), set()
    groups = Counter()
    for species, level, dvs, trainer_id in rows:
        if species not in SPECIES or level is None or not 1 <= level <= 100:
            continue
        mon = {'species': species, 'dvs': dvs, 'trainer_id': trainer_id}
        if level == 100:
            maxed.update(level_credit(species))
        if (dv_rating(mon)['dv_stars'] or 0) >= 3:
            high_quality_species.add(SPECIES[species]['dex'])
        if is_perfect(mon):
            perfect_species.add(SPECIES[species]['dex'])
            if trainer_id is not None and 0 <= trainer_id <= 65535:
                groups[perfect_group(mon)] += 1
    return (tuple(sorted(maxed)), tuple(sorted(perfect_species)), tuple(sorted(groups.items())),
            tuple(sorted(high_quality_species)))


class MilestoneTracker:
    def __init__(self, store):
        self.store = store
        self.previous = None
        self.confirmed = None
        self._inputs = None
        self._token = None

    def reset(self):
        self.store.set(KEY, empty())
        self.previous = self.confirmed = None
        self._inputs = self._token = None

    def observe(self, snapshot):
        if not snapshot.started or not snapshot.valid or self.store.get('trade_hold'):
            self.previous = None
            return
        inputs = _goal_inputs(snapshot)
        if inputs != self._inputs:
            self._token = _goal_token(inputs)
            self._inputs = inputs
        token = self._token
        # Confirm across consecutive observations to ignore partial party/PC writes.
        if token != self.previous:
            self.previous = token
            return
        if token == self.confirmed:
            return
        maxed, perfect_species, groups, high_quality_species = token
        with self.store.lock, self.store.db:
            row = self.store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()
            value = json.loads(row[0]) if row else empty()
            value['level_100'] = sorted(set(value['level_100']) | set(maxed))
            value['perfect_species'] = sorted(set(value['perfect_species']) | set(perfect_species))
            value['high_quality_species'] = sorted(set(value.get('high_quality_species', ()))
                                                   | set(high_quality_species) | set(value['perfect_species']))
            for group, count in groups:
                value['perfect_groups'][group] = max(count, value['perfect_groups'].get(group, 0))
            self.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (KEY, json.dumps(value)))
            progress.goals_changed(self.store.db, time.time())
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
