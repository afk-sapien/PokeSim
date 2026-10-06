"""Prepare a legal Crystal Battle Tower team and play a seven-opponent challenge."""
from .menus import Take, Teach, choose
from .ram import Memory
from .teams import assemble, key


def select_team(snapshot):
    def strength(mon):
        value = (sum(mon.stats) - mon.level - 35) / mon.level
        data = getattr(mon, 'data', None)
        if data:
            attacks = []
            for mid in mon.moves:
                move = data.moves.get(mid, {})
                power = move.get('power', 0)
                if not power:
                    continue
                kind = move['type']
                attack = mon.stats[1 if kind < 20 else 4]
                stab = 1.5 if kind in data.species[mon.species]['types'] else 1
                score = power * attack / mon.level * stab * move.get('accuracy', 100) / 100
                if move.get('effect') == 'EFFECT_STATIC_DAMAGE':
                    score = power * 250 / mon.level
                if move.get('effect') == 'EFFECT_LEVEL_DAMAGE':
                    score = 250
                if move.get('effect') in {'EFFECT_EXPLOSION', 'EFFECT_SELFDESTRUCT'}:
                    score *= 0.1
                attacks.append(score)
            value *= (max(attacks, default=0) / 200) ** 0.5
        return value
    choices = []
    for cap in range(10, 101, 10):
        candidates = sorted((mon for mon in snapshot.party + snapshot.stored
                             if not mon.egg and cap - 10 < mon.level <= cap
                             and (cap >= 70 or mon.species not in {150, 151, 249, 250, 251})),
                            key=strength, reverse=True)
        team = []
        for mon in candidates:
            if mon.species not in {member.species for member in team}:
                team.append(mon)
                if len(team) == 3:
                    break
        if len(team) == 3:
            choices.append((sum(strength(mon) for mon in team), cap, team))
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
            'original': [key(mon) for mon in snapshot.party], 'cap': cap, 'entered': False, 'returning': False,
            'previous_training': policy.collection.get('training')}
    mem = Memory(policy.memory, policy.data)
    name = policy.data.maps[snapshot.map]['constant']
    if name in {'BATTLE_TOWER_BATTLE_ROOM', 'BATTLE_TOWER_HALLWAY', 'BATTLE_TOWER_ELEVATOR'}:
        state['entered'] = True
        state['wins'] = min(7, mem.byte('sNrOfBeatenBattleTowerTrainers'))
        return Goal('tower_battle', 'Challenge the Battle Tower opponents', name, snapshot.x, snapshot.y)
    if state['entered'] and name == 'BATTLE_TOWER_1F':
        # The cartridge increments this counter when an opponent is loaded.
        state['wins'] = max(0, min(7, mem.byte('sNrOfBeatenBattleTowerTrainers'))
                            - int(mem.byte('wBattleResult') != 0))
        state['returning'] = True
    if state['returning']:
        goal = assemble(policy, snapshot, state['original'], Goal, 'Restore the adventure team after the Battle Tower')
        if goal:
            return goal
        policy.collection['tower_result'] = {'wins': state.get('wins', 0), 'level': state['cap']}
        policy.collection['tower_after'] = policy.decisions + 50000
        if 'previous_training' in state:
            policy.collection['training'] = state['previous_training']
        policy.collection.pop('tower', None)
        policy.completed['tower'] = snapshot.frame
        return None
    if not state.get('trained') and 'previous_training' in state:
        from .training import identity, journey as train
        partner = next((mon for mon in snapshot.party + snapshot.stored
                        if key(mon) in state['team'] and mon.level < state['cap']), None)
        if partner:
            policy.collection['training'] = {'identity': identity(partner), 'target': partner.species,
                'item': None, 'species': partner.species, 'terminal': True, 'level_goal': state['cap']}
            goal = train(policy, snapshot, mem, Goal)
            if goal:
                return goal
            if policy.menu:
                return Goal('tower_training_menu', 'Finish preparing the Tower training partner', name, snapshot.x, snapshot.y)
        state['trained'] = True
        policy.collection['training'] = state['previous_training']
    if not state.get('preparation_center'):
        if name == 'OLIVINE_POKECENTER_1F':
            state['preparation_center'] = True
        else:
            goal = assemble(policy, snapshot, state['original'], Goal, 'Prepare the adventure team for travel to Olivine')
            if goal:
                return goal
            return Goal('tower_travel', 'Travel to Olivine before preparing the Tower team', 'OLIVINE_POKECENTER_1F', 5, 6)
    goal = assemble(policy, snapshot, state['team'], Goal, 'Prepare three partners for the Battle Tower')
    if goal:
        return goal
    items = set()
    for slot, mon in enumerate(snapshot.party):
        physical = [policy.data.moves.get(move, {}) for move in mon.moves]
        best = max((move.get('power', 0) * (1.5 if move.get('type') in policy.data.species[mon.species]['types'] else 1)
                    for move in physical if move.get('type', 20) < 20
                    and move.get('effect') not in {'EFFECT_EXPLOSION', 'EFFECT_SELFDESTRUCT'}), default=0)
        if (70 not in mon.moves and 70 in policy.data.species[mon.species]['machines']
                and policy.data.items['HM04'] in dict(snapshot.items)
                and mon.stats[1] > mon.stats[4] * 1.4 and best < 80):
            if policy.menu is None:
                policy.menu = Teach(70, slot)
            return Goal('tower_move', 'Prepare a physical attack for the Tower', name, snapshot.x, snapshot.y)
        if mon.held_item and mon.held_item in items:
            if policy.menu is None:
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
