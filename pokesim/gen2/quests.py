"""Postgame gifts and legendary encounters driven by cartridge quest flags."""
from .menus import ChangeBox, FieldMove, ShowPartner, Storage, Teach
from .training import FIELD_MOVES


def room_for_gift(policy, snapshot, Goal):
    if len(snapshot.party) < 6:
        return None
    goal = policy.storage_goal(snapshot)
    return Goal('collection_gift_room', 'Make room for a new partner', goal.map_name, goal.x, goal.y, goal.face)


def gifts(policy, snapshot, Goal):
    data = policy.data
    if not snapshot.event('EVENT_GOT_MASTER_BALL_FROM_ELM'):
        return policy.person(snapshot, 'gift_master_ball', 'Receive Elm’s Master Ball', 'ELMS_LAB', 'ProfElmScript')
    if not snapshot.event('EVENT_GOT_EEVEE'):
        if snapshot.event('EVENT_MET_BILL'):
            return Goal('meet_bill', 'Meet Bill in Ecruteak', 'ECRUTEAK_POKECENTER_1F', 4, 5)
        return room_for_gift(policy, snapshot, Goal) or policy.person(snapshot, 'gift_eevee', 'Receive Eevee from Bill',
            'BILLS_FAMILYS_HOUSE', 'BillScript')
    if data.game == 'crystal' and not snapshot.event('EVENT_GOT_ODD_EGG'):
        return room_for_gift(policy, snapshot, Goal) or policy.person(snapshot, 'gift_odd_egg', 'Receive the Day Care’s Odd Egg',
            'DAY_CARE', 'DayCareManScript_Inside')
    if data.game == 'crystal' and not snapshot.event('EVENT_GOT_DRATINI'):
        return room_for_gift(policy, snapshot, Goal) or policy.person(snapshot, 'gift_dratini', 'Receive the Dragon Master’s Dratini',
            'DRAGON_SHRINE', 'DragonShrineElder1Script')
    if not snapshot.event('EVENT_GOT_TYROGUE_FROM_KIYO'):
        return room_for_gift(policy, snapshot, Goal) or policy.person(snapshot, 'gift_tyrogue', 'Meet Kiyo in Mt. Mortar',
            'MOUNT_MORTAR_B1F', 'MountMortarB1FKiyoScript')
    return None


def legends(policy, snapshot, Goal):
    from .celebi import journey
    celebi = journey(policy, snapshot, Goal)
    if celebi:
        return celebi
    # A walking return makes an owned legendary worth another capture.
    owned = snapshot.owned - getattr(policy, 'returned', set())
    if {243, 244, 245, 249, 250} <= owned:
        return None
    data = policy.data
    policy.collection['phase'] = 'legendary'
    if not snapshot.can_catch:
        goal = policy.storage_goal(snapshot)
        return Goal('collection_box', 'Make room for the legendary encounter', goal.map_name, goal.x, goal.y, goal.face)
    if not snapshot.event('EVENT_GOT_MASTER_BALL_FROM_ELM'):
        return policy.person(snapshot, 'gift_master_ball', 'Receive Elm’s Master Ball', 'ELMS_LAB', 'ProfElmScript')
    if data.game != 'crystal' and not snapshot.event('EVENT_RELEASED_THE_BEASTS'):
        tower = data.map_ids['BURNED_TOWER_1F']
        if snapshot.map != data.map_ids['BURNED_TOWER_B1F'] and 3 not in policy.nav.regions.cleared_rocks.get(tower, set()):
            if not snapshot.event('EVENT_GOT_TM08_ROCK_SMASH'):
                return policy.person(snapshot, 'rock_smash', 'Prepare to explore the Burned Tower',
                                     'ROUTE_36', 'Route36RockSmashGuyScript')
            return Goal('collection_release_rock', 'Clear the Burned Tower passage', 'BURNED_TOWER_1F', 4, 4, 'up')
        return Goal('release_beasts', 'Awaken the legendary beasts in the Burned Tower', 'BURNED_TOWER_B1F', 9, 5)
    items = dict(snapshot.items)
    wing = 'RAINBOW_WING' if data.game == 'silver' else 'SILVER_WING'
    if data.items[wing] not in items:
        return policy.person(snapshot, 'pewter_wing', 'Hear the old man’s story in Pewter', 'PEWTER_CITY', 'PewterCityGrampsScript')
    if data.game == 'crystal' and not snapshot.event('EVENT_FOUGHT_SUICUNE'):
        if not snapshot.event('EVENT_KOJI_ALLOWS_YOU_PASSAGE_TO_TIN_TOWER'):
            if (snapshot.map == data.map_ids['ECRUTEAK_TIN_TOWER_ENTRANCE']
                    and snapshot.x < 10 and snapshot.y >= 6
                    and not snapshot.event('EVENT_TEMPORARY_UNTIL_MAP_RELOAD_1')):
                return policy.person(snapshot, 'clear_bell', 'Show the Clear Bell to the tower’s guardian',
                                     'ECRUTEAK_TIN_TOWER_ENTRANCE', 'EcruteakTinTowerEntranceSageScript')
            for trainer in ('GAKU', 'MASA', 'KOJI'):
                if not snapshot.event(f'EVENT_BEAT_SAGE_{trainer}'):
                    return policy.person(snapshot, 'sage_' + trainer.lower(), 'Pass the Wise Trio’s test',
                                         'WISE_TRIOS_ROOM', 'TrainerSage' + trainer.title())
        return static_lead(policy, snapshot, 245, Goal) or Goal('legend_suicune', 'Meet Suicune at the Tin Tower', 'TIN_TOWER_1F', 9, 12)
    if 249 not in owned and not snapshot.event('EVENT_FOUGHT_LUGIA') and ball_ready(policy, snapshot):
        return (static_lead(policy, snapshot, 249, Goal)
                or policy.person(snapshot, 'legend_lugia', 'Seek Lugia in the Whirl Islands', 'WHIRL_ISLAND_LUGIA_CHAMBER', 'Lugia'))
    if (data.game == 'crystal' and 250 not in snapshot.owned
            and {243, 244, 245} <= snapshot.owned and data.items['RAINBOW_WING'] not in items):
        return policy.person(snapshot, 'rainbow_wing', 'Return to the Tin Tower with the three beasts',
                             'TIN_TOWER_1F', 'TinTower1FSage5Script')
    if (250 not in owned and data.items['RAINBOW_WING'] in items and not snapshot.event('EVENT_FOUGHT_HO_OH')
            and ball_ready(policy, snapshot)):
        return (static_lead(policy, snapshot, 250, Goal)
                or policy.person(snapshot, 'legend_ho_oh', 'Seek Ho-Oh above the Tin Tower', 'TIN_TOWER_ROOF', 'TinTowerHoOh'))
    return roamers(policy, snapshot, Goal)


# Where a roaming beast may go next from each route (pret data/wild/roammon_maps.asm, the same in all three games).
ROAM_MAPS = {
    29: (30, 46), 30: (29, 31), 31: (30, 32, 36), 32: (36, 31, 33), 33: (32, 34), 34: (33, 35),
    35: (34, 36), 36: (35, 31, 32, 37), 37: (36, 38, 42), 38: (37, 39, 42), 39: (38,),
    42: (43, 44, 37, 38), 43: (42, 44), 44: (42, 43, 45), 45: (44, 46), 46: (45, 29),
}


def roam_neighbours(data, mid):
    """Maps a roamer standing on mid can move to when the player next crosses a map connection."""
    name = data.maps.get(mid, {}).get('constant', '')
    if not name.startswith('ROUTE_') or not name[6:].isdigit() or int(name[6:]) not in ROAM_MAPS:
        return ()
    return tuple(data.map_ids[f'ROUTE_{route}'] for route in ROAM_MAPS[int(name[6:])])


def roamer_speed(policy, species, level):
    """The roaming beast's Speed, from its stored DVs once it has been met, else the highest possible.

    Roamers carry no stat experience, and the cartridge keeps their DVs in the roam struct after the
    first encounter, so the Speed stat is exact from then on.
    """
    from .ram import Memory
    dv = 15
    if policy.memory is not None and 'wRoamMon1' in policy.data.symbols:
        mem = Memory(policy.memory, policy.data)
        for index in (1, 2, 3):
            raw = mem.read(f'wRoamMon{index}', 7)
            if raw[0] == species and (raw[5] or raw[6]):
                dv = raw[6] >> 4
    return (policy.data.species[species]['stats'][3] + dv) * 2 * level // 100 + 5


def sleep_move(data, mon, species):
    """The most accurate sleep move this Pokémon can still use on the given species, as (accuracy, move)."""
    moves = [(data.moves[move]['accuracy'], move) for move, pp in zip(mon.moves, mon.pp)
             if pp and data.moves.get(move, {}).get('effect') == 'EFFECT_SLEEP'
             and all(data.matchups.get((data.moves[move]['type'], kind), 1) for kind in data.species[species]['types'])]
    return max(moves, default=None)


def roam_lead(policy, snapshot, wanted):
    """Pick the Pokémon that should lead against the roaming beasts, and the level it needs.

    A roaming beast flees on its first turn before the player can act, unless the player's Pokémon
    moves first. A faster lead that puts it to sleep stops the flight (TryEnemyFlee keeps a sleeping
    or frozen opponent in battle), and sleep is also the only status that raises the catch chance in
    Gen II. Mean Look or Spider Web on the same lead keeps the beast from leaving after it wakes. Only
    sleep counts on the roamer: switching in a sleeper resets Mean Look and gives the beast its turn.
    """
    from .ram import calculated_stats, experience_at
    data = policy.data
    need = max(roamer_speed(policy, roamer['species'], roamer['level']) for roamer in wanted)
    options = []
    for mon in snapshot.party + snapshot.stored:
        if mon.egg or mon.species not in data.species:
            continue
        sleep = [sleep_move(data, mon, roamer['species']) for roamer in wanted]
        if None in sleep:
            continue
        base = data.species[mon.species]['stats']
        level = mon.level
        while level <= 100 and calculated_stats(base, level, mon.dvs, mon.stat_exp)[3] <= need:
            level += 1
        if level > 100:
            continue
        cost = max(0, experience_at(level, data.species[mon.species]['growth']) - mon.experience)
        trap = any(pp and data.moves.get(move, {}).get('effect') == 'EFFECT_MEAN_LOOK' for move, pp in zip(mon.moves, mon.pp))
        options.append(((cost, not trap, -min(sleep)[0], mon.box is not None, mon.level), mon, level))
    if not options:
        return None
    _, mon, level = min(options, key=lambda row: row[0])
    return mon, level


def prepare_lead(policy, snapshot, wanted, Goal):
    """Train, withdraw and lead with the roamer sleeper. None once it leads the party."""
    from .menus import Lead
    from .ram import Memory
    from .teams import assemble, key
    from .training import identity, journey as train
    state, data = policy.collection, policy.data
    choice = roam_lead(policy, snapshot, wanted)
    if choice is None:
        state.pop('roam_lead', None)
        return None
    mon, level = choice
    if mon.level < level:
        state.pop('roam_lead', None)
        state['roam_started'] = policy.decisions  # Training time does not count against the search.
        if policy.memory is None:
            return None
        if not state.get('training'):
            state['training'] = {'identity': identity(mon), 'target': mon.species, 'item': None,
                                 'species': mon.species, 'terminal': True, 'level_goal': level}
        return train(policy, snapshot, Memory(policy.memory, data), Goal)
    state['roam_lead'] = identity(mon)
    if mon.box is not None:
        team = [row for row in snapshot.party if not row.egg]
        if len(team) >= 6:
            counts = {move: sum(move in row.moves for row in team) for move in FIELD_MOVES}
            team.remove(min(team[1:], key=lambda row: (sum(counts[move] == 1 for move in row.moves if move in FIELD_MOVES),
                                                       row.held_item == data.items['EXP_SHARE'], row.level)))
        return assemble(policy, snapshot, [key(row) for row in team] + [key(mon)], Goal,
                        f'Bring {mon.name} to lead against the roaming beasts')
    slot = snapshot.party.index(mon)
    if slot:
        if policy.menu is None:
            policy.menu = Lead(slot, (mon.trainer_id, mon.dvs))
        return Goal('collection_roam_lead', f'Lead with {mon.name} to put the roaming beasts to sleep',
                    data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    return None


ULTRA_STOCK = 10


def ultra_shortfall(policy, snapshot):
    """Fewer than ten Ultra Balls and too little money to buy them before a static legendary trip.

    Asleep, a catch rate of 3 gives about 13/256 per Ultra Ball against about 11/256 per Poké Ball,
    so the trip waits for a League run to pay for a full stock instead of spending the encounter.
    """
    ultras = dict(snapshot.pockets['balls']).get(policy.data.items['ULTRA_BALL'], 0)
    price = policy.data.item_attributes[policy.data.items['ULTRA_BALL']]['price']
    return ultras < ULTRA_STOCK and snapshot.money < price * ULTRA_STOCK + 400


def static_wanted(policy, snapshot):
    """Lugia, Ho-Oh or Crystal's Suicune is still to catch and waiting in its room."""
    owned = snapshot.owned - getattr(policy, 'returned', set())
    statics = [(249, 'LUGIA'), (250, 'HO_OH')] + ([(245, 'SUICUNE')] if policy.data.game == 'crystal' else [])
    return any(dex not in owned and not snapshot.event('EVENT_FOUGHT_' + flag) for dex, flag in statics)


def ball_ready(policy, snapshot):
    """A ball other than the Master Ball is in the pack, or no roaming beast still needs the Master Ball,
    and the Ultra Ball stock is full or cannot be afforded yet.

    Without a ball, a static legendary battle could only knock it out, so the trip waits for a restock.
    """
    master = policy.data.items['MASTER_BALL']
    regular = any(item != master and count for item, count in snapshot.pockets['balls'])
    return (regular or not beasts_roaming(policy, snapshot)) and not (
        regular and ULTRA_STOCK > dict(snapshot.pockets['balls']).get(policy.data.items['ULTRA_BALL'], 0)
        and not ultra_shortfall(policy, snapshot))


def beasts_roaming(policy, snapshot):
    """A roaming beast is still wanted. Those flee, so they are the hardest catch and keep the Master Ball."""
    owned = snapshot.owned - policy.returned
    return any(row['species'] not in owned and row['map'] in policy.data.maps for row in snapshot.roamers)


def static_level(data, species):
    """The level a static legendary is met at: the version mascot at 40, the other one at 70, Crystal's at 60."""
    if data.game == 'crystal':
        return 40 if species == 245 else 60
    return 40 if species == {'gold': 250, 'silver': 249}.get(data.game) else 70


def sleep_chance(policy, mon, species, level):
    """Chance this Pokémon puts the legendary to sleep before it faints, from the legendary's strongest hit."""
    from types import SimpleNamespace
    from .ram import calculated_stats
    data = policy.data
    sleep = sleep_move(data, mon, species)
    if sleep is None:
        return 0
    learned = [move for at, move in data.species[species]['learnset'] if at <= level]
    moves = list(dict.fromkeys(reversed(learned)))[:4]
    stats = calculated_stats(data.species[species]['stats'], level, (15,) * 5, (0,) * 5)
    enemy = SimpleNamespace(species=species, level=level, stats=stats)
    target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.stats[0],
                             enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
    hit = max((policy.move_score(move, enemy, target) for move in moves), default=0)
    turns = -(-mon.stats[0] // max(1, int(hit))) if hit else 8
    # A slower sleeper takes the first hit before it can move.
    tries = min(8, turns if mon.stats[3] > stats[3] else turns - 1)
    return 1 - (1 - sleep[0] / 100) ** max(0, tries)


def static_lead(policy, snapshot, species, Goal):
    """Withdraw and lead with the Pokémon most likely to put a static legendary to sleep.

    Sleep adds 10 to the catch chance in Gen II, where a catch rate of 3 otherwise gives 3 in 256 per
    Ultra Ball, so the lead that lands it before fainting matters more than how hard it hits. None once
    that Pokémon leads, or when no Pokémon knows a sleep move the legendary is not immune to.
    """
    from .menus import Lead
    from .teams import assemble, key
    data = policy.data
    level = static_level(data, species)
    options = [(sleep_chance(policy, mon, species, level), mon.box is None, mon.level, mon)
               for mon in snapshot.party + snapshot.stored if not mon.egg and mon.species in data.species]
    options = [row for row in options if row[0] > 0]
    if not options:
        return None
    mon = max(options, key=lambda row: row[:3])[3]
    # False Swipe chips a sleeping legendary to 1 HP with no risk, so a Pokémon that knows it comes too.
    swipers = [row for row in snapshot.party + snapshot.stored if not row.egg and row is not mon
               and any(pp and data.moves.get(move, {}).get('effect') == 'EFFECT_FALSE_SWIPE' for move, pp in zip(row.moves, row.pp))]
    swiper = None if any(row.box is None for row in swipers) else max(swipers, key=lambda row: row.level, default=None)
    joining = [row for row in (mon, swiper) if row is not None and row.box is not None]
    if joining:
        team = [row for row in snapshot.party if not row.egg]
        counts = {move: sum(move in row.moves for row in team) for move in FIELD_MOVES}
        while len(team) + len(joining) > 6:
            team.remove(min((row for row in team[1:] if row is not mon), key=lambda row: (
                sum(counts[move] == 1 for move in row.moves if move in FIELD_MOVES),
                row.held_item == data.items['EXP_SHARE'], row.level)))
        return assemble(policy, snapshot, [key(row) for row in team + joining], Goal,
                        f'Bring {mon.name} to put {data.species[species]["name"]} to sleep')
    slot = snapshot.party.index(mon)
    if slot:
        if policy.menu is None:
            policy.menu = Lead(slot, (mon.trainer_id, mon.dvs))
        return Goal('collection_static_lead', f'Lead with {mon.name} to put {data.species[species]["name"]} to sleep',
                    data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
    return None


def roamers(policy, snapshot, Goal):
    """Track the roaming beasts with the cartridge's own movement rule.

    Each time the player crosses a map connection, every roamer steps to a random neighbour of its
    route that is not the map the player left before the current one (wRoamMons_LastMap). Walking
    into a neighbour of a roamer's route that is not that excluded map gives the roamer a fair
    chance to step into the same map, and then its grass is searched.
    """
    from .collection import encounter_points
    from .ram import Memory
    state, data = policy.collection, policy.data
    owned = snapshot.owned - getattr(policy, 'returned', set())
    if policy.decisions < state.get('roam_after', 0):
        return None
    started = state.setdefault('roam_started', policy.decisions)
    if policy.decisions - started > 12000:
        state['roam_after'] = policy.decisions + 18000
        state.pop('roam_started', None)
        state.pop('roam_lead', None)
        return None
    state.pop('roam_destination', None)
    wanted = [row for row in snapshot.roamers
              if row['species'] and row['species'] not in owned and row['map'] in data.maps]
    if not wanted:
        state.pop('roam_lead', None)
        return None
    goal = prepare_lead(policy, snapshot, wanted, Goal)
    if goal:
        return goal
    for roamer in wanted:
        mid, species = roamer['map'], roamer['species']
        if mid != snapshot.map:
            continue
        points = sorted(encounter_points(policy, snapshot, mid, 'grass'),
                        key=lambda p: (abs(p[0] - snapshot.x) + abs(p[1] - snapshot.y),
                                       policy.nav.visits.get((mid, *p[:2]), 0)))
        point = next((p for p in points[:24] if p[:2] != (snapshot.x, snapshot.y)
                      and policy.nav.local(snapshot, [p[:2]], policy.memory, surf=True)), None)
        if point is not None:
            return Goal('collection_roam_hunt', f'Track {data.species[species]["name"]} through Johto',
                        data.maps[mid]['constant'], *point[:2])
    excluded = {snapshot.map}
    if policy.memory is not None and 'wRoamMons_LastMapGroup' in data.symbols:
        mem = Memory(policy.memory, data)
        excluded.add(mem.byte('wRoamMons_LastMapGroup') * 256 + mem.byte('wRoamMons_LastMapNumber'))
    candidates = {mid: roamer['species'] for roamer in wanted
                  for mid in roam_neighbours(data, roamer['map']) if mid not in excluded}
    if not candidates:
        # Every neighbour is excluded right now: any other roaming route still moves the beasts.
        candidates = {data.map_ids[f'ROUTE_{route}']: wanted[0]['species'] for route in ROAM_MAPS
                      if data.map_ids[f'ROUTE_{route}'] not in excluded}
    choices = []
    for mid, species in candidates.items():
        route = policy.nav.route(snapshot.map, mid)
        if route is None:
            continue
        points = encounter_points(policy, snapshot, mid, 'grass')
        if points:
            choices.append((len(route), mid, species, points))
    if not choices:
        return None
    _, mid, species, points = min(choices, key=lambda row: row[:2])
    width = data.maps[mid]['width']
    x, y, _ = min(points, key=lambda p: min(p[0], width - 1 - p[0], p[1], data.maps[mid]['height'] - 1 - p[1]))
    return Goal('collection_roam_shift', f'Head where {data.species[species]["name"]} may roam next',
                data.maps[mid]['constant'], x, y)


def arrive(policy, snapshot):
    if policy.goal.key == 'collection_release_rock':
        slot = next((i for i, mon in enumerate(snapshot.party) if 249 in mon.moves and not mon.egg), None)
        if slot is None:
            slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg
                         and 249 in policy.data.species[mon.species]['machines']
                         and not all(move in FIELD_MOVES for move in mon.moves)), None)
            if slot is not None:
                policy.menu = Teach(249, slot)
        else:
            policy.menu = FieldMove(slot, 'ROCK SMASH')
        return 'wait'
    if policy.goal.key == 'collection_stone_show':
        species, flag = policy.collection['stone_show']
        slot = next((i for i, mon in enumerate(snapshot.party) if mon.species == species and not mon.egg), None)
        if slot is None:
            return 'b'
        policy.menu = ShowPartner(slot, flag)
        return 'a'
    if policy.goal.key == 'collection_stone_pc':
        species, _ = policy.collection['stone_show']
        if len(snapshot.party) < 6:
            mon = next((mon for mon in snapshot.stored if mon.species == species and not mon.egg), None)
            if mon:
                policy.menu = ChangeBox(mon.box) if mon.box != snapshot.active_box else Storage('WITHDRAW', mon.position, len(snapshot.party))
            return 'a'
    elif policy.goal.key != 'collection_gift_room':
        return None
    if snapshot.box_counts[snapshot.active_box] >= 20:
        box = next((index for index, count in enumerate(snapshot.box_counts) if count < 20), None)
        if box is not None:
            policy.menu = ChangeBox(box)
    else:
        if len(snapshot.party) < 2:
            return 'b'
        counts = {move: sum(move in mon.moves for mon in snapshot.party) for move in FIELD_MOVES}
        slot = min(range(1, len(snapshot.party)), key=lambda i: (
            sum(counts[move] == 1 for move in snapshot.party[i].moves if move in FIELD_MOVES),
            snapshot.party[i].held_item == policy.data.items['EXP_SHARE'], snapshot.party[i].egg, snapshot.party[i].level))
        policy.menu = Storage('DEPOSIT', slot, len(snapshot.party))
    return 'a'


def stones(policy, snapshot, Goal):
    if not snapshot.event('EVENT_TOHJO_FALLS_MOON_STONE'):
        return policy.person(snapshot, 'collection_stone', 'Collect the Moon Stone in Tohjo Falls',
                             'TOHJO_FALLS', 'TohjoFallsMoonStone')
    requirements = [(108, 'EVERSTONE'), (43, 'LEAF_STONE'), (120, 'WATER_STONE'),
                    (37 if policy.data.game == 'silver' else 58, 'FIRE_STONE'), (172, 'THUNDERSTONE')]
    for species, item in requirements:
        flag = 'EVENT_GOT_' + item + '_FROM_BILLS_GRANDPA'
        if snapshot.event(flag):
            continue
        mon = next((mon for mon in snapshot.party + snapshot.stored if mon.species == species and not mon.egg), None)
        if mon is None:
            return None
        policy.collection['stone_show'] = [species, flag]
        if mon.box is not None:
            goal = policy.storage_goal(snapshot)
            return Goal('collection_stone_pc', 'Bring a Pokémon to show Bill’s grandfather',
                        goal.map_name, goal.x, goal.y, goal.face)
        if (snapshot.map == policy.data.map_ids['BILLS_HOUSE']
                and snapshot.event('EVENT_TEMPORARY_UNTIL_MAP_RELOAD_1')):
            return Goal('stone_visit_again', 'Give Bill’s grandfather time for another visit', 'ROUTE_25', 47, 5)
        return policy.person(snapshot, 'collection_stone_show', 'Show a Pokémon to Bill’s grandfather',
                             'BILLS_HOUSE', 'BillsGrandpa')
    return None


def trade_items(policy, snapshot, Goal):
    well = policy.data.map_ids['SLOWPOKE_WELL_B1F']
    if snapshot.map == well:
        stones = policy.nav.objects.setdefault(well, {})
        stones.update({index: (x, y) for index, x, y in snapshot.objects})
        index = next(i for i, obj in enumerate(policy.data.maps[well]['objects'], 1) if obj['sprite'] == 'SPRITE_BOULDER')
        x, y = stones.get(index, (3, 2))
        if (not snapshot.event('EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL') and x > 2
                and policy.nav.local(snapshot, [(7, 11)], policy.memory, surf=True) is None):
            return Goal('push_well_passage', 'Open the lower passage in Slowpoke Well', 'SLOWPOKE_WELL_B1F', x + 1, y, 'left')
        if (snapshot.event('EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL') and x < 6
                and policy.nav.local(snapshot, [(17, 15)], policy.memory, surf=True) is None):
            return Goal('push_well_exit', 'Reopen the exit from Slowpoke Well', 'SLOWPOKE_WELL_B1F', x - 1, y, 'right')
    for event, area, script, label in [
        ('EVENT_GOT_UP_GRADE', 'SILPH_CO_1F', 'SilphCoOfficerScript', 'Receive the Up-Grade at Silph Co.'),
        ('EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL', 'SLOWPOKE_WELL_B2F', 'SlowpokeWellB2FGymGuideScript',
         'Receive the King’s Rock in Slowpoke Well'),
        ('EVENT_MOUNT_MORTAR_2F_INSIDE_DRAGON_SCALE', 'MOUNT_MORTAR_2F_INSIDE', 'MountMortar2FInsideDragonScale',
         'Collect the Dragon Scale in Mt. Mortar'),
    ]:
        if not snapshot.event(event):
            return policy.person(snapshot, 'collection_trade_item', label, area, script)
    return None
