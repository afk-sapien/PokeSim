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
    if {243, 244, 245, 249, 250} <= snapshot.owned:
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
        return Goal('legend_suicune', 'Meet Suicune at the Tin Tower', 'TIN_TOWER_1F', 9, 12)
    if 249 not in snapshot.owned and not snapshot.event('EVENT_FOUGHT_LUGIA'):
        return policy.person(snapshot, 'legend_lugia', 'Seek Lugia in the Whirl Islands', 'WHIRL_ISLAND_LUGIA_CHAMBER', 'Lugia')
    if (data.game == 'crystal' and 250 not in snapshot.owned
            and {243, 244, 245} <= snapshot.owned and data.items['RAINBOW_WING'] not in items):
        return policy.person(snapshot, 'rainbow_wing', 'Return to the Tin Tower with the three beasts',
                             'TIN_TOWER_1F', 'TinTower1FSage5Script')
    if 250 not in snapshot.owned and data.items['RAINBOW_WING'] in items and not snapshot.event('EVENT_FOUGHT_HO_OH'):
        return policy.person(snapshot, 'legend_ho_oh', 'Seek Ho-Oh above the Tin Tower', 'TIN_TOWER_ROOF', 'TinTowerHoOh')
    return roamers(policy, snapshot, Goal)


def roamers(policy, snapshot, Goal):
    from .collection import encounter_points
    state, data = policy.collection, policy.data
    if policy.decisions < state.get('roam_after', 0):
        return None
    started = state.setdefault('roam_started', policy.decisions)
    if policy.decisions - started > 12000:
        state['roam_after'] = policy.decisions + 18000
        state.pop('roam_started', None)
        return None
    choices = []
    for roamer in snapshot.roamers:
        mid, species = roamer['map'], roamer['species']
        if species in snapshot.owned or mid not in data.maps or mid != snapshot.map:
            continue
        points = encounter_points(policy, snapshot, mid, 'grass')
        route = policy.nav.regions.route(snapshot, mid, [point[:2] for point in points], cut=True, surf=True)
        if route is None or not points:
            continue
        points = sorted(points, key=lambda p: (abs(p[0] - snapshot.x) + abs(p[1] - snapshot.y),
                                                policy.nav.visits.get((mid, *p[:2]), 0)))
        point = next((p for p in points if p[:2] != (snapshot.x, snapshot.y)
                      and policy.nav.local(snapshot, [p[:2]], policy.memory, surf=True)), None)
        if point is None:
            continue
        choices.append((len(route), species, mid, point))
    if choices:
        _, species, mid, (x, y, _) = min(choices)
        return Goal('collection_hunt', f'Track {data.species[species]["name"]} through Johto', data.maps[mid]['constant'], x, y)
    if any(row['species'] not in snapshot.owned and row['map'] in data.maps for row in snapshot.roamers):
        # A two-map reversal excludes the route through the native last-map rule.
        # Visiting the ruins through its gate gives the roamers a fresh route entry.
        destination = state.get('roam_destination', 'ROUTE_36')
        if snapshot.map == data.map_ids[destination]:
            destination = 'RUINS_OF_ALPH_OUTSIDE' if destination == 'ROUTE_36' else 'ROUTE_36'
        state['roam_destination'] = destination
        x, y = (47, 12) if destination == 'ROUTE_36' else (7, 6)
        return Goal('collection_roam_shift', 'Search the ruins border for roaming legends', destination, x, y)
    return None


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
