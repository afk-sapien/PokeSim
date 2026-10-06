"""Prepare a legal Crystal Battle Tower team and play a seven-opponent challenge."""
from .menus import Take, choose
from .ram import Memory
from .teams import assemble, key


def select_team(snapshot):
    choices = []
    for cap in range(10, 101, 10):
        candidates = sorted((mon for mon in snapshot.party + snapshot.stored
                             if not mon.egg and cap - 10 < mon.level <= cap
                             and (cap >= 70 or mon.species not in {150, 151, 249, 250, 251})),
                            key=lambda mon: sum(mon.stats), reverse=True)
        team = []
        for mon in candidates:
            if mon.species not in {member.species for member in team}:
                team.append(mon)
                if len(team) == 3:
                    break
        if len(team) == 3:
            choices.append((sum(sum(mon.stats) for mon in team) / cap, cap, team))
    return max(choices, key=lambda row: row[:2])[1:] if choices else None


def journey(policy, snapshot, Goal, *, force=False):
    if policy.data.game != 'crystal':
        return None
    state = policy.collection.get('tower')
    if state is None:
        if not force and policy.decisions < policy.collection.get('tower_after', 0):
            return None
        selected = select_team(snapshot)
        if not selected:
            return None
        cap, team = selected
        state = policy.collection['tower'] = {'team': [key(mon) for mon in team],
            'original': [key(mon) for mon in snapshot.party], 'cap': cap, 'entered': False, 'returning': False}
    mem = Memory(policy.memory, policy.data)
    name = policy.data.maps[snapshot.map]['constant']
    if name in {'BATTLE_TOWER_BATTLE_ROOM', 'BATTLE_TOWER_HALLWAY', 'BATTLE_TOWER_ELEVATOR'}:
        state['entered'] = True
        state['wins'] = min(7, mem.byte('sNrOfBeatenBattleTowerTrainers'))
        return Goal('tower_battle', 'Challenge the Battle Tower opponents', name, snapshot.x, snapshot.y)
    if state['entered'] and name == 'BATTLE_TOWER_1F':
        state['wins'] = min(7, mem.byte('sNrOfBeatenBattleTowerTrainers'))
        state['returning'] = True
    if state['returning']:
        goal = assemble(policy, snapshot, state['original'], Goal, 'Restore the adventure team after the Battle Tower')
        if goal:
            return goal
        policy.collection['tower_result'] = {'wins': state.get('wins', 0), 'level': state['cap']}
        policy.collection['tower_after'] = policy.decisions + 50000
        policy.collection.pop('tower', None)
        policy.completed['tower'] = snapshot.frame
        return None
    goal = assemble(policy, snapshot, state['team'], Goal, 'Prepare three partners for the Battle Tower')
    if goal:
        return goal
    items = set()
    for slot, mon in enumerate(snapshot.party):
        if mon.held_item and mon.held_item in items:
            policy.menu = Take(slot)
            return Goal('tower_items', 'Remove a duplicate held item for the Battle Tower', name, snapshot.x, snapshot.y)
        items.add(mon.held_item)
    return Goal('tower_enter', 'Enter the Battle Tower challenge', 'BATTLE_TOWER_1F', 7, 7, 'up')


def control(policy, snapshot, mem):
    state = policy.collection.get('tower')
    if not state or policy.data.maps[snapshot.map]['constant'] != 'BATTLE_TOWER_1F':
        return None
    text = snapshot.text.upper()
    if 'LEVEL' in text and mem.byte('wBattleTowerRoomMenuJumptableIndex') == 2:
        current = mem.byte('wcd4f')
        target = state['cap'] // 10
        return 'a' if current == target else 'up' if current < target else 'down'
    if 'CHALLENGE' in text and 'EXPLANATION' in text:
        return choose(snapshot.tiles, 'CHALLENGE', exact=True) or 'a'
    if 'HEAR ABOUT' in text and 'YES' in text:
        return choose(snapshot.tiles, 'NO', exact=True) or 'a'
    return None
