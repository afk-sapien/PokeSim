"""Kanto story objectives selected from cartridge progress flags.

Where each step happens is in pokesim/story/gen2.json. The order of the steps stays here.
"""


def journey(policy, snapshot, mem, Goal):
    step = lambda key, title: policy.story_step(snapshot, key, title)
    name = policy.data.maps[snapshot.map]['constant']
    if not snapshot.event('EVENT_GOT_SS_TICKET_FROM_ELM'):
        return step('ticket', 'Receive the S.S. Aqua ticket')
    if not mem.byte('wPokegearFlags') & 2:
        return step('radio_card', 'Get the Pokégear Radio Card')
    if not snapshot.event('EVENT_FAST_SHIP_FIRST_TIME'):
        if not name.startswith('FAST_SHIP'):
            return step('board_ship', 'Board the S.S. Aqua for Kanto')
        if not snapshot.event('EVENT_FAST_SHIP_INFORMED_ABOUT_LAZY_SAILOR'):
            return step('ship_sailor', 'Help the crew find the missing sailor')
        if not snapshot.event('EVENT_FAST_SHIP_LAZY_SAILOR'):
            return step('wake_sailor', 'Wake the sailor in his cabin')
        if not snapshot.event('EVENT_FAST_SHIP_FOUND_GIRL'):
            return step('find_girl', 'Find the missing granddaughter')
        return step('leave_ship', 'Disembark in Vermilion City')
    policy.completed.setdefault('kanto', snapshot.frame)
    for mask, key in [(1024, 'surge'), (8192, 'sabrina'), (2048, 'erika'), (4096, 'janine')]:
        if not snapshot.badges & mask:
            return step(key, f'Challenge {key.title()}')
        policy.completed.setdefault(key, snapshot.frame)
    if not snapshot.event('EVENT_MET_MANAGER_AT_POWER_PLANT'):
        return step('power_plant', 'Investigate the Power Plant theft')
    if not snapshot.event('EVENT_MET_ROCKET_GRUNT_AT_CERULEAN_GYM'):
        return step('cerulean_rocket', 'Investigate Cerulean Gym')
    if not snapshot.event('EVENT_ROUTE_24_ROCKET'):
        return step('rocket_part', 'Find the Rocket on Nugget Bridge')
    if not snapshot.event('EVENT_FOUND_MACHINE_PART_IN_CERULEAN_GYM'):
        return step('machine_part', 'Recover the missing Machine Part')
    if not snapshot.event('EVENT_RETURNED_MACHINE_PART'):
        return step('restore_power', 'Restore power to Kanto')
    if snapshot.event('EVENT_TRAINERS_IN_CERULEAN_GYM'):
        return step('find_misty', 'Find Misty on Route 25')
    if not snapshot.badges & 512:
        return step('misty', 'Challenge Misty')
    if not mem.byte('wPokegearFlags') & 8:
        return step('expansion', 'Receive the Kanto radio expansion')
    snorlax = step('snorlax', 'Wake Snorlax with the Poké Flute channel')
    if not snapshot.event('EVENT_FOUGHT_SNORLAX'):
        return snorlax
    if not snapshot.event('EVENT_VERMILION_CITY_SNORLAX'):
        # A walking return shows Snorlax again without clearing the fought flag.
        goal = policy.returned_encounter(snapshot, Goal, 'Snorlax')
        if goal is not None:
            return goal or snorlax
    if not snapshot.badges & 256:
        return step('brock', 'Challenge Brock')
    if not snapshot.badges & 16384:
        return step('blaine', 'Challenge Blaine')
    if snapshot.event('EVENT_VIRIDIAN_GYM_BLUE'):
        return step('find_blue', 'Invite Blue back to his Gym')
    if not snapshot.badges & 32768:
        return step('blue', 'Challenge Blue')
    policy.completed.setdefault('sixteen_badges', snapshot.frame)
    if not snapshot.event('EVENT_OPENED_MT_SILVER'):
        return step('oak', 'Show Professor Oak all sixteen badges')
    if 'red' not in policy.completed and not snapshot.event('EVENT_RED_IN_MT_SILVER'):
        goal = red_funding(policy, snapshot, Goal)
        return goal or step('red', 'Challenge Red on Mt. Silver')
    policy.completed.setdefault('red', snapshot.frame)
    from .collection import journey as collect
    return collect(policy, snapshot, mem, Goal)


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
    from .ledger import red_short
    if funding is None and red_short(policy, snapshot):
        state['funding'] = funding = snapshot.hall_of_fame_count + 1
    if funding is None:
        return None
    from .collection import league_funding
    return league_funding(policy, snapshot, Goal)
