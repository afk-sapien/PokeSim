"""Raise collected partners through normal battles, held items and evolution."""
from .menus import ChangeBox, Give, PutAway, Release, Remedy, Storage, Take, Toss
from pokecore.gen2.ram import calculated_stats, experience_at
from .standdown import TRAINING_DECISIONS, exhausted, spend, stand_down, standing_down, train_key

FIELD_MOVES = {15, 19, 57, 70, 148, 250, 127}


def identity(mon):
    return [mon.trainer_id, list(mon.dvs)]


def shareless(data, snapshot):
    """Whether the cartridge has lost its only Exp. Share, which no shop or person hands out again."""
    share = data.items['EXP_SHARE']
    return not dict(snapshot.items).get(share) and not any(mon.held_item == share for mon in snapshot.party + snapshot.stored)


# Distinct entries each Gen 2 pocket holds. A held item handed back on a swap or a take needs one free.
POCKET_SLOTS = {'items': 20, 'balls': 12}
# Refusals of one training project's item task before the project stands down. The monitor keeps the count.
ITEM_REFUSALS = 3


def bag_takes(data, snapshot, item):
    """Whether the bag has room for one more ``item``."""
    pocket = 'balls' if data.item_attributes[item]['pocket'] == 'BALL' else 'items'
    held = snapshot.pockets.get(pocket, ())
    count = dict(held).get(item, 0)
    return count < 99 if count else len(held) < POCKET_SLOTS[pocket]


# Items some plan uses from the bag: battle medicine, Champion shop supplies, the Tower's held items and
# the share and Everstone the training itself moves. Evolution items are added from the species data.
KEPT_ITEMS = frozenset({'EXP_SHARE', 'EVERSTONE', 'PRZCUREBERRY', 'LEFTOVERS', 'LUCKY_EGG', 'RARE_CANDY', 'PP_UP',
                        'FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION', 'SUPER_POTION', 'POTION', 'MAX_REVIVE',
                        'REVIVE', 'FULL_HEAL', 'ANTIDOTE', 'AWAKENING', 'PARLYZ_HEAL', 'BURN_HEAL', 'ICE_HEAL',
                        'MAX_ELIXER', 'ELIXER'})
# Sold for money when the wallet runs dry, so they leave the bag last.
VALUABLES = frozenset({'NUGGET', 'PEARL', 'BIG_PEARL', 'STARDUST', 'STAR_PIECE'})


def spare_item(data, snapshot):
    """The items-pocket entry worth least that no plan uses, put away to free an entry, or None."""
    kept = {data.items[name] for name in KEPT_ITEMS if name in data.items}
    kept |= {data.items[req] for entry in data.species.values() for evo in entry['evolutions']
             if evo['method'] in ('item', 'trade') for req in evo['requirements'] if req in data.items}
    valuables = {data.items[name] for name in VALUABLES if name in data.items}
    rows = [(item, count) for item, count in snapshot.pockets.get('items', ())
            if item not in kept and data.item_attributes.get(item, {}).get('pocket') == 'ITEM']
    if not rows:
        return None
    return min(rows, key=lambda row: (row[0] in valuables, data.item_attributes[row[0]]['price'] * row[1], row[0]))[0]


def room_goal(policy, snapshot, Goal, item):
    """Walk to the PC to put a spare item away when the bag has no entry for ``item``, or None."""
    data = policy.data
    if bag_takes(data, snapshot, item):
        return None
    spare = spare_item(data, snapshot)
    if spare is None:
        return None
    policy.collection['tidy_item'] = spare
    goal = policy.storage_goal(snapshot)
    return Goal('collection_tidy', f'Store {data.item_names.get(spare, "a spare item")} in the PC to make room', goal.map_name, goal.x, goal.y, goal.face)


def share_blocked(data, snapshot, mon):
    """Whether the Exp. Share cannot reach ``mon`` because the bag has no room for an item the move hands back.

    Giving the share to a Pokémon that holds something else puts that item in the bag, and taking the share
    from another party member puts the share there, so either one needs a free pocket entry.
    """
    share = data.items['EXP_SHARE']
    if mon.held_item == share:
        return False
    if mon.held_item and not bag_takes(data, snapshot, mon.held_item):
        return True
    return any(row is not mon and row.held_item == share for row in snapshot.party) and not bag_takes(data, snapshot, share)


def trainee_slot(policy, snapshot):
    """The party slot of a partner levelling without an Exp. Share, which leads so it joins every battle."""
    project = policy.collection.get('training')
    if not project or project.get('item'):
        return None
    slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg and identity(mon) == project['identity']), None)
    if slot is None or not (shareless(policy.data, snapshot) or share_blocked(policy.data, snapshot, snapshot.party[slot])):
        return None
    return slot


def happiness_levels(friendship):
    """Level ups needed to reach evolution friendship, using the cartridge's +5, +3 and +2 tiers."""
    levels = 0
    while friendship < 220:
        friendship += 5 if friendship < 100 else 3 if friendship < 200 else 2
        levels += 1
    return levels


def requested(data, snapshot, demand, species, *, item=False):
    """Whether cable demand wants another evolved copy of a family with no wild source.

    An evolution stone makes a copy for a peer even when the family has a wild source, if no copy
    here could travel: automatic trading keeps a trained partner, so a single veteran never leaves.
    """
    from pokecore.gen2.breeding import single_source
    copies = [mon for mon in snapshot.party + snapshot.stored if mon.species == species and not mon.egg]
    if not demand.get(species):
        return False
    if species in single_source(data) and len(copies) <= demand[species]:
        return True
    return item and not any(spare_copy(data, mon) for mon in copies)


def spare_copy(data, mon):
    """Whether automatic trading could offer this copy, the rules of trading._kept that a snapshot shows."""
    return (mon.box is not None and not mon.shiny and tuple(mon.dvs) != (15,) * 5
            and mon.held_item != data.items['EXP_SHARE'] and sum(mon.stat_exp) < 20000)


def stone_needed(data, snapshot, item, keep):
    """Whether ``item`` would evolve another partner here into an entry this cartridge still lacks."""
    return any(evo['method'] == 'item' and data.items.get(evo['requirements'][0]) == item
               and evo['species'] not in snapshot.owned and mon is not keep
               for mon in snapshot.party + snapshot.stored if not mon.egg
               for evo in data.species[mon.species]['evolutions'])


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
                    and not requested(data, snapshot, demand, evo['species'], item=evo['method'] == 'item')
                    or evo['method'] == 'trade'):
                continue
            if mon.level == 100 and evo['method'] != 'item':
                continue
            requirements = evo['requirements']
            if evo['method'] == 'item':
                item = data.items[requirements[0]]
                if not inventory.get(item):
                    continue
                # A stone spent on a peer's request must not be the one this cartridge's own entry needs.
                if (evo['species'] in snapshot.owned and inventory[item] < 2
                        and stone_needed(data, snapshot, item, mon)):
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
    from .breeding import hatching
    # Training is the walking time that hatches eggs, so stored eggs join the party first.
    goal = hatching(policy, snapshot, Goal)
    if goal:
        return goal
    project = state.get('training')
    if project and project.get('terminal') and not project.get('level_goal') and not terminal:
        state['training'] = None
    if project and project.get('postgame') and not terminal:
        # Postgame training waits behind collection work and only runs from postgame.journey, but an
        # evolution that adds a Pokédex entry takes its place at once.
        current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
        if not projects(data, snapshot, current_time, getattr(policy, 'demand', {})):
            return None
        state['training'] = None
    share = data.items['EXP_SHARE']
    inventory = dict(snapshot.items)
    missing = shareless(data, snapshot)
    if missing and inventory.get(data.items['RED_SCALE']):
        return policy.person(snapshot, 'exp_share', 'Exchange the Red Scale for Exp. Share',
                             'MR_POKEMONS_HOUSE', 'MrPokemonsHouse_MrPokemonScript')
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    project = state.get('training')
    from .collection import prerequisites
    demand = getattr(policy, 'demand', {})
    if (project and not project.get('terminal') and project['target'] in snapshot.owned
            and project['target'] not in prerequisites(data, snapshot)
            and not requested(data, snapshot, demand, project['target'], item=bool(project.get('item')))):
        state['training'] = project = None
    if project and standing_down(policy, train_key(project['identity'])):
        state['training'] = project = None
    # A full party with every box full and nothing to release cannot swap anyone in at the PC, so
    # stored partners and a stored Exp. Share are out of reach. Plan only around the party then,
    # instead of walking to the PC to stand each stored partner down in turn.
    sealed = len(snapshot.party) >= 6 and bool(getattr(policy, 'no_room', lambda snapshot: False)(snapshot))
    if project is None:
        choices = projects(data, snapshot, current_time, demand)
        terminal_project = False
        if not choices and terminal:
            terminal_project = True
            choices = [(experience_at(100, data.species[mon.species]['growth']) - mon.experience,
                        mon.box is not None, mon.species, identity(mon), mon.species, None)
                       for mon in snapshot.party + snapshot.stored if not mon.egg and mon.level < 100]
        choices = [row for row in choices if not standing_down(policy, train_key(row[3]))
                   and not (row[1] and sealed)]
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
            return room_goal(policy, snapshot, Goal, share) or Goal(
                'collection_take', f'Hold {mon.name} back until the time of day suits',
                data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        state['training'] = None
        return None
    if mon.held_item == data.items['EVERSTONE']:
        state['take_slot'] = snapshot.party.index(mon) if mon.box is None else None
        if mon.box is None:
            return room_goal(policy, snapshot, Goal, mon.held_item) or Goal(
                'collection_take', 'Remove Everstone before evolution', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state['phase'] = 'evolving'
    if mon.box is not None and sealed:
        state['training'] = None
        return None
    # A carried egg with no spare beside it hatches first, so the swap never stores a field move holder.
    from .breeding import hatch_walk
    walk = hatch_walk(policy, snapshot)
    if mon.box is not None:
        if walk:
            return walk_goal(policy, snapshot, Goal, lambda: f'Walk to hatch the egg before {mon.name} joins')
        goal = policy.storage_goal(snapshot)
        return Goal('collection_train_pc', f'Prepare {mon.name} for training', goal.map_name, goal.x, goal.y, goal.face)
    if project['item']:
        return Goal('collection_evolve_item', f'Evolve {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    if not missing and share_blocked(data, snapshot, mon):
        # The bag has no entry for the item that moving the share hands back. Put a spare item in the PC first.
        held = mon.held_item if mon.held_item and not bag_takes(data, snapshot, mon.held_item) else share
        goal = room_goal(policy, snapshot, Goal, held)
        if goal:
            return goal
    if missing or share_blocked(data, snapshot, mon):
        # The cartridge's only Exp. Share is gone for good, or nothing in the full bag can be put away to make
        # room for the item that moving the share hands back, so the partner leads instead: the policy keeps
        # it in front and switches it out on the first turn of a battle it cannot win, which still splits the
        # experience with it.
        target = 'level ' + str(project.get('level_goal', 100)) if project.get('terminal') else data.species[project['target']]['name']
        return walk_goal(policy, snapshot, Goal, lambda: f'Train {mon.name} toward {target} in the lead')
    if mon.held_item != share:
        other = next((i for i, row in enumerate(snapshot.party) if row.held_item == share), None)
        if other is not None:
            state['take_slot'] = other
            return room_goal(policy, snapshot, Goal, share) or Goal(
                'collection_take', 'Pass Exp. Share to the next partner', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        if not inventory.get(share):
            holder = next((row for row in snapshot.stored if row.held_item == share), None)
            if holder and sealed:
                return None
            if holder and walk:
                return walk_goal(policy, snapshot, Goal, lambda: 'Walk to hatch the egg before fetching Exp. Share')
            if holder:
                state['share_holder'] = identity(holder)
                goal = policy.storage_goal(snapshot)
                return Goal('collection_train_pc', 'Retrieve Exp. Share from storage', goal.map_name, goal.x, goal.y, goal.face)
            return None
        return Goal('collection_equip', f'Give Exp. Share to {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state.pop('share_holder', None)
    target = 'level ' + str(project.get('level_goal', 100)) if project.get('terminal') else data.species[project['target']]['name']
    return walk_goal(policy, snapshot, Goal, lambda: f'Train {mon.name} toward {target}')


def walk_goal(policy, snapshot, Goal, label, *, map_name='SILVER_CAVE_ROOM_1'):
    """Walk encounter tiles, which trains the party and counts carried eggs down.

    ``label`` names the walk once the grass is known.
    """
    data = policy.data
    # Mt. Silver provides renewable experience for the trained champion and its partner.
    mid = data.map_ids[map_name]
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
        x, y = (9, 31) if map_name == 'SILVER_CAVE_ROOM_1' else points[0][:2]
    return Goal('collection_train', label(), map_name, x, y)


def arrive(policy, snapshot):
    state, data = policy.collection, policy.data
    project = state.get('training')
    if not project:
        return None
    wanted = state.get('share_holder') if policy.goal.key == 'collection_train_pc' else None
    wanted = wanted or project['identity']
    mon = next((row for row in snapshot.party + snapshot.stored if identity(row) == wanted), None)
    key = policy.goal.key
    if key == 'collection_tidy':
        item = state.get('tidy_item')
        count = dict(snapshot.items).get(item)
        if not count:
            state.pop('tidy_item', None)
            return 'b'
        # A full item PC refuses the deposit, and the policy then blocks it for a while. The item goes in
        # the bin instead, since it is the one worth least that no plan uses.
        task = PutAway(item, count)
        if not getattr(policy, 'allowed', lambda task, snapshot: True)(task, snapshot):
            task = Toss(item, count)
            if not policy.allowed(task, snapshot):
                return held_back(policy, task, project)
        policy.menu = task
        return 'a'
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
            from .breeding import carried
            counts = {move: sum(move in row.moves for row in snapshot.party) for move in FIELD_MOVES}
            # An egg only hatches in the party, so only the sole holder of a field move stays ahead of it,
            # and an egg brought out to hatch never goes back. The trainee stays too, or fetching its Exp.
            # Share would send it to the PC.
            keep = (project['identity'], wanted)
            slot = min(range(1, 6), key=lambda i: (carried(policy, snapshot, snapshot.party[i]), identity(snapshot.party[i]) in keep,
                                                   sum(counts[move] == 1 for move in snapshot.party[i].moves if move in FIELD_MOVES), snapshot.party[i].egg,
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
            task = Give(data.items['EXP_SHARE'], slot)
        elif key == 'collection_take':
            task = Take(state['take_slot'])
        elif key == 'collection_evolve_item':
            count = dict(snapshot.items).get(project['item'])
            if not count:
                # The stone was used or sold on the way, so this evolution has to be planned again.
                state['training'] = None
                return None
            task = Remedy(project['item'], slot, count)
        else:
            return 'wait' if key == 'collection_train' else None
        if not getattr(policy, 'allowed', lambda task, snapshot: True)(task, snapshot):
            return held_back(policy, task, project)
        policy.menu = task
        return 'wait'
    return None


def held_back(policy, task, project):
    """Wait out a refused item task, and stand the project down once the game keeps refusing it.

    The policy blocks a refused shortcut for a minute, and the plan would otherwise name it again the moment
    the block ends. Each block counts once, by the frame it ends on.
    """
    until = policy.blocked[policy.task_key(task)]
    refused = project.setdefault('refused', [])
    if until in refused:
        return 'wait'
    refused.append(until)
    if exhausted(policy, refusal_key(project['identity']), ITEM_REFUSALS):
        stand_down(policy, train_key(project['identity']))
        policy.collection['training'] = None
        return None
    return 'wait'


def refusal_key(identity):
    return 'refused:' + train_key(identity)


def observe(policy, snapshot):
    """Count each decision a training trip spends against its trainee. Experience the trainee gains is
    progress. A trip that spent three times its expected decisions without any stands down."""
    project = policy.collection.get('training')
    goal = getattr(policy, 'goal', None)
    if not project or goal is None or goal.key != 'collection_train':
        return
    mon = next((mon for mon in snapshot.party if identity(mon) == project['identity']), None)
    if mon is None:
        return
    events = ('experience',) if mon.experience > project.get('experience', mon.experience) else ()
    project['experience'] = mon.experience
    if events:
        project['gained'] = True
    if spend(policy, train_key(project['identity']), TRAINING_DECISIONS, events, progressed=project.get('gained', False)):
        policy.collection['training'] = None
