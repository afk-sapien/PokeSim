"""Raise collected partners through normal battles, held items and evolution."""
from .menus import ChangeBox, Give, Remedy, Storage, Take
from .ram import calculated_stats, experience_at

FIELD_MOVES = {15, 19, 57, 70, 148, 250, 127}


def identity(mon):
    return [mon.trainer_id, list(mon.dvs)]


def projects(data, snapshot, current_time):
    inventory = dict(snapshot.items)
    rows = []
    for mon in snapshot.party + snapshot.stored:
        if mon.egg or mon.level == 100:
            continue
        for evo in data.species[mon.species]['evolutions']:
            if evo['species'] in snapshot.owned or evo['method'] == 'trade':
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
                    if requirements[0] == 'TR_NITE' and current_time != 'night':
                        continue
                    if requirements[0] == 'TR_MORNDAY' and current_time == 'night':
                        continue
                    level += max(0, 220 - mon.friendship) // 5
                if level > 100:
                    continue
                cost = experience_at(level, data.species[mon.species]['growth']) - mon.experience
            rows.append((cost, mon.box is not None, mon.species, identity(mon), evo['species'], item))
    return rows


def journey(policy, snapshot, mem, Goal, *, terminal=False):
    data, state = policy.data, policy.collection
    share = data.items['EXP_SHARE']
    inventory = dict(snapshot.items)
    if not inventory.get(share) and not any(mon.held_item == share for mon in snapshot.party + snapshot.stored):
        if inventory.get(data.items['RED_SCALE']):
            return policy.person(snapshot, 'exp_share', 'Exchange the Red Scale for Exp. Share',
                                 'MR_POKEMONS_HOUSE', 'MrPokemonsHouse_MrPokemonScript')
        return None
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    project = state.get('training')
    if project and not project.get('terminal') and project['target'] in snapshot.owned:
        state['training'] = project = None
    if project is None:
        choices = projects(data, snapshot, current_time)
        terminal_project = False
        if not choices and terminal:
            terminal_project = True
            choices = [(experience_at(100, data.species[mon.species]['growth']) - mon.experience,
                        mon.box is not None, mon.species, identity(mon), mon.species, None)
                       for mon in snapshot.party + snapshot.stored if not mon.egg and mon.level < 100]
        if not choices:
            return None
        _, _, species, key, target, item = min(choices)
        project = state['training'] = {'identity': key, 'target': target, 'item': item, 'species': species, 'terminal': terminal_project}
    mon = next((mon for mon in snapshot.party + snapshot.stored if identity(mon) == project['identity']), None)
    if mon is None or mon.species != project['species'] and not project.get('terminal') or mon.level == 100:
        state['training'] = None
        return None
    if project.get('terminal'):
        project['species'] = project['target'] = mon.species
    if mon.held_item == data.items['EVERSTONE']:
        state['take_slot'] = snapshot.party.index(mon) if mon.box is None else None
        if mon.box is None:
            return Goal('collection_take', 'Remove Everstone before evolution', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state['phase'] = 'evolving'
    if mon.box is not None:
        goal = policy.storage_goal(snapshot)
        return Goal('collection_train_pc', f'Prepare {mon.name} for evolution', goal.map_name, goal.x, goal.y, goal.face)
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
    target_name = 'level 100' if project.get('terminal') else data.species[project['target']]['name']
    return Goal('collection_train', f'Train {mon.name} toward {target_name}',
                'SILVER_CAVE_ROOM_1', x, y)


def arrive(policy, snapshot):
    state, data = policy.collection, policy.data
    project = state.get('training')
    if not project:
        return None
    wanted = state.get('share_holder') or project['identity']
    mon = next((row for row in snapshot.party + snapshot.stored if identity(row) == wanted), None)
    key = policy.goal.key
    if key == 'collection_train_pc' and mon:
        if mon.box is None:
            state.pop('share_holder', None)
            return 'b'
        if len(snapshot.party) == 6:
            if snapshot.box_counts[snapshot.active_box] >= 20:
                box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
                if box is not None:
                    policy.menu = ChangeBox(box)
                    return 'a'
                return 'b'
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
