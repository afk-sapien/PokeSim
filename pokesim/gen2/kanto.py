"""Kanto story objectives selected from cartridge progress flags."""


def journey(policy, snapshot, mem, Goal):
    person = lambda key, label, area, script: policy.person(snapshot, key, label, area, script)
    name = policy.data.maps[snapshot.map]['constant']
    if not snapshot.event('EVENT_GOT_SS_TICKET_FROM_ELM'):
        return person('ticket', 'Receive the S.S. Aqua ticket', 'ELMS_LAB', 'ProfElmScript')
    if not mem.byte('wPokegearFlags') & 2:
        return person('radio_card', 'Get the Pokégear Radio Card', 'RADIO_TOWER_1F', 'RadioTower1FRadioCardWomanScript')
    if not snapshot.event('EVENT_FAST_SHIP_FIRST_TIME'):
        if not name.startswith('FAST_SHIP'):
            return person('board_ship', 'Board the S.S. Aqua for Kanto', 'OLIVINE_PORT', 'OlivinePortSailorAtGangwayScript')
        if not snapshot.event('EVENT_FAST_SHIP_INFORMED_ABOUT_LAZY_SAILOR'):
            return person('ship_sailor', 'Help the crew find the missing sailor', 'FAST_SHIP_B1F', 'FastShipB1FSailorScript')
        if not snapshot.event('EVENT_FAST_SHIP_LAZY_SAILOR'):
            return person('wake_sailor', 'Wake the sailor in his cabin', 'FAST_SHIP_CABINS_NNW_NNE_NE', 'FastShipLazySailorScript')
        if not snapshot.event('EVENT_FAST_SHIP_FOUND_GIRL'):
            return person('find_girl', 'Find the missing granddaughter', 'FAST_SHIP_CABINS_SE_SSE_CAPTAINS_CABIN', 'SSAquaGranddaughterBefore')
        return person('leave_ship', 'Disembark in Vermilion City', 'FAST_SHIP_1F', 'FastShip1FSailor1Script')
    policy.completed.setdefault('kanto', snapshot.frame)
    for mask, key, area, script in [
        (1024, 'surge', 'VERMILION_GYM', 'VermilionGymSurgeScript'),
        (8192, 'sabrina', 'SAFFRON_GYM', 'SaffronGymSabrinaScript'),
        (2048, 'erika', 'CELADON_GYM', 'CeladonGymErikaScript'),
        (4096, 'janine', 'FUCHSIA_GYM', 'FuchsiaGymJanineScript'),
    ]:
        if not snapshot.badges & mask:
            return person(key, f'Challenge {key.title()}', area, script)
        policy.completed.setdefault(key, snapshot.frame)
    if not snapshot.event('EVENT_MET_MANAGER_AT_POWER_PLANT'):
        return person('power_plant', 'Investigate the Power Plant theft', 'POWER_PLANT', 'PowerPlantManager')
    if not snapshot.event('EVENT_MET_ROCKET_GRUNT_AT_CERULEAN_GYM'):
        return Goal('cerulean_rocket', 'Investigate Cerulean Gym', 'CERULEAN_GYM', 4, 12)
    if not snapshot.event('EVENT_ROUTE_24_ROCKET'):
        return person('rocket_part', 'Find the Rocket on Nugget Bridge', 'ROUTE_24', 'Route24RocketScript')
    if not snapshot.event('EVENT_FOUND_MACHINE_PART_IN_CERULEAN_GYM'):
        return Goal('machine_part', 'Recover the missing Machine Part', 'CERULEAN_GYM', 3, 9, 'up')
    if not snapshot.event('EVENT_RETURNED_MACHINE_PART'):
        return person('restore_power', 'Restore power to Kanto', 'POWER_PLANT', 'PowerPlantManager')
    if snapshot.event('EVENT_TRAINERS_IN_CERULEAN_GYM'):
        return Goal('find_misty', 'Find Misty on Route 25', 'ROUTE_25', 42, 6)
    if not snapshot.badges & 512:
        return person('misty', 'Challenge Misty', 'CERULEAN_GYM', 'CeruleanGymMistyScript')
    if not mem.byte('wPokegearFlags') & 8:
        return person('expansion', 'Receive the Kanto radio expansion', 'LAV_RADIO_TOWER_1F', 'LavRadioTower1FGentlemanScript')
    if not snapshot.event('EVENT_FOUGHT_SNORLAX'):
        return Goal('snorlax', 'Wake Snorlax with the Poké Flute channel', 'VERMILION_CITY', 36, 8, 'left')
    if not snapshot.badges & 256:
        return person('brock', 'Challenge Brock', 'PEWTER_GYM', 'PewterGymBrockScript')
    if not snapshot.badges & 16384:
        return person('blaine', 'Challenge Blaine', 'SEAFOAM_GYM', 'SeafoamGymBlaineScript')
    if snapshot.event('EVENT_VIRIDIAN_GYM_BLUE'):
        return person('find_blue', 'Invite Blue back to his Gym', 'CINNABAR_ISLAND', 'CinnabarIslandBlue')
    if not snapshot.badges & 32768:
        return person('blue', 'Challenge Blue', 'VIRIDIAN_GYM', 'ViridianGymBlueScript')
    policy.completed.setdefault('sixteen_badges', snapshot.frame)
    if not snapshot.event('EVENT_OPENED_MT_SILVER'):
        return person('oak', 'Show Professor Oak all sixteen badges', 'OAKS_LAB', 'Oak')
    if 'red' not in policy.completed and not snapshot.event('EVENT_RED_IN_MT_SILVER'):
        goal = red_funding(policy, snapshot, Goal)
        return goal or person('red', 'Challenge Red on Mt. Silver', 'SILVER_CAVE_ROOM_3', 'Red')
    policy.completed.setdefault('red', snapshot.frame)
    from .collection import journey as collect
    return collect(policy, snapshot, mem, Goal)


RED_POTIONS = ['FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION']


def red_funding(policy, snapshot, Goal):
    """Win League prize money before Red when healing items run low and the purse cannot restock them.

    Each loss to Red halves the money, so without this the policy keeps walking back to Mt. Silver
    with an empty bag and no way to buy the potions the shop asks for.
    """
    state = policy.collection
    funding = state.get('funding')
    if funding is not None and snapshot.hall_of_fame_count >= funding:
        state.pop('funding', None)
        funding = None
    inventory = dict(snapshot.items)
    potions = sum(inventory.get(policy.data.items[name], 0) for name in RED_POTIONS)
    if funding is None and potions < 8 and snapshot.money < 10000:
        state['funding'] = funding = snapshot.hall_of_fame_count + 1
    if funding is None:
        return None
    from .collection import league_funding
    return league_funding(policy, snapshot, Goal)
