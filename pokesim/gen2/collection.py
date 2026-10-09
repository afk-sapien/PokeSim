"""Persistent postgame expeditions using version and time specific encounters."""
from .menus import ChangeBox, FieldMove, Teach, Use
from .navigation import DIRS
from .ram import Memory


def matching_time(value, current):
    return value in {'any', 'rare trees'} or current in value.split('/')


def waiting_label(policy, snapshot, mem, current_time):
    """Say what the idle collection is waiting for. The cartridge clock follows wall time, so a
    weekday or time of day that is not here yet can be hours or days of real time away."""
    from .contest import waiting_for_day
    label = waiting_for_day(policy, snapshot, mem)
    if label:
        return label
    if wanted(policy, snapshot, LAPRAS) and mem.byte('wCurDay') % 7 != FRIDAY:
        return 'Waiting for Friday: Lapras surfaces in Union Cave'
    later = sorted({row['time'] for row in policy.data.encounters
                    if wanted(policy, snapshot, row['species']) and not matching_time(row['time'], current_time)})
    if later:
        return f'Waiting for {" or ".join(later[:2])} to find new Pokémon'
    return 'Explore while waiting for new collection opportunities'


def tree_score(x, y, trainer_id):
    # Facing tile coordinates include the four tile map border in cartridge RAM.
    x, y = x + 4, y + 4
    return ((x * y + x + y) // 5 - trainer_id) % 10


def encounter_points(policy, snapshot, mid, method, *, rare=False):
    data = policy.data
    entry = data.maps[mid]
    grid = policy.nav.collision(snapshot, policy.memory) if mid == snapshot.map else policy.nav.regions.live.get(mid, entry['collision'])
    width, height = entry['width'], entry['height']
    points = []
    warps = {(warp['x'], warp['y']) for warp in entry['warps']}
    rocks = {(obj['x'], obj['y']) for index, obj in enumerate(entry['objects'], 1)
             if obj['sprite'] == 'SPRITE_ROCK' and index not in policy.nav.regions.cleared_rocks.get(mid, set())}
    trainer = Memory(policy.memory, data).word('wPlayerID') if method == 'headbutt' else 0
    for y in range(height):
        for x in range(width):
            tile = grid[y * width + x]
            if (x, y) in warps:
                continue
            if method in {'grass', 'surf'}:
                good = tile in (0x10, 0x14, 0x18, 0x1C) if method == 'grass' else tile in (0x21, 0x29)
                # The cartridge treats every floor tile of a cave or dungeon as an encounter tile.
                good |= method == 'grass' and entry['environment'] in {'CAVE', 'DUNGEON'} and tile == 0
                if good:
                    points.append((x, y, None))
            elif method.endswith('rod') and policy.nav.passable(tile):
                for face, (dx, dy) in DIRS.items():
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and grid[ny * width + nx] in (0x21, 0x29):
                        points.append((x, y, face))
            elif method in {'headbutt', 'rock smash'} and policy.nav.passable(tile):
                for face, (dx, dy) in DIRS.items():
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if method == 'rock smash':
                        good = (nx, ny) in rocks
                    else:
                        good = grid[ny * width + nx] in (0x15, 0x1D) and (tree_score(nx, ny, trainer) == 0) == rare
                    if good:
                        points.append((x, y, face))
    return points


UNOWN = 201
# Letters each solved Ruins of Alph puzzle unlocks, in wUnlockedUnowns bit order (pret data/wild/unlocked_unowns.asm).
UNOWN_SETS = (range(1, 12), range(12, 19), range(19, 24), range(24, 27))
LAPRAS, FRIDAY = 131, 5


def unown_letter(dvs):
    """Letter number, 1 for A to 26 for Z, from the two DV bytes (pret GetUnownLetter)."""
    first, second = dvs[0], dvs[1]
    value = ((first & 0x60) << 1) | ((first & 0x06) << 3) | ((second & 0x60) >> 3) | ((second & 0x06) >> 1)
    return value // 10 + 1


def unown_missing(policy, snapshot):
    """Unown letters the solved puzzles let appear but the Unown Pokédex still lacks."""
    if getattr(policy, 'memory', None) is None or 'wUnownDex' not in policy.data.symbols:
        return set()
    mem = Memory(policy.memory, policy.data)
    unlocked = mem.byte('wUnlockedUnowns')
    letters = {letter for bit, group in enumerate(UNOWN_SETS) if unlocked >> bit & 1 for letter in group}
    return letters - set(mem.read('wUnownDex', 26))


def wanted(policy, snapshot, species):
    held = sum(mon.species == species and not mon.egg for mon in snapshot.party + snapshot.stored)
    return (species not in snapshot.owned
            or species in policy.collection.get('prerequisites', ()) and not held
            or held < policy.demand.get(species, 0) + 1 and bool(policy.demand.get(species))
            or species == UNOWN and bool(unown_missing(policy, snapshot)))


def lapras(policy, snapshot, mem, Goal):
    """Meet the Union Cave Lapras, which surfaces on Fridays until the day's battle sets its flag."""
    if (not wanted(policy, snapshot, LAPRAS) or mem.byte('wCurDay') % 7 != FRIDAY
            or mem.byte('wDailyFlags2') & 2 or not snapshot.badges & 8
            or not snapshot.event('EVENT_GOT_HM03_SURF') or not snapshot.can_catch):
        policy.collection.pop('lapras', None)
        return None
    # Give up for the day if the meeting never happens, so other Friday work still gets done.
    started = policy.collection.setdefault('lapras', policy.decisions)
    if policy.decisions - started > 3000:
        return None
    if not any(57 in mon.moves or 57 in policy.data.species[mon.species]['machines']
               for mon in snapshot.party if not mon.egg):
        return None
    data = policy.data
    mid = data.map_ids['UNION_CAVE_B2F']
    entry = data.maps[mid]
    index, obj = next((i, obj) for i, obj in enumerate(entry['objects'], 1) if obj['script'] == 'UnionCaveLapras')
    # Objects are briefly missing right after a warp, so fall back to the spawn point.
    x, y = next(((x, y) for i, x, y in snapshot.objects if i == index), (obj['x'], obj['y'])) \
        if snapshot.map == mid else (obj['x'], obj['y'])
    grid = policy.nav.collision(snapshot, policy.memory) if snapshot.map == mid else entry['collision']
    choices = []
    for face, (dx, dy) in DIRS.items():
        px, py = x - dx, y - dy
        if not (0 <= px < entry['width'] and 0 <= py < entry['height']):
            continue
        if not policy.nav.passable(grid[py * entry['width'] + px], surf=True):
            continue
        if snapshot.map == mid:
            # Lapras swims around, so only a water tile reachable right now beside it will do.
            path = policy.nav.local(snapshot, [(px, py)], policy.memory, surf=True)
            if path is None:
                continue
            choices.append((len(path), px, py, face))
        else:
            # From afar, head for the side facing the western shore the player surfs out from.
            choices.append((px, px, py, face))
    if not choices:
        return Goal('collection_lapras', 'Find the Friday Lapras in Union Cave', 'UNION_CAVE_B2F', 4, 31)
    _, px, py, face = min(choices)
    return Goal('collection_lapras', 'Catch the Friday Lapras in Union Cave', 'UNION_CAVE_B2F', px, py, face)


def prerequisites(data, snapshot):
    """Find breeding and evolution partners that were collected but later traded away."""
    mons = snapshot.party + snapshot.stored + tuple(mon for mon in getattr(snapshot, 'daycare', ()) if mon)
    held = {mon.species for mon in mons}
    needed = set()
    for source, row in data.species.items():
        for evolution in row['evolutions']:
            if (evolution['species'] not in snapshot.owned
                    and not any(mon.species == source and (evolution['method'] in {'item', 'trade'} or mon.level < 100)
                                for mon in mons)):
                needed.add(source)
    babies = {172: {25, 26}, 173: {35, 36}, 174: {39, 40}, 236: {106, 107, 237},
              238: {124}, 239: {125}, 240: {126}}
    for baby, parents in babies.items():
        if baby not in snapshot.owned and not parents & held:
            needed.update(parents)
    if len(snapshot.owned) < 251 and 132 not in held:
        needed.add(132)
    return needed


def league_funding(policy, snapshot, Goal):
    """Run the Elite Four again for prize money, ending with a Hall of Fame entry."""
    if not policy.in_league(snapshot):
        if snapshot.event('EVENT_WILLS_ROOM_ENTRANCE_CLOSED'):
            return Goal('funds_arrive', 'Return to the League reception', 'INDIGO_PLATEAU_POKECENTER_1F', 17, 10)
        return policy.person(snapshot, 'funds_will', 'Challenge the League to fund the next expedition',
                             'WILLS_ROOM', 'WillScript_Battle')
    for trainer, room in [('WILL', 'WILLS'), ('KOGA', 'KOGAS'), ('BRUNO', 'BRUNOS'), ('KAREN', 'KARENS')]:
        if not snapshot.event(f'EVENT_BEAT_ELITE_4_{trainer}'):
            return policy.person(snapshot, 'funds_' + trainer.lower(), 'Continue the League expedition',
                                 room + '_ROOM', trainer.title() + 'Script_Battle')
    if not snapshot.event('EVENT_BEAT_CHAMPION_LANCE'):
        return policy.person(snapshot, 'funds_lance', 'Challenge Champion Lance again', 'LANCES_ROOM', 'LancesRoomLanceScript')
    return Goal('funds_champion', 'Record another League victory', 'HALL_OF_FAME', 4, 7)


def journey(policy, snapshot, mem, Goal):
    data, state = policy.data, policy.collection
    state['prerequisites'] = sorted(prerequisites(data, snapshot))
    from .contest import journey as contest
    if state.get('contest'):
        goal = contest(policy, snapshot, Goal)
        if goal:
            return goal
    from .tower import journey as tower
    if state.get('tower'):
        goal = tower(policy, snapshot, Goal)
        if goal:
            return goal
    if not snapshot.can_catch and not policy.in_league(snapshot):
        if any(count < 20 for count in snapshot.box_counts):
            goal = policy.storage_goal(snapshot)
            return Goal('collection_box', 'Make room for new catches', goal.map_name, goal.x, goal.y, goal.face)
    if not snapshot.event('EVENT_GOT_SUPER_ROD'):
        return policy.person(snapshot, 'super_rod', 'Get the Super Rod for the Pokédex expedition',
                             'ROUTE_12_SUPER_ROD_HOUSE', 'Route12SuperRodHouseFishingGuruScript')
    for flag, map_name, script, label in [
            ('EVENT_GOT_TM02_HEADBUTT', 'ILEX_FOREST', 'IlexForestHeadbuttGuyScript', 'Learn about Headbutt encounters'),
            ('EVENT_GOT_TM08_ROCK_SMASH', 'ROUTE_36', 'Route36RockSmashGuyScript', 'Learn about Rock Smash encounters')]:
        if not snapshot.event(flag):
            return policy.person(snapshot, flag.lower(), label, map_name, script)
    funding = state.get('funding')
    if funding is not None and snapshot.hall_of_fame_count >= funding:
        state.pop('funding', None)
        funding = None
    from .breeding import retrieval_cost
    fees = retrieval_cost(data, snapshot)
    from .. import config
    starter_gifts = getattr(config, 'LEAGUE_REWARDS', False) and not {152, 155, 158} <= snapshot.owned
    if funding is None and (snapshot.money < 5000 and sum(count for _, count in snapshot.pockets['balls']) < 4
                            or fees and snapshot.money < fees + 1000 or starter_gifts):
        state['funding'] = funding = snapshot.hall_of_fame_count + 1
    if funding is not None:
        state['phase'] = 'league'
        return league_funding(policy, snapshot, Goal)
    from .ruins import journey as ruins
    goal = ruins(policy, snapshot, Goal)
    if goal:
        return goal
    goal = lapras(policy, snapshot, mem, Goal)
    if goal:
        return goal
    from .quests import gifts
    gift = gifts(policy, snapshot, Goal)
    if gift:
        return gift
    from .quests import trade_items
    goal = trade_items(policy, snapshot, Goal)
    if goal:
        return goal
    if 'tower' not in policy.completed:
        goal = tower(policy, snapshot, Goal)
        if goal:
            return goal
    from .celebi import journey as celebi
    goal = celebi(policy, snapshot, Goal)
    if goal:
        return goal
    goal = contest(policy, snapshot, Goal)
    if goal:
        return goal
    from .breeding import journey as breed
    goal = breed(policy, snapshot, Goal)
    if goal:
        return goal
    from .gamecorner import journey as prizes
    goal = prizes(policy, snapshot, Goal)
    if goal:
        return goal
    from .quests import stones
    goal = stones(policy, snapshot, Goal)
    if goal:
        return goal
    from .training import journey as training
    goal = training(policy, snapshot, mem, Goal)
    if goal:
        return goal
    current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
    target = state.get('target')
    if (target and (not wanted(policy, snapshot, target['species']) or not matching_time(target['time'], current_time)
                   or policy.decisions - target['started'] > 12000)):
        state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
        state['target'] = target = None
    if target is None:
        from .quests import legends
        legend = legends(policy, snapshot, Goal)
        if legend:
            return legend
        groups = {}
        items = dict(snapshot.items)
        for row in data.encounters:
            if not wanted(policy, snapshot, row['species']) or not matching_time(row['time'], current_time):
                continue
            method = row['method']
            if method not in {'grass', 'surf', 'old rod', 'good rod', 'super rod', 'headbutt', 'rock smash'}:
                continue
            if method in {'headbutt', 'rock smash'}:
                move = 29 if method == 'headbutt' else 249
                machine = data.items['TM_HEADBUTT' if move == 29 else 'TM_ROCK_SMASH']
                if not any(move in mon.moves or machine in items and move in data.species[mon.species]['machines']
                           and not all(known in {15, 19, 57, 70, 148, 250, 127} for known in mon.moves)
                           for mon in snapshot.party if not mon.egg):
                    continue
            if method.endswith('rod') and data.items[method.upper().replace(' ', '_')] not in items:
                continue
            key = (row['map'], method, row['species'], row['time'] == 'rare trees')
            groups.setdefault(key, {**row, 'chance': 0})['chance'] += row['chance']
        routes, points = {}, {}
        choices = []
        distances = {}
        for mid, _, _, _ in groups:
            if mid not in distances:
                route = policy.nav.route(snapshot.map, mid)
                distances[mid] = len(route) if route is not None else 9999
        ranked = sorted(groups.items(), key=lambda pair: (not bool(policy.demand.get(pair[0][2])
                         or pair[0][2] in state['prerequisites']),
                         distances[pair[0][0]] + 50 / max(1, pair[1]['chance'])))
        for (mid, method, species, rare), row in ranked:
            if choices and len(choices) >= 12:
                break
            key = (mid, method, rare)
            if key not in points:
                points[key] = encounter_points(policy, snapshot, mid, method, rare=rare)
                routes[key] = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points[key]], cut=True, surf=True)
            route = routes[key]
            if route is None or not points[key]:
                continue
            attempted = state.get('attempts', {}).get(str(species), -100000)
            recent = policy.decisions - attempted < 18000
            choices.append((not bool(policy.demand.get(species) or species in state['prerequisites']),
                            species in snapshot.owned, recent,
                            len(route) + 50 / max(1, row['chance']), species, mid, method, row))
        if choices:
            target = dict(min(choices, key=lambda row: row[:-1])[-1], started=policy.decisions)
            state['target'] = target
        else:
            goal = tower(policy, snapshot, Goal)
            if goal:
                return goal
            goal = training(policy, snapshot, mem, Goal, terminal=True)
            if goal:
                return goal
            state['phase'] = 'waiting'
            return Goal('collection_wait', waiting_label(policy, snapshot, mem, current_time), 'ROUTE_29', 12, 8)
    return hunt(policy, snapshot, Goal)


def hunt(policy, snapshot, Goal):
    data, state = policy.data, policy.collection
    target = state['target']
    state['phase'] = 'hunting'
    mid, method = target['map'], target['method']
    points = encounter_points(policy, snapshot, mid, method, rare=target['time'] == 'rare trees')
    if not points:
        state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
        state['target'] = None
        return Goal('collection_wait', 'Replan the Pokédex expedition', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    if mid == snapshot.map:
        candidates = []
        ordered = sorted(points, key=lambda point: (abs(point[0] - snapshot.x) + abs(point[1] - snapshot.y),
                         policy.nav.visits.get((mid, point[0], point[1]), 0)))
        for x, y, face in ordered:
            if (x, y) == (snapshot.x, snapshot.y) and method in {'grass', 'surf'}:
                continue
            path = policy.nav.local(snapshot, [(x, y)], policy.memory, surf=True)
            if path is not None:
                visits = policy.nav.visits.get((mid, x, y), 0)
                candidates.append((len(path), visits, x, y, face))
                if len(candidates) >= 4:
                    break
        if candidates:
            _, _, x, y, face = min(candidates, key=lambda row: row[:4])
        else:
            route = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
            if route:
                region = route[-1][1][1]
                x, y, face = next((point for point in points
                                   if region in policy.nav.regions.memberships(mid, point[:2], True, True)), points[0])
            else:
                state.setdefault('attempts', {})[str(target['species'])] = policy.decisions
                state['target'] = None
                return Goal('collection_wait', 'Replan the Pokédex expedition', data.maps[mid]['constant'], snapshot.x, snapshot.y)
    else:
        route = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
        region = route[-1][1][1] if route else None
        x, y, face = next((point for point in points
                           if region in policy.nav.regions.memberships(mid, point[:2], True, True)), points[0])
    name = data.species[target['species']]['name']
    key = 'collection_fish' if method.endswith('rod') else 'collection_field' if method in {'headbutt', 'rock smash'} else 'collection_hunt'
    return Goal(key,
                f'Search for {name} in {data.maps[mid]["name"]}', data.maps[mid]['constant'], x, y, face)


def arrive(policy, snapshot):
    key = policy.goal.key
    from .gamecorner import arrive as prize
    result = prize(policy, snapshot)
    if result is not None:
        return result
    from .teams import arrive as team
    result = team(policy, snapshot)
    if result is not None:
        return result
    from .breeding import arrive as breed
    result = breed(policy, snapshot)
    if result is not None:
        return result
    from .quests import arrive as gift
    result = gift(policy, snapshot)
    if result is not None:
        return result
    from .training import arrive as train
    result = train(policy, snapshot)
    if result is not None:
        return result
    if key == 'collection_box':
        box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is not None:
            policy.menu = ChangeBox(box)
            return 'a'
    if key == 'collection_fish':
        method = policy.collection['target']['method']
        policy.menu = Use(policy.data.items[method.upper().replace(' ', '_')])
        return 'wait'
    if key == 'collection_field':
        method = policy.collection['target']['method']
        move = 29 if method == 'headbutt' else 249
        slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg and move in mon.moves), None)
        if slot is None:
            slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg
                         and move in policy.data.species[mon.species]['machines']
                         and not all(known in {15, 19, 57, 70, 148, 250, 127} for known in mon.moves)), None)
            if slot is not None:
                policy.menu = Teach(move, slot)
        else:
            policy.menu = FieldMove(slot, 'HEADBUTT' if move == 29 else 'ROCK SMASH')
        return 'wait'
    if key in {'collection_wait', 'collection_hunt'}:
        return 'wait'
    return None
