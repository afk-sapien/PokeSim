"""Collect missing hatchlings through the cartridge's two parent Day Care.

Core holds the breeding rules (``pokecore.gen2.breeding``). This module plans the trips.
"""
from copy import deepcopy
from itertools import combinations

from pokecore.gen2.breeding import (branch_parents, descendants_wanted, egg_lines, families,
                                        free_slots, offspring)

from .menus import ChangeBox, DayCare, Storage
from ..planning.ledger import FIELD_MOVES
from .training import identity


HAPPINESS_TO_EVOLVE = 220
# Eggs carried at once while hatching the ones stored in the PC. The rest of the party stays free for
# field moves, trainees and partners.
HATCH_BATCH = 3
# PC operations a hatching trip may take before it stands down instead of looping at the PC.
HATCH_OPS = 30
HATCH_KEY = 'hatch'
BREED_KEY = 'breed'


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


def sole_field_move(party, slot):
    """Whether party ``slot`` is the only member that knows one of its field moves."""
    others = {move for i, mon in enumerate(party) if i != slot and not mon.egg for move in mon.moves}
    return bool(FIELD_MOVES.intersection(party[slot].moves) - others)


def spare_slots(snapshot, project):
    """Party slots the breeding errands may send to the PC, best choice first.

    A parent still needed at the Day Care stays, and so does the only party member that knows a field
    move. Storing that one would make the policy fetch it straight back for the next HM obstacle.
    """
    party, complete = snapshot.party, finished(project, snapshot)
    slots = [i for i, mon in enumerate(party) if i and not mon.egg and not sole_field_move(party, i)
             and (complete or not parent(mon, project))]
    return sorted(slots, key=lambda i: (bool(FIELD_MOVES.intersection(party[i].moves)), party[i].level))


def make_room(policy, snapshot, Goal, label, project):
    spare = spare_slots(snapshot, project)
    if not spare and any(mon.egg for mon in snapshot.party):
        # Every member is needed. Hatching an egg gives the party a Pokémon it can spare.
        return nursery(policy, snapshot, Goal)
    if not spare or free_slots(snapshot) < 1:
        # Nothing the PC may take, or nowhere to put it: the errand would press B at the PC forever.
        from .standdown import stand_down
        stand_down(policy, BREED_KEY)
        policy.collection['breeding'] = None
        return None
    return pc_goal(policy, snapshot, Goal, label)


def nursery(policy, snapshot, Goal):
    y = policy.collection.setdefault('nursery_end', 10)
    if snapshot.map == policy.data.map_ids['GOLDENROD_CITY'] and (snapshot.x, snapshot.y) == (20, y):
        y = policy.collection['nursery_end'] = 28 if y == 10 else 10
    x = 20
    return Goal('collection_hatch', 'Walk with the eggs and the Day Care partners', 'GOLDENROD_CITY', x, y)


def pairings(policy, snapshot):
    """Every Day Care pair worth breeding, as (target, first boxed, second boxed, identities, species).

    The search tries every pair of Pokémon in the party, the PC and the Day Care, so it is slow for a
    large collection. Its answer depends only on those Pokémon, the Pokédex and the demand list, which
    stay the same across the many policy steps of a menu, a walk or an animation, so the last answer is
    kept until one of them changes.
    """
    data, parents = policy.data, snapshot.daycare
    room = free_slots(snapshot) >= 3
    unhatched = egg_lines(data, snapshot)
    key = (snapshot.party, snapshot.stored, parents, frozenset(snapshot.owned), tuple(sorted(policy.demand.items())), room)
    cached = getattr(policy, '_breeding_pairings', None)
    if cached is not None and cached[0] == key:
        return cached[1]
    mons = [mon for mon in snapshot.party[1:] + snapshot.stored + tuple(mon for mon in parents if mon)
            if not mon.egg and (mon.box is not None or not FIELD_MOVES.intersection(mon.moves))]
    choices = []
    for first, second in combinations(mons, 2):
        babies = offspring(data, first, second)
        missing = babies - snapshot.owned
        for baby in babies:
            if descendants_wanted(data, snapshot, policy.demand, baby):
                missing.add(baby)
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
            if target in unhatched:
                # An egg of this line is still waiting to hatch, so hatch it before breeding another.
                continue
            if target in snapshot.owned and not room:
                # A spare copy needs a box slot for each egg and parent shuffle, or the PC errand loops.
                continue
            choices.append((target, first.box is not None, second.box is not None, identity(first), identity(second),
                            first.species, second.species))
    policy._breeding_pairings = (key, choices)
    return choices


def journey(policy, snapshot, Goal):
    state, data = policy.collection, policy.data
    parents = snapshot.daycare
    project = state.get('breeding')
    if project is not None and 'species' not in project:
        project = state['breeding'] = recorded_species(data, snapshot, project)
    # Eggs brought from the PC hatch on the walks of other errands, so they do not hold the run here.
    brought = brought_eggs(state, snapshot)
    walk = any(mon.egg and (not brought or egg_key(mon) not in brought) for mon in snapshot.party)
    if project is None and walk:
        return nursery(policy, snapshot, Goal)
    if project is None:
        from .standdown import standing_down
        choices = [] if standing_down(policy, BREED_KEY) else pairings(policy, snapshot)
        if choices and snapshot.money >= 3000:
            target, _, _, first, second, *species = deepcopy(min(choices))
            project = state['breeding'] = {'target': target, 'parents': [first, second], 'species': species,
                'duplicate': target in snapshot.owned,
                'existing': [identity(mon) for mon in snapshot.party + snapshot.stored if mon.species == target]}
    if project is None:
        return nursery(policy, snapshot, Goal) if walk else None
    state['phase'] = 'breeding'
    unhatched = project['target'] in egg_lines(data, snapshot)
    complete = finished(project, snapshot) or unhatched
    # While an egg waits the Day Care man stands outside on Route 34, so his partner comes back only
    # after the egg. Talking to his empty spot inside would loop forever.
    man_partner = parents[0] and (complete or not member(parents[0], project, 0))
    if snapshot.egg_ready and (not unhatched or man_partner):
        if len(snapshot.party) == 6:
            return make_room(policy, snapshot, Goal, 'Make room for the Day Care egg', project)
        return policy.person(snapshot, 'collection_breed_egg', 'Receive the Day Care egg', 'ROUTE_34', 'DayCareManScript_Outside')
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
        return nursery(policy, snapshot, Goal) if walk else None
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
            if len(snapshot.party) == 6:
                # A full party of eggs and sole field-move holders has nothing the PC can take, so the
                # errand would stand at the PC forever. The eggs hatch first and free a slot.
                return make_room(policy, snapshot, Goal, 'Bring the breeding partner from storage', project)
            return pc_goal(policy, snapshot, Goal, 'Bring the breeding partner from storage')
        return policy.person(snapshot, 'collection_breed_leave_' + str(index), 'Leave a partner at the Day Care',
                             'DAY_CARE', 'DayCareManScript_Inside' if index == 0 else 'DayCareLadyScript')
    return nursery(policy, snapshot, Goal)


def egg_key(mon):
    return [mon.trainer_id, list(mon.dvs), mon.species]


def brought_eggs(state, snapshot):
    """The eggs a hatching trip took from the PC that are still eggs, as egg keys."""
    if not state.get('hatching'):
        return []
    held = [egg_key(mon) for mon in snapshot.party + snapshot.stored if mon.egg]
    brought = [key for key in state.get('hatching') or () if key in held]
    if brought:
        state['hatching'] = brought
    else:
        state.pop('hatching', None)
    return brought


def worth_hatching(policy, snapshot, mon):
    """Whether an egg would add something once hatched.

    An egg whose whole family is already registered gives only another copy, so it is worth a trip
    only while cable demand or a later stage of a single source family still asks for that copy. Gold
    once boxed dozens of Sneasel eggs, and fetching them one by one held a trainee in the PC for days.
    """
    data, demand = policy.data, getattr(policy, 'demand', None) or {}
    owned = getattr(snapshot, 'owned', None)
    species = mon.species
    if owned is None or not families(data).get(species, {species}) <= owned:
        return True
    held = sum(not other.egg and other.species == species for other in snapshot.party + snapshot.stored)
    # Like the breeding search, demand keeps one copy beyond what the cable asks for as a parent.
    return bool(demand.get(species)) and held <= demand[species] or descendants_wanted(data, snapshot, demand, species)


def carried(policy, snapshot, mon):
    """Whether a party member is an egg a hatching trip brought from the PC that is worth hatching.

    Every PC deposit ranks such an egg last of all, so an egg taken out to hatch never goes back. An
    egg that adds nothing may go back to make room for a trainee.
    """
    return (bool(getattr(mon, 'egg', False)) and egg_key(mon) in brought_eggs(getattr(policy, 'collection', {}), snapshot)
            and worth_hatching(policy, snapshot, mon))


def hatch_spares(policy, snapshot):
    """Party slots a hatching trip may send to the PC to carry an egg, best choice first.

    The lead, the eggs, the only holder of a field move, the breeding parents, the trainees, the Exp.
    Share holder and the legendary sleeper stay, or the next errand would fetch them straight back. An
    activity team is left out, because its errands run ahead of this one and a finished activity can
    leave its last team on record.
    """
    from .release import _keys, _pair, plan_partners
    state, party = policy.collection, snapshot.party
    partners = {key for key in plan_partners(state) if not isinstance(key, str)}
    partners.update(pair for pair in map(_pair, (state.get('share_holder'), state.get('roam_lead'))) if pair)
    share = policy.data.items.get('EXP_SHARE')
    slots = [i for i, mon in enumerate(party) if i and not mon.egg and not sole_field_move(party, i)
             and mon.held_item != share and not partners.intersection(_keys(mon))]
    return sorted(slots, key=lambda i: (bool(FIELD_MOVES.intersection(party[i].moves)),
                                        bool(party[i].held_item), party[i].level))


def hatching(policy, snapshot, Goal):
    """Bring a few eggs from the PC into the party so the walks of other errands hatch them.

    Eggs only hatch in the party, and an egg boxed to make room would otherwise wait forever. The trip
    fills the party up to HATCH_BATCH eggs once it carries none, then leaves the walking to training,
    hunts and the patrol. Every training plan asks here first, so the trip also fits in the training
    that prepares a legendary or roamer lead. With every box and the party full the eggs wait for the
    release errand to free a slot.
    """
    from .standdown import standing_down
    state = policy.collection
    carried = sum(getattr(mon, 'egg', False) for mon in snapshot.party)
    # Only eggs that add something get a trip. The rest stay boxed rather than hold up training.
    boxed = any(getattr(mon, 'egg', False) and worth_hatching(policy, snapshot, mon)
                for mon in getattr(snapshot, 'stored', ()))
    # A Battle Tower run or a Time Capsule restore needs an exact party, so the eggs wait for it.
    if (not boxed or carried >= HATCH_BATCH or state.get('breeding') or state.get('tower')
            or state.get('time_capsule_restore') or standing_down(policy, HATCH_KEY) or carried and not state.get('hatch_fill')):
        state.pop('hatch_fill', None)
        state.pop('hatch_ops', None)
        return None
    # A trainee or the Exp. Share holder waiting in the PC needs the party slot, so the eggs wait for it.
    project = state.get('training') or {}
    waiting = [key for key in (project.get('identity'), state.get('share_holder')) if key]
    if waiting and any(identity(mon) in waiting for mon in getattr(snapshot, 'stored', ())):
        return None
    if len(snapshot.party) >= 6 and (not hatch_spares(policy, snapshot) or free_slots(snapshot) < 1):
        return None
    state['hatch_fill'] = True
    goal = policy.storage_goal(snapshot)
    return Goal('collection_hatch_pc', 'Bring eggs from storage to hatch', goal.map_name, goal.x, goal.y, goal.face)


def hatch_walk(policy, snapshot):
    """Whether a PC swap should wait while the party walks an egg to hatching.

    An egg brought out to hatch never goes back, so with a full party and no spare beside it the swap
    could only store the sole holder of a field move, which the next route fetches straight back. The
    walk is bounded, since every step counts the egg down and the hatched partner becomes a spare.
    """
    party = snapshot.party
    return (len(party) >= 6 and any(carried(policy, snapshot, mon) for mon in party)
            and not hatch_spares(policy, snapshot))


def hatch_arrive(policy, snapshot):
    """Withdraw a stored egg, or deposit a spare partner first when the party is full."""
    from .standdown import stand_down
    state = policy.collection
    state['hatch_ops'] = state.get('hatch_ops', 0) + 1
    eggs = sorted((mon for mon in snapshot.stored if mon.egg and worth_hatching(policy, snapshot, mon)), key=lambda mon: (mon.box != snapshot.active_box, mon.box))
    if not eggs or state['hatch_ops'] > HATCH_OPS:
        # Nothing left to bring, or the trip keeps failing. Leave the PC and let other work go on.
        stand_down(policy, HATCH_KEY)
        state.pop('hatch_fill', None)
        state.pop('hatch_ops', None)
        return 'b'
    if len(snapshot.party) < 6:
        egg = eggs[0]
        if egg.box != snapshot.active_box:
            policy.menu = ChangeBox(egg.box)
        else:
            brought = state.setdefault('hatching', [])
            if egg_key(egg) not in brought:
                brought.append(egg_key(egg))
            policy.menu = Storage('WITHDRAW', egg.position, len(snapshot.party))
        return 'a'
    spares = hatch_spares(policy, snapshot)
    if snapshot.box_counts[snapshot.active_box] >= 20:
        box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is None or not spares:
            stand_down(policy, HATCH_KEY)
            return 'b'
        policy.menu = ChangeBox(box)
        return 'a'
    if not spares:
        stand_down(policy, HATCH_KEY)
        return 'b'
    policy.menu = Storage('DEPOSIT', spares[0], len(snapshot.party))
    return 'a'


def pc_goal(policy, snapshot, Goal, label):
    goal = policy.storage_goal(snapshot)
    return Goal('collection_breed_pc', label, goal.map_name, goal.x, goal.y, goal.face)


def arrive(policy, snapshot):
    key, state = policy.goal.key, policy.collection
    project = state.get('breeding')
    if key == 'collection_hatch':
        return 'wait'
    if key == 'collection_hatch_pc':
        return hatch_arrive(policy, snapshot)
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
