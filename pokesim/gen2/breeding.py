"""Collect missing hatchlings through the cartridge's two parent Day Care."""
from itertools import combinations

from .menus import ChangeBox, DayCare, Storage
from .training import FIELD_MOVES, identity
from .ram import calculated_stats, experience_at


def retrieval_cost(data, snapshot):
    total = 0
    for mon in getattr(snapshot, 'daycare', ()):
        if mon:
            growth = data.species[mon.species]['growth']
            level = max(level for level in range(mon.level, 101) if experience_at(level, growth) <= mon.experience)
            total += (level - mon.level + 1) * 100
    return total


def branch_parents(data, snapshot, baby, branches):
    available = [mon for mon in snapshot.party + snapshot.stored if mon.species == baby]
    if baby != 236:
        return len(available) >= len(branches)
    possible = set()
    for mon in available:
        stats = calculated_stats(data.species[baby]['stats'], max(20, mon.level + 1), mon.dvs, mon.stat_exp)
        possible.add(107 if stats[1] < stats[2] else 106 if stats[1] > stats[2] else 237)
    return branches <= possible


def offspring(data, first, second):
    if first.egg or second.egg or first.species == second.species == 132:
        return set()
    groups = [set(data.species[mon.species]['egg_groups']) for mon in (first, second)]
    if any('NONE' in group for group in groups):
        return set()
    if first.dvs[2] == second.dvs[2] and first.dvs[4] % 8 == second.dvs[4] % 8:
        return set()
    if first.species == 132 or second.species == 132:
        mother = second if first.species == 132 else first
    elif groups[0] & groups[1] and {first.gender, second.gender} == {'Male', 'Female'}:
        mother = first if first.gender == 'Female' else second
    else:
        return set()
    species = mother.species
    for _ in range(2):
        species = next((sid for sid, row in data.species.items()
                        if any(evo['species'] == species for evo in row['evolutions'])), species)
    return {29, 32} if species == 29 else {species}


def nursery(policy, snapshot, Goal):
    y = policy.collection.setdefault('nursery_end', 10)
    if snapshot.map == policy.data.map_ids['GOLDENROD_CITY'] and (snapshot.x, snapshot.y) == (20, y):
        y = policy.collection['nursery_end'] = 28 if y == 10 else 10
    x = 20
    return Goal('collection_hatch', 'Walk with the eggs and the Day Care partners', 'GOLDENROD_CITY', x, y)


def journey(policy, snapshot, Goal):
    state, data = policy.collection, policy.data
    parents = snapshot.daycare
    project = state.get('breeding')
    if project is None:
        mons = [mon for mon in snapshot.party[1:] + snapshot.stored + tuple(mon for mon in parents if mon)
                if not mon.egg and (mon.box is not None or not FIELD_MOVES.intersection(mon.moves))]
        choices = []
        for first, second in combinations(mons, 2):
            babies = offspring(data, first, second)
            missing = babies - snapshot.owned
            for baby in babies:
                if (policy.demand.get(baby, 0) and sum(mon.species == baby for mon in snapshot.party + snapshot.stored)
                        <= policy.demand[baby]):
                    missing.add(baby)
            for baby in babies & {133, 236, 43, 60, 79}:
                branches = {evo['species'] for evo in data.species[baby]['evolutions']}
                if baby in (43, 60):
                    middle = 44 if baby == 43 else 61
                    branches = {evo['species'] for evo in data.species[middle]['evolutions']}
                    available = sum(mon.species in {baby, middle} for mon in snapshot.party + snapshot.stored)
                    ready = available >= len(branches - snapshot.owned)
                else:
                    ready = branch_parents(data, snapshot, baby, branches - snapshot.owned)
                if not ready:
                    missing.add(baby)
            for target in missing:
                choices.append((target, first.box is not None, second.box is not None, identity(first), identity(second)))
        if choices and snapshot.money >= 3000:
            target, _, _, first, second = min(choices)
            project = state['breeding'] = {'target': target, 'parents': [first, second],
                'duplicate': target in snapshot.owned,
                'existing': [identity(mon) for mon in snapshot.party + snapshot.stored if mon.species == target]}
    if project is None:
        return nursery(policy, snapshot, Goal) if any(mon.egg for mon in snapshot.party) else None
    state['phase'] = 'breeding'
    if snapshot.egg_ready:
        if len(snapshot.party) == 6:
            return pc_goal(policy, snapshot, Goal, 'Make room for the Day Care egg')
        return policy.person(snapshot, 'collection_breed_egg', 'Receive the Day Care egg', 'ROUTE_34', 'DayCareManScript_Outside')
    complete = (project['target'] in snapshot.owned and not project.get('duplicate')
                or any(mon.species == project['target'] and (mon.egg or identity(mon) not in project.get('existing', []))
                       for mon in snapshot.party))
    for index, parent in enumerate(parents):
        if parent and (complete or identity(parent) != project['parents'][index]):
            if len(snapshot.party) == 6:
                return pc_goal(policy, snapshot, Goal, 'Make room to retrieve the Day Care partner')
            return policy.person(snapshot, 'collection_breed_take_' + str(index), 'Retrieve the Day Care partner',
                                 'DAY_CARE', 'DayCareManScript_Inside' if index == 0 else 'DayCareLadyScript')
    if complete:
        state['breeding'] = None
        return nursery(policy, snapshot, Goal) if any(mon.egg for mon in snapshot.party) else None
    for index, parent in enumerate(parents):
        if parent:
            continue
        mon = next((mon for mon in snapshot.party + snapshot.stored if identity(mon) == project['parents'][index]), None)
        if mon is None:
            state['breeding'] = None
            return None
        if mon.box is not None:
            state['breed_withdraw'] = identity(mon)
            return pc_goal(policy, snapshot, Goal, 'Bring the breeding partner from storage')
        return policy.person(snapshot, 'collection_breed_leave_' + str(index), 'Leave a partner at the Day Care',
                             'DAY_CARE', 'DayCareManScript_Inside' if index == 0 else 'DayCareLadyScript')
    return nursery(policy, snapshot, Goal)


def pc_goal(policy, snapshot, Goal, label):
    goal = policy.storage_goal(snapshot)
    return Goal('collection_breed_pc', label, goal.map_name, goal.x, goal.y, goal.face)


def arrive(policy, snapshot):
    key, state = policy.goal.key, policy.collection
    project = state.get('breeding')
    if key == 'collection_hatch':
        return 'wait'
    if not project:
        return None
    if key.startswith('collection_breed_leave_'):
        index = int(key[-1])
        slot = next(i for i, mon in enumerate(snapshot.party) if identity(mon) == project['parents'][index])
        policy.menu = DayCare(index, slot)
        return 'a'
    if key.startswith('collection_breed_take_'):
        policy.menu = DayCare(int(key[-1]))
        return 'a'
    if key == 'collection_breed_pc':
        if len(snapshot.party) == 6:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
                if box is not None:
                    policy.menu = ChangeBox(box)
                    return 'a'
                return 'b'
            candidates = [i for i, mon in enumerate(snapshot.party) if i and not mon.egg
                          and identity(mon) not in project['parents']]
            if not candidates:
                return 'b'
            slot = min(candidates, key=lambda i: (bool(FIELD_MOVES.intersection(snapshot.party[i].moves)), snapshot.party[i].level))
            policy.menu = Storage('DEPOSIT', slot, 6)
        else:
            mon = next((mon for mon in snapshot.stored if identity(mon) == state.get('breed_withdraw')), None)
            if mon:
                policy.menu = ChangeBox(mon.box) if mon.box != snapshot.active_box else Storage('WITHDRAW', mon.position, len(snapshot.party))
        return 'a'
    return None
