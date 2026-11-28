"""Raise collected partners through normal battles, held items and evolution."""
from dataclasses import replace

from .menus import ChangeBox, Give, PutAway, Release, Remedy, Storage, Take, Toss
from pokecore.gen2.ram import calculated_stats, experience_at
from pokecore.identity import family
from ..planning.ledger import FIELD_MOVES
from ..planning.stance import TRAIN
from .facts import facts
from .ledger import fight_room, fits, members_room, tidy_goal
from .standdown import TRAINING_DECISIONS, exhausted, site_key, spend, stand_down, standing_down, train_key
from . import kinds

# Mt. Silver provides renewable experience for the trained champion and its partner.
SITE = 'SILVER_CAVE_ROOM_1'
# Maps beside the project's own that a training project may fall back on.
SITES = 8


def identity(mon):
    return [mon.trainer_id, list(mon.dvs)]


def find(mons, key, species=None):
    """The first of ``mons`` with the trainer ID and DVs in ``key``, or None.

    Two Pokémon can share both, as a Rhydon and an Electrode in a Crystal party did (#705). A known
    species picks among them: that species first, then another of its evolution family, which is what
    the Pokémon becomes when it evolves. A Pokémon of another family never answers.
    """
    root = None if species is None else family(species)
    first = None
    for mon in mons:
        if identity(mon) == key and (root is None or family(mon.species) == root):
            if species is None or mon.species == species:
                return mon
            first = first or mon
    return first


def wild_levels(policy):
    """The top wild level of each map whose cartridge wild table has walking encounters (grass or cave floor).

    Callers only read it. It is kept in the facts until ``data.encounters`` is replaced, as loading a
    cartridge's own table does, since the rows are never changed in place.
    """
    return facts(policy).answer('wild levels', (policy.data.encounters,), _wild_levels, policy.data.encounters)


def _wild_levels(encounters):
    top = {}
    for row in encounters:
        if row['method'] == 'grass':
            top[row['map']] = max(top.get(row['map'], 0), row['level'])
    return top


def field_moves(snapshot):
    """Whether Cut and Surf open the way, as they do for the walk itself, which needs the badge and a party
    member that knows the move. With the badge alone, a Gold run aimed at Route 34 past the tree in Ilex
    Forest before it had Cut, found no route on the walk and stalled."""
    cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
    surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
    return cut, surf


def walk_points(policy, snapshot, mid):
    """The encounter tiles of map ``mid`` the player can reach from here.

    Empty when the map's cartridge wild table has no walking encounters. A cave counts every floor tile,
    and the floor outside its walls is out of reach: a first League trip once aimed at Victory Road's top
    left corner, found no route and stood in Mr. Pokémon's House for hours.
    """
    from .collection import encounter_points
    if mid not in wild_levels(policy):
        return []
    points = encounter_points(policy, snapshot, mid, 'grass')
    if not points:
        return []
    regions = policy.nav.regions
    cut, surf = field_moves(snapshot)
    if regions.between(snapshot, cut, surf):
        # Nothing can be judged until the player lands, so every tile counts for now. A Crystal run judged
        # from a ledge jump outside the Silver Cave, ended training and stood down one trainee after another.
        return points
    if snapshot.map == mid:
        wanted = regions.memberships(mid, (snapshot.x, snapshot.y), cut, surf, arrive=True)
    else:
        route = regions.route(snapshot, mid, [point[:2] for point in points], cut=cut, surf=surf)
        if not route:
            return []
        wanted = {route[-1][1][1]}
    return [point for point in points if wanted & regions.memberships(mid, point[:2], cut, surf)]


def site(policy, snapshot, project, mon):
    """The map a training project walks, or None when no map can still train ``mon``.

    The project's own map comes first, then every other map with walking encounters in the cartridge's
    wild table, the highest wild level the party's best member still outlevels first. Every wild battle
    a Gen II party wins pays experience, so a map can train any trainee under level 100. A map is left out
    once a whole stint there gave no experience (observe), or when none of its encounter tiles can be
    reached from here.
    """
    if mon.level >= 100:
        return None
    data = policy.data
    top = wild_levels(policy)
    usable =lambda mid: mid in top and not standing_down(policy, site_key(mid))
    first = data.map_ids[project.get('map') or SITE]
    # On the map itself, the walk waits there while its collision loads (walk_goal).
    if usable(first) and (snapshot.map == first or walk_points(policy, snapshot, first)):
        return data.maps[first]['constant']
    best = max((row.level for row in snapshot.party if not row.egg), default=0)
    others = sorted((mid for mid in top if mid != first), key=lambda mid: (top[mid] > best, -top[mid]))
    return next((data.maps[mid]['constant'] for mid in others[:SITES]
                 if usable(mid) and walk_points(policy, snapshot, mid)), None)


def shareless(data, snapshot):
    """Whether the cartridge has lost its only Exp. Share, which no shop or person hands out again."""
    share = data.items['EXP_SHARE']
    return not dict(snapshot.items).get(share) and not any(mon.held_item == share for mon in snapshot.party + snapshot.stored)


# Refusals of one training project's item task before the project stands down. The monitor keeps the count.
ITEM_REFUSALS = 3


def share_room(data, snapshot, mon):
    """The item that moving the Exp. Share to ``mon`` hands back and the bag has no room for, or None.

    Giving the share to a Pokémon that holds something else puts that item in the bag, and taking the share
    from another party member puts the share there. Either one needs room the ledger has to find.
    """
    share = data.items['EXP_SHARE']
    if mon.held_item == share:
        return None
    back = [mon.held_item] if mon.held_item else []
    if any(row is not mon and row.held_item == share for row in snapshot.party):
        back.append(share)
    return next((item for item in back if not fits(data, snapshot, item)), None)


def trainee_index(policy, snapshot):
    """The party slot of the Pokémon the training project raises, or None."""
    project = policy.collection.get('training')
    if not project:
        return None
    mon = find((mon for mon in snapshot.party if not mon.egg), project['identity'], project.get('species'))
    return None if mon is None else snapshot.party.index(mon)


def trainee_slot(policy, snapshot):
    """The party slot of a partner levelling without an Exp. Share, which leads so it joins every battle."""
    project = policy.collection.get('training')
    if not project or project.get('item'):
        return None
    slot = trainee_index(policy, snapshot)
    if slot is None or not (shareless(policy.data, snapshot) or share_room(policy.data, snapshot, snapshot.party[slot])):
        return None
    return slot


# Levels a fighter on the training walk keeps over the site's top wild level. A trainee this far above its
# opponent fights the battle out rather than switch (Policy.trainee_switch).
LEAD_MARGIN = 5


def walk_fighters(policy, snapshot):
    """The party slots that can fight on the training walk, each with its room (ledger.fight_room), or
    None to leave the heal walk and the lead to their usual rules.

    A fighter has room left and a level at least LEAD_MARGIN above the top wild level of the map the walk
    trains on, so a wild battle there costs it little. None off the training walk and when no member
    stands that far above the map, where any member's wear still sends the party to heal (ledger.battle_room).
    Callers pass the party as the field cures in the bag leave it (ledger.cured), as the heal check reads it.
    """
    goal = policy.goal
    if goal is None or goal.key != 'collection_train' or not policy.collection.get('training'):
        return None
    data = policy.data
    top = wild_levels(policy).get(data.map_ids.get(goal.map_name))
    if top is None:
        return None
    party = snapshot.party
    tall = [i for i, mon in enumerate(party) if not mon.egg and mon.level >= top + LEAD_MARGIN]
    if not tall:
        return None
    rooms = {i: fight_room(data, party[i]) for i in tall}
    return {i: room for i, room in rooms.items() if room}


def training_spent(policy, snapshot):
    """Whether the training walk needs a Pokémon Center, or None to leave it to the usual rule (walk_fighters).

    It does once no fighter is left, or once the trainee has fainted, since a fainted Pokémon gains no
    experience. A trainee that leads without an Exp. Share (trainee_slot) gains only from its own battles,
    so its own wear still sends the party to heal. A partner's wear alone does not while another can fight.
    """
    able = walk_fighters(policy, snapshot)
    if able is None:
        return None
    if not able:
        return True
    slot = trainee_index(policy, snapshot)
    if slot is None:
        return False
    mon = snapshot.party[slot]
    if slot == trainee_slot(policy, snapshot):
        return 0 in members_room(policy.data, [mon]).values()
    return not mon.hp


def training_lead(policy, snapshot):
    """The party slot that leads the training walk, or None to leave the lead to the usual rule.

    The trainee leads while it is a fighter (walk_fighters), so it gains a participant's share of each
    battle on top of the Exp. Share's. Otherwise the lead keeps its place while it is a fighter, and a worn
    lead gives way to the fighter with the most room. None off the training walk and once no fighter is
    left, when the party is due at a Pokémon Center.
    """
    able = walk_fighters(policy, snapshot)
    if not able:
        return None
    trainee = trainee_index(policy, snapshot)
    if trainee in able:
        return trainee
    if 0 in able:
        return 0
    return max(able, key=able.get)


def happiness_levels(friendship):
    """Level ups needed to reach evolution friendship, using the cartridge's +5, +3 and +2 tiers."""
    levels = 0
    while friendship < 220:
        friendship += 5 if friendship < 100 else 3 if friendship < 200 else 2
        levels += 1
    return levels


def requested(data, snapshot, demand, species, *, source=None):
    """Whether cable demand wants another evolved copy of a family with no wild source.

    An item evolution of ``source`` makes a copy for a peer even when the family has a wild source,
    if no copy here could travel: automatic trading keeps a trained partner, so a single veteran
    never leaves. The new copy must be able to travel itself, or it is one more veteran.
    """
    from pokecore.gen2.breeding import single_source
    copies = [mon for mon in snapshot.party + snapshot.stored if mon.species == species and not mon.egg]
    if not demand.get(species):
        return False
    if species in single_source(data) and len(copies) <= demand[species]:
        return True
    return (source is not None and could_travel(source)
            and not any(spare_copy(data, mon) for mon in copies))


def could_travel(mon):
    """Whether nothing lasting keeps this copy from automatic trading. Its shine, its DVs and its
    stat experience stay through evolution and the PC, as the rules of trading._kept read them."""
    return not mon.shiny and tuple(mon.dvs) != (15,) * 5 and sum(mon.stat_exp) < 20000


def spare_copy(data, mon):
    """Whether automatic trading could offer this copy, the rules of trading._kept that a snapshot shows."""
    return mon.box is not None and mon.held_item != data.items['EXP_SHARE'] and could_travel(mon)


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


def projects(policy, snapshot, current_time, demand=None):
    from .collection import prerequisites
    data, needed = policy.data, prerequisites(policy, snapshot)
    demand = demand or {}
    inventory = dict(snapshot.items)
    rows = []
    for mon in snapshot.party + snapshot.stored:
        if mon.egg:
            continue
        for evo in data.species[mon.species]['evolutions']:
            if (evo['species'] in snapshot.owned and evo['species'] not in needed
                    and not requested(data, snapshot, demand, evo['species'],
                                      source=mon if evo['method'] == 'item' else None)
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


def kept_projects(policy, snapshot, current_time):
    """``projects`` for this policy, kept in its facts until what it reads changes.

    It reads the party, the boxes, the bag, the Pokédex, the time of day, the demand and the prerequisites.
    The prerequisites go in as their answer, since they also read the Day Care, whose Pokémon gain
    experience as the player walks. The snapshot's regions and the prerequisites are frozen, and the
    demand goes in as a copy, so nothing in the key is edited in place.
    """
    from .collection import prerequisites
    demand = getattr(policy, 'demand', None) or {}
    inputs = (snapshot.party, snapshot.stored, snapshot.items, snapshot.owned, current_time,
              tuple(sorted(demand.items())), prerequisites(policy, snapshot))
    return list(facts(policy).answer('training projects', inputs,
                                     lambda: projects(policy, snapshot, current_time, demand)))


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
        if not kept_projects(policy, snapshot, current_time):
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
            and project['target'] not in prerequisites(policy, snapshot)):
        source = find(snapshot.party + snapshot.stored, project['identity'],
                      project.get('species')) if project.get('item') else None
        if not requested(data, snapshot, demand, project['target'], source=source):
            state['training'] = project = None
    if project and standing_down(policy, train_key(project['identity'])):
        state['training'] = project = None
    # A full party with every box full and nothing to release cannot swap anyone in at the PC, so
    # stored partners and a stored Exp. Share are out of reach. Plan only around the party then,
    # instead of walking to the PC to stand each stored partner down in turn.
    sealed = len(snapshot.party) >= 6 and bool(getattr(policy, 'no_room', lambda snapshot: False)(snapshot))
    if project is None:
        choices = kept_projects(policy, snapshot, current_time)
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
        project = state['training'] = kinds.project(
            {'identity': key, 'target': target, 'item': item, 'species': species, 'terminal': terminal_project})
    mon = find(snapshot.party + snapshot.stored, project['identity'], project.get('species'))
    if (mon is None or mon.species != project['species'] and not project.get('terminal')
            or not project.get('item') and mon.level >= project.get('level_goal', 100)):
        state['training'] = None
        return None
    if project.get('terminal'):
        project = state['training'] = project.replace(species=mon.species, target=mon.species)
    # Every walk heads for a map the cartridge has wild Pokémon on, and a project with nowhere left to
    # train ends.
    place = None if project['item'] else site(policy, snapshot, project, mon)
    if place is None and not project['item']:
        state['training'] = None
        return None
    project = state['training'] = project.replace(site=place)
    spot = {'map_name': place} if place else {}
    evo = next((evo for evo in data.species[mon.species]['evolutions'] if evo['species'] == project['target']), None)
    if (evo and not project.get('terminal') and wrong_time(evo, current_time)
            and happiness_levels(mon.friendship) <= 1 and mon.held_item != data.items['EVERSTONE']):
        # The next level brings evolution friendship, and Espeon needs morning or day while Umbreon needs
        # night. Exp. Share would level this Eevee in any battle, so it waits without the share.
        if mon.box is None and mon.held_item == share:
            state['take_slot'] = snapshot.party.index(mon)
            return tidy_goal(policy, snapshot, Goal, share) or Goal(
                'collection_take', f'Hold {mon.name} back until the time of day suits',
                data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        state['training'] = None
        return None
    if mon.held_item == data.items['EVERSTONE']:
        state['take_slot'] = snapshot.party.index(mon) if mon.box is None else None
        if mon.box is None:
            return tidy_goal(policy, snapshot, Goal, mon.held_item) or Goal(
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
            return walk_goal(policy, snapshot, Goal, lambda: f'Walk to hatch the egg before {mon.name} joins', **spot)
        goal = policy.storage_goal(snapshot)
        return replace(goal, key='collection_train_pc', label=f'Prepare {mon.name} for training')
    if project['item']:
        return Goal('collection_evolve_item', f'Evolve {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    blocked = share_room(data, snapshot, mon)
    if not missing and blocked:
        # The bag has no entry for the item that moving the share hands back. Put a spare item in the PC first.
        goal = tidy_goal(policy, snapshot, Goal, blocked)
        if goal:
            return goal
    if missing or blocked:
        # The cartridge's only Exp. Share is gone for good, or nothing in the full bag can be put away to make
        # room for the item that moving the share hands back, so the partner leads instead: the policy keeps
        # it in front and switches it out on the first turn of a battle it cannot win, which still splits the
        # experience with it.
        target = 'level ' + str(project.get('level_goal', 100)) if project.get('terminal') else data.species[project['target']]['name']
        return walk_goal(policy, snapshot, Goal, lambda: f'Train {mon.name} toward {target} in the lead', **spot)
    if mon.held_item != share:
        other = next((i for i, row in enumerate(snapshot.party) if row.held_item == share), None)
        if other is not None:
            state['take_slot'] = other
            return tidy_goal(policy, snapshot, Goal, share) or Goal(
                'collection_take', 'Pass Exp. Share to the next partner', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
        if not inventory.get(share):
            holder = next((row for row in snapshot.stored if row.held_item == share), None)
            if holder and sealed:
                return None
            if holder and walk:
                return walk_goal(policy, snapshot, Goal, lambda: 'Walk to hatch the egg before fetching Exp. Share', **spot)
            if holder:
                state['share_holder'] = identity(holder)
                goal = policy.storage_goal(snapshot)
                return replace(goal, key='collection_train_pc', label='Retrieve Exp. Share from storage')
            return None
        return Goal('collection_equip', f'Give Exp. Share to {mon.name}', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    state.pop('share_holder', None)
    target = 'level ' + str(project.get('level_goal', 100)) if project.get('terminal') else data.species[project['target']]['name']
    return walk_goal(policy, snapshot, Goal, lambda: f'Train {mon.name} toward {target}', **spot)


def walk_goal(policy, snapshot, Goal, label, *, map_name=SITE):
    """Walk encounter tiles, which trains the party and counts carried eggs down.

    ``label`` names the walk once the grass is known. None when no encounter tile of the map can be reached.
    """
    data = policy.data
    # A ledge jump neither starts a walk nor ends one under way, since nothing can be judged until the player
    # lands (walk_points). A Crystal run that jumped the ledge on Route 33 with a story goal under way walked
    # toward Route 34 for that one step, past the tree in Ilex Forest it had no Cut for (#786).
    if getattr(policy.goal, 'key', None) != 'collection_train' and policy.nav.regions.between(snapshot, *field_moves(snapshot)):
        return None
    mid = data.map_ids[map_name]
    points = walk_points(policy, snapshot, mid)
    if not points and snapshot.map != mid:
        return None
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
    return Goal('collection_train', label(), map_name, x, y, kind=TRAIN)


def arrive(policy, snapshot):
    state, data = policy.collection, policy.data
    project = state.get('training')
    if not project:
        return None
    wanted = state.get('share_holder') if policy.goal.key == 'collection_train_pc' else None
    # The fetch goes by the item as well. Copies alike in trainer and DVs all answer to the holder's
    # identity, and one already in the party ended each fetch before the holder came out: a Silver run
    # went back to the PC for three days for an Exp. Share on one of four such Aerodactyl (issue #113).
    share = data.items['EXP_SHARE']
    mon = next((row for row in snapshot.party + snapshot.stored
                if wanted and row.held_item == share and identity(row) == wanted), None)
    species = None if wanted else project.get('species')
    wanted = wanted or project['identity']
    mon = mon or find(snapshot.party + snapshot.stored, wanted, species)
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
    mon = find(snapshot.party, project['identity'], project.get('species'))
    if mon is None:
        return
    events = ('experience',) if mon.experience > project.get('experience', mon.experience) else ()
    project['experience'] = mon.experience
    if events:
        project['gained'] = True
    if spend(policy, train_key(project['identity']), TRAINING_DECISIONS, events, progressed=project.get('gained', False)):
        # A whole stint without experience means the site cannot train, so the next trainee
        # does not take the same walk. The stand-down counts as one failed attempt there.
        site_failed(policy, project)
        policy.collection['training'] = None


def site_failed(policy, project):
    """Stand down the site of a training stint that gained no experience at all."""
    if project.get('site') and not project.get('gained'):
        stand_down(policy, site_key(policy.data.map_ids[project['site']]))
