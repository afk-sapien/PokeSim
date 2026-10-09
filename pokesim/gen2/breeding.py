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


def member(mon, project, index):
    """Whether ``mon`` is the project's parent in Day Care slot ``index``.

    Trainer ID and DVs alone are not unique. Two boxed Pokémon caught by the same trainer can share
    all five DVs, so a project also records each parent's species once it knows them.
    """
    species = project.get('species')
    return identity(mon) == project['parents'][index] and (species is None or mon.species == species[index])


def parent(mon, project):
    return any(member(mon, project, index) for index in range(2))


def recorded_species(data, snapshot, project):
    """Fill in the parent species of a project saved before they were recorded, or None when no pair fits."""
    pool = snapshot.party + snapshot.stored + tuple(mon for mon in snapshot.daycare if mon)
    options = [[mon for mon in pool if identity(mon) == wanted] for wanted in project['parents']]
    for first in options[0]:
        for second in options[1]:
            if first is not second and project['target'] in offspring(data, first, second):
                return {**project, 'species': [first.species, second.species]}
    return None


def finished(project, snapshot):
    return (project['target'] in snapshot.owned and not project.get('duplicate')
            or any(mon.species == project['target'] and (mon.egg or identity(mon) not in project.get('existing', []))
                   for mon in snapshot.party))


def spare_slots(snapshot, project):
    """Party slots the breeding errands may send to the PC, best choice first.

    A parent still needed at the Day Care stays, and so does the only party member that knows a field
    move. Storing that one would make the policy fetch it straight back for the next HM obstacle.
    """
    party, complete = snapshot.party, finished(project, snapshot)
    def sole_field_move(slot):
        others = {move for i, mon in enumerate(party) if i != slot and not mon.egg for move in mon.moves}
        return bool(FIELD_MOVES.intersection(party[slot].moves) - others)
    slots = [i for i, mon in enumerate(party) if i and not mon.egg and not sole_field_move(i)
             and (complete or not parent(mon, project))]
    return sorted(slots, key=lambda i: (bool(FIELD_MOVES.intersection(party[i].moves)), party[i].level))


def make_room(policy, snapshot, Goal, label, project):
    if not spare_slots(snapshot, project) and any(mon.egg for mon in snapshot.party):
        # Every member is needed. Hatching an egg gives the party a Pokémon it can spare.
        return nursery(policy, snapshot, Goal)
    return pc_goal(policy, snapshot, Goal, label)


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
    if project is not None and 'species' not in project:
        project = state['breeding'] = recorded_species(data, snapshot, project)
    if project is None and any(mon.egg for mon in snapshot.party):
        return nursery(policy, snapshot, Goal)
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
                level_evolution = any(evo['method'] in {'level', 'happiness', 'stat'}
                                      and evo['species'] not in snapshot.owned
                                      for evo in data.species[baby]['evolutions'])
                if (baby in snapshot.owned and level_evolution
                        and not any(mon.species == baby and mon.level < 100
                                    for mon in snapshot.party + snapshot.stored)):
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
                choices.append((target, first.box is not None, second.box is not None, identity(first), identity(second),
                                first.species, second.species))
        if choices and snapshot.money >= 3000:
            target, _, _, first, second, *species = min(choices)
            project = state['breeding'] = {'target': target, 'parents': [first, second], 'species': species,
                'duplicate': target in snapshot.owned,
                'existing': [identity(mon) for mon in snapshot.party + snapshot.stored if mon.species == target]}
    if project is None:
        return nursery(policy, snapshot, Goal) if any(mon.egg for mon in snapshot.party) else None
    state['phase'] = 'breeding'
    if snapshot.egg_ready:
        if len(snapshot.party) == 6:
            return make_room(policy, snapshot, Goal, 'Make room for the Day Care egg', project)
        return policy.person(snapshot, 'collection_breed_egg', 'Receive the Day Care egg', 'ROUTE_34', 'DayCareManScript_Outside')
    complete = finished(project, snapshot)
    if (not complete and all(parents) and all(member(mon, project, index) for index, mon in enumerate(parents))
            and project['target'] not in offspring(data, *parents)):
        # These two can never produce the target, so walking with them would wait forever.
        state['breeding'] = None
        return None
    for index, mon in enumerate(parents):
        if mon and (complete or not member(mon, project, index)):
            if len(snapshot.party) == 6:
                return make_room(policy, snapshot, Goal, 'Make room to retrieve the Day Care partner', project)
            return policy.person(snapshot, 'collection_breed_take_' + str(index), 'Retrieve the Day Care partner',
                                 'DAY_CARE', 'DayCareManScript_Inside' if index == 0 else 'DayCareLadyScript')
    if complete:
        state['breeding'] = None
        return nursery(policy, snapshot, Goal) if any(mon.egg for mon in snapshot.party) else None
    for index, current in enumerate(parents):
        if current:
            continue
        mon = next((mon for mon in snapshot.party + snapshot.stored if member(mon, project, index)), None)
        if mon is None:
            state['breeding'] = None
            return None
        if mon.box is not None:
            state['breed_withdraw'] = identity(mon)
            state['breed_withdraw_species'] = mon.species
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
        slot = next((i for i, mon in enumerate(snapshot.party) if member(mon, project, index)), None)
        if slot is None:
            return 'b'
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
            candidates = spare_slots(snapshot, project)
            if not candidates:
                return 'b'
            policy.menu = Storage('DEPOSIT', candidates[0], 6)
        else:
            species = state.get('breed_withdraw_species')
            mon = next((mon for mon in snapshot.stored if identity(mon) == state.get('breed_withdraw')
                        and (species is None or mon.species == species)), None)
            if mon:
                policy.menu = ChangeBox(mon.box) if mon.box != snapshot.active_box else Storage('WITHDRAW', mon.position, len(snapshot.party))
        return 'a'
    return None
