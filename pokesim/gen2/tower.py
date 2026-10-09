"""Prepare a legal Crystal Battle Tower team and play a seven-opponent challenge."""
from itertools import combinations
from types import SimpleNamespace

from .menus import Give, Lead, Take, Teach, choose
from .ram import Memory, calculated_stats
from .teams import assemble, assembled, key

MACHINES = ((70, 'HM04'), (57, 'HM03'), (19, 'HM02'), (94, 'TM29'), (89, 'TM26'), (188, 'TM36'), (247, 'TM30'))


def attack_value(data, mon, mid):
    move = data.moves.get(mid, {})
    power = move.get('power', 0)
    if not power:
        return 0
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
    if move.get('effect') in {'EFFECT_RECHARGE', 'EFFECT_RAZOR_WIND', 'EFFECT_SOLARBEAM', 'EFFECT_FLY', 'EFFECT_DIG'}:
        score *= 0.6
    return score


def upgrades(data, mon, inventory):
    return [move for move, item in MACHINES if inventory.get(data.items[item])
            and move in data.species[mon.species]['machines'] and move not in mon.moves]


def forecast(mon, cap):
    data = getattr(mon, 'data', None)
    if not data:
        return mon
    species = mon.species
    for _ in range(2):
        species = next((evo['species'] for evo in data.species[species]['evolutions']
                        if evo['method'] == 'level' and int(evo['requirements'][0]) <= cap), species)
    return SimpleNamespace(data=data, species=species, level=cap, moves=mon.moves,
        stats=calculated_stats(data.species[species]['stats'], cap, mon.dvs, mon.stat_exp))


def select_team(snapshot):
    def strength(mon):
        value = (sum(mon.stats) - mon.level - 35) / mon.level
        data = getattr(mon, 'data', None)
        if data:
            attacks = [attack_value(data, mon, mid) for mid in list(mon.moves) + upgrades(data, mon, dict(snapshot.items))]
            value *= (max(attacks, default=0) / 200) ** 0.5
            if 105 in mon.moves:
                value *= 1.6 if 92 in mon.moves else 1.3
        return value
    choices = []
    for cap in range(10, 101, 10):
        candidates = []
        for mon in snapshot.party + snapshot.stored:
            if mon.egg or not cap - 20 < mon.level <= cap or cap < 70 and mon.species in {150, 151, 249, 250, 251}:
                continue
            expected = forecast(mon, cap)
            score = strength(expected) * (1 - (cap - mon.level) * 0.01)
            candidates.append((score, mon, expected))
        unique = {}
        for row in sorted(candidates, key=lambda row: row[0], reverse=True):
            unique.setdefault(row[2].species, row)
        candidates = list(unique.values())[:12]
        for rows in combinations(candidates, 3):
            if len({row[2].species for row in rows}) != 3:
                continue
            data = getattr(rows[0][2], 'data', None)
            exposed = 0
            if data:
                for attack in {kind for pair in data.matchups for kind in pair}:
                    factors = []
                    for _, _, mon in rows:
                        factor = 1
                        for kind in set(data.species[mon.species]['types']):
                            factor *= data.matchups.get((attack, kind), 1)
                        factors.append(factor)
                    exposed += sum(value > 1 for value in factors) >= 2 and min(factors) >= 1
            score = sum(row[0] for row in rows) * max(0.4, 1 - exposed * 0.12)
            choices.append((score, -cap, [row[1] for row in rows]))
    if not choices:
        return None
    _, cap, team = max(choices, key=lambda row: row[:2])
    return -cap, team


def journey(policy, snapshot, Goal, *, force=False):
    if policy.data.game != 'crystal':
        return None
    state = policy.collection.get('tower')
    if state is None:
        if not force and policy.decisions < policy.collection.get('tower_after', 0):
            return None
        for flag, area, script in [('EVENT_GOT_TM29_PSYCHIC', 'MR_PSYCHICS_HOUSE', 'MrPsychic'),
                                    ('EVENT_VICTORY_ROAD_TM_EARTHQUAKE', 'VICTORY_ROAD', 'VictoryRoadTMEarthquake'),
                                    ('EVENT_GOT_TM36_SLUDGE_BOMB', 'ROUTE_43_GATE', 'OfficerScript_GuardWithSludgeBomb')]:
            if not snapshot.event(flag):
                return policy.person(snapshot, 'tower_machine', 'Collect a move for the Battle Tower team', area, script)
        if not snapshot.event('EVENT_FOUND_LEFTOVERS_IN_CELADON_CAFE'):
            return Goal('tower_leftovers', 'Collect Leftovers for the Tower team', 'CELADON_CAFE', 7, 2, 'up')
        berry = policy.data.items['PRZCUREBERRY']
        mem = Memory(policy.memory, policy.data)
        # Violet City's tree is number nine. The daily flag gates its native reset.
        fruit_ready = not mem.byte('wDailyFlags1') & 16 or not mem.byte('wFruitTreeFlags', 1) & 1
        if (fruit_ready and len(snapshot.pockets['items']) < 20 and not dict(snapshot.items).get(berry)
                and not any(mon.held_item == berry for mon in snapshot.party + snapshot.stored)):
            return policy.person(snapshot, 'tower_berry', 'Collect a paralysis-curing berry for the Tower',
                                 'VIOLET_CITY', 'VioletCityFruitTree')
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
        if not state.get('abandoned'):
            policy.collection['tower_result'] = {'wins': state.get('wins', 0), 'level': state['cap']}
            policy.completed['tower'] = snapshot.frame
        policy.collection['tower_after'] = policy.decisions + 50000
        if 'previous_training' in state:
            policy.collection['training'] = state['previous_training']
        policy.collection.pop('tower', None)
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
    if not assembled(snapshot, state['team']):
        # A partner is gone or storage has no room left, so this challenge stands down.
        state['abandoned'] = state['returning'] = True
        return journey(policy, snapshot, Goal)
    options = []
    protected = {15, 19, 57, 70, 148, 250, 127, 105, 92}
    for slot, mon in enumerate(snapshot.party):
        if (105 in mon.moves and 92 not in mon.moves and 92 in policy.data.species[mon.species]['machines']
                and dict(snapshot.items).get(policy.data.items['TM06'])):
            weakest = min((move for move in mon.moves if move not in protected),
                          key=lambda move: attack_value(policy.data, mon, move), default=None)
            if weakest is not None:
                if policy.menu is None:
                    policy.menu = Teach(92, slot, replace_move=weakest)
                return Goal('tower_toxic', 'Prepare Toxic for opponents that withstand direct attacks', name, snapshot.x, snapshot.y)
    for slot, mon in enumerate(snapshot.party):
        for move in upgrades(policy.data, mon, dict(snapshot.items)):
            kind = policy.data.moves[move]['type']
            same_type = max((attack_value(policy.data, mon, known) for known in mon.moves
                             if policy.data.moves.get(known, {}).get('type') == kind), default=0)
            weakest = min((known for known in mon.moves if known not in protected),
                          key=lambda known: attack_value(policy.data, mon, known), default=None)
            if weakest is not None:
                gain = attack_value(policy.data, mon, move) - max(same_type, attack_value(policy.data, mon, weakest))
                if gain > 20:
                    options.append((gain, slot, move, weakest))
    if options:
        _, slot, move, weakest = max(options)
        if policy.menu is None:
            policy.menu = Teach(move, slot, replace_move=weakest)
        return Goal('tower_move', 'Prepare attacks for the Tower opponents', name, snapshot.x, snapshot.y)
    lead = max(range(len(snapshot.party)), key=lambda slot: sum(snapshot.party[slot].stats)
               * (1.3 if {92, 105} <= set(snapshot.party[slot].moves) else 1))
    if lead:
        mon = snapshot.party[lead]
        if policy.menu is None:
            policy.menu = Lead(lead, (mon.trainer_id, mon.dvs))
        return Goal('tower_lead', 'Lead with the strongest Tower partner', name, snapshot.x, snapshot.y)
    leftovers = policy.data.items['LEFTOVERS']
    if dict(snapshot.items).get(leftovers) and not any(mon.held_item == leftovers for mon in snapshot.party):
        if policy.menu is None:
            policy.menu = Take(0) if snapshot.party[0].held_item else Give(leftovers, 0)
        return Goal('tower_leftovers', 'Equip Leftovers for the Tower challenge', name, snapshot.x, snapshot.y)
    berry = policy.data.items['PRZCUREBERRY']
    if dict(snapshot.items).get(berry) and not any(mon.held_item == berry for mon in snapshot.party):
        candidates = [slot for slot, mon in enumerate(snapshot.party)
                      if mon.held_item in {0, policy.data.items['EXP_SHARE']} and 105 not in mon.moves]
        if candidates:
            slot = max(candidates, key=lambda slot: snapshot.party[slot].stats[1])
            if policy.menu is None:
                policy.menu = Take(slot) if snapshot.party[slot].held_item else Give(berry, slot)
            return Goal('tower_berry', 'Equip a paralysis-curing berry for the Tower', name, snapshot.x, snapshot.y)
    items = set()
    for slot, mon in enumerate(snapshot.party):
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
