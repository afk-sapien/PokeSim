"""Raise collected partners through normal battles, held items and evolution."""
from .menus import ChangeBox, Give, Release, Remedy, Storage, Take
from .ram import calculated_stats, experience_at
from .standdown import stand_down, standing_down, train_key

FIELD_MOVES = {15, 19, 57, 70, 148, 250, 127}


def identity(mon):
    return [mon.trainer_id, list(mon.dvs)]


def happiness_levels(friendship):
    """Level ups needed to reach evolution friendship, using the cartridge's +5, +3 and +2 tiers."""
    levels = 0
    while friendship < 220:
        friendship += 5 if friendship < 100 else 3 if friendship < 200 else 2
        levels += 1
    return levels


def requested(data, snapshot, demand, species):
    """Whether cable demand wants another evolved copy of a family with no wild source."""
    from .breeding import single_source
    held = sum(mon.species == species and not mon.egg for mon in snapshot.party + snapshot.stored)
    return species in single_source(data) and bool(demand.get(species)) and held <= demand[species]


def wrong_time(evo, current_time):
    if evo['method'] != 'happiness':
        return False
    return (evo['requirements'][0] == 'TR_NITE' and current_time != 'night'
            or evo['requirements'][0] == 'TR_MORNDAY' and current_time == 'night')


def projects(data, snapshot, current_time, demand=None):
    from .collection import prerequisites
    needed = prerequisites(data, snapshot)
    demand = demand or {}
    inventory = dict(snapshot.items)
    rows = []
    for mon in snapshot.party + snapshot.stored:
        if mon.egg:
            continue
        for evo in data.species[mon.species]['evolutions']:
            if (evo['species'] in snapshot.owned and evo['species'] not in needed
                    and not requested(data, snapshot, demand, evo['species']) or evo['method'] == 'trade'):
                continue
            if mon.level == 100 and evo['method'] != 'item':
                continue
            requirements = evo['requirements']
            if evo['method'] == 'item':
                item = data.items[requirements[0]]
                if not inventory.get(item):
                    continue
                cost, level = 0, mon.level
            else:
                item = None
                level = max(mon.level + 1, int(requirements[0])) if evo['method'] in {'level', 'stat'} else mon.level + 1
                if evo['method'] == 'stat':
                    stats = calculated_stats(data.species[mon.species]['stats'], level, mon.dvs, mon.stat_exp)
                    condition = 'ATK_LT_DEF' if stats[1] < stats[2] else 'ATK_GT_DEF' if stats[1] > stats[2] else 'ATK_EQ_DEF'
                    if requirements[1] != condition:
                        continue
                if evo['method'] == 'happiness':
                    if wrong_time(evo, current_time):
                        continue
                    level = mon.level + max(1, happiness_levels(mon.friendship))
                if level > 100:
                    continue
                cost = experience_at(level, data.species[mon.species]['growth']) - mon.experience
            rows.append((cost, mon.box is not None, mon.species, identity(mon), evo['species'], item))
    return rows


def journey(policy, snapshot, mem, Goal, *, terminal=False):
    data, state = policy.data, policy.collection
    project = state.get('training')
    if project and project.get('terminal') and not project.get('level_goal') and not terminal:
        state['training'] = None
    share = data.items['EXP_SHARE']
    inventory = dict(snapshot.items)
    if not inventory.get(share) and not any(mon.held_item == share for mon in snapshot.party + snapshot.stored):
        if inventory.get(data.items['RED_SCALE']):
            return policy.person(snapshot, 'exp_share', 'Exchange the Red Scale for Exp. Share',
                                 'MR_POKEMONS_HOUSE', 'MrPokemonsHouse_MrPokemonScript')
        return None
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    project = state.get('training')
    from .collection import prerequisites
    demand = getattr(policy, 'demand', {})
    if (project and not project.get('terminal') and project['target'] in snapshot.owned
            and project['target'] not in prerequisites(data, snapshot)
            and not requested(data, snapshot, demand, project['target'])):
        state['training'] = project = None
    if project and standing_down(policy, train_key(project['identity'])):
        state['training'] = project = None
    if project is None:
        choices = projects(data, snapshot, current_time, demand)
        terminal_project = False
        if not choices and terminal:
            terminal_project = True
            choices = [(experience_at(100, data.species[mon.species]['growth']) - mon.experience,
                        mon.box is not None, mon.species, identity(mon), mon.species, None)
                       for mon in snapshot.party + snapshot.stored if not mon.egg and mon.level < 100]
        choices = [row for row in choices if not standing_down(policy, train_key(row[3]))]
        if not choices:
            return None
        _, _, species, key, target, item = min(choices)
        project = state['training'] = {'identity': key, 'target': target, 'item': item, 'species': species, 'terminal': terminal_project}
    mon = next((mon for mon in snapshot.party + snapshot.stored if identity(mon) == project['identity']), None)
    if (mon is None or mon.species != project['species'] and not project.get('terminal')
            or not project.get('item') and mon.level >= project.get('level_goal', 100)):
        state['training'] = None
        return None
    if project.get('terminal'):
        project['species'] = project['target'] = mon.species
    evo = next((evo for evo in data.species[mon.species]['evolutions'] if evo['species'] == project['target']), None)
    if (evo and not project.get('terminal') and wrong_time(evo, current_time)
            and happiness_levels(mon.friendship) <= 1 and mon.held_item != data.items['EVERSTONE']):
        # The next level brings evolution friendship, and Espeon needs morning or day while Umbreon needs
        # night. Exp. Share would level this Eevee in any battle, so it waits without the share.
        if mon.box is None and mon.held_item == share:
            state['take_slot'] = snapshot.party.index(mon)
            return Goal('collection_take', f'Hold {mon.name} back until the time of day suits',
                        data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        state['training'] = None
        return None
    if mon.held_item == data.items['EVERSTONE']:
        state['take_slot'] = snapshot.party.index(mon) if mon.box is None else None
        if mon.box is None:
            return Goal('collection_take', 'Remove Everstone before evolution', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state['phase'] = 'evolving'
    if mon.box is not None:
        goal = policy.storage_goal(snapshot)
        return Goal('collection_train_pc', f'Prepare {mon.name} for training', goal.map_name, goal.x, goal.y, goal.face)
    if project['item']:
        return Goal('collection_evolve_item', f'Evolve {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    if mon.held_item != share:
        other = next((i for i, row in enumerate(snapshot.party) if row.held_item == share), None)
        if other is not None:
            state['take_slot'] = other
            return Goal('collection_take', 'Pass Exp. Share to the next partner', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        if not inventory.get(share):
            holder = next((row for row in snapshot.stored if row.held_item == share), None)
            if holder:
                state['share_holder'] = identity(holder)
                goal = policy.storage_goal(snapshot)
                return Goal('collection_train_pc', 'Retrieve Exp. Share from storage', goal.map_name, goal.x, goal.y, goal.face)
            return None
        return Goal('collection_equip', f'Give Exp. Share to {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state.pop('share_holder', None)
    # Mt. Silver provides renewable experience for the trained champion and its partner.
    mid = data.map_ids['SILVER_CAVE_ROOM_1']
    from .collection import encounter_points
    points = encounter_points(policy, snapshot, mid, 'grass')
    if not points:
        return Goal('collection_train', 'Wait for the training map to finish loading',
                    data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    if snapshot.map == mid:
        candidates = [(policy.nav.local(snapshot, [point[:2]], policy.memory), point) for point in points
                      if 0 < abs(point[0] - snapshot.x) + abs(point[1] - snapshot.y) <= 3]
        candidates = [(len(path), policy.nav.visits.get((mid, *point[:2]), 0), point)
                      for path, point in candidates if path]
        if candidates:
            x, y, _ = min(candidates)[2]
        else:
            x, y, _ = points[0]
    else:
        x, y = 9, 31
    target_name = 'level ' + str(project.get('level_goal', 100)) if project.get('terminal') else data.species[project['target']]['name']
    return Goal('collection_train', f'Train {mon.name} toward {target_name}',
                'SILVER_CAVE_ROOM_1', x, y)


def arrive(policy, snapshot):
    state, data = policy.collection, policy.data
    project = state.get('training')
    if not project:
        return None
    wanted = state.get('share_holder') if policy.goal.key == 'collection_train_pc' else None
    wanted = wanted or project['identity']
    mon = next((row for row in snapshot.party + snapshot.stored if identity(row) == wanted), None)
    key = policy.goal.key
    if key == 'collection_train_pc' and mon:
        if mon.box is None:
            state.pop('share_holder', None)
            return 'b'
        if len(snapshot.party) == 6:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
                spare = policy.release_target(snapshot) if box is None else None
                if box is not None:
                    policy.menu = ChangeBox(box)
                elif spare is not None:
                    policy.menu = (ChangeBox(spare.box) if spare.box != snapshot.active_box
                                   else Release(spare.box, spare.position, [spare.species, spare.trainer_id, list(spare.dvs)]))
                else:
                    # No box has room and nothing can be released, so this partner cannot join the party.
                    stand_down(policy, train_key(project['identity']))
                    state['training'] = None
                    state.pop('share_holder', None)
                    return 'b'
                return 'a'
            counts = {move: sum(move in row.moves for row in snapshot.party) for move in FIELD_MOVES}
            slot = min(range(1, 6), key=lambda i: (sum(counts[move] == 1 for move in snapshot.party[i].moves if move in FIELD_MOVES),
                                                   snapshot.party[i].held_item == data.items['EXP_SHARE'], snapshot.party[i].level))
            policy.menu = Storage('DEPOSIT', slot, 6)
        elif snapshot.active_box != mon.box:
            policy.menu = ChangeBox(mon.box)
        else:
            policy.menu = Storage('WITHDRAW', mon.position, len(snapshot.party))
        return 'a'
    if mon and mon.box is None:
        slot = snapshot.party.index(mon)
        if key == 'collection_equip':
            policy.menu = Give(data.items['EXP_SHARE'], slot)
        elif key == 'collection_take':
            policy.menu = Take(state['take_slot'])
        elif key == 'collection_evolve_item':
            policy.menu = Remedy(project['item'], slot, dict(snapshot.items)[project['item']])
        else:
            return 'wait' if key == 'collection_train' else None
        return 'wait'
    return None
