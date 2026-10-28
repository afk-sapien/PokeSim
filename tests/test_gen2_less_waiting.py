"""A Gen II run waits for the cartridge clock only when nothing else is useful, and says what it waits for."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(species, *, box=0, position=0, level=30, dvs=(10, 10, 10, 10, 10), **extra):
    fields = dict(species=species, name=str(species), gender='Male', egg=False, box=box, position=position, trainer_id=4321,
                  dvs=dvs, moves=(33, 0, 0, 0), pp=(35, 0, 0, 0), level=level, friendship=70, held_item=0,
                  experience=30000, stat_exp=(0,) * 5)
    fields.update(extra)
    return SimpleNamespace(**fields)


def lead():
    return mon(157, box=None, dvs=(1,) * 5, moves=(57, 15, 53, 0), level=100, trainer_id=1)


def ditto():
    """Kept as the universal Day Care partner, so the plan never hunts for one."""
    return mon(132, box=1, position=19, gender='Genderless', dvs=(4, 4, 4, 4, 4))


def snapshot(party, stored=(), *, owned=None):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored) + (ditto(),), daycare=(None, None), egg_ready=False,
                           owned=set(range(1, 252)) if owned is None else owned, money=50000, box_counts=(5,) * 14,
                           active_box=0, map=1, x=1, y=1, items=(), can_catch=True, hall_of_fame_count=3,
                           pockets={'balls': [(5, 20)]}, event=lambda name: True)


def clock(day=1, time=1):
    """Monday by default, which is neither a contest day nor Lapras's Friday."""
    values = {'wCurDay': day, 'wTimeOfDay': time}
    return SimpleNamespace(byte=lambda name: values.get(name, 0), memory=None)


def stub_activities(monkeypatch, **goals):
    """Make every activity of the expedition idle except the ``goals`` given by name."""
    from pokesim.gen2 import (breeding, celebi, champion_shop, collection, contest, gamecorner, npc_trades, postgame,
                              quests, ruins, tower, training)
    for module, name in [(champion_shop, 'journey'), (contest, 'journey'), (tower, 'journey'), (ruins, 'journey'), (celebi, 'journey'),
                         (quests, 'gifts'), (quests, 'trade_items'), (quests, 'legends'), (quests, 'stones'),
                         (npc_trades, 'journey'), (breeding, 'journey'), (breeding, 'hatching'),
                         (gamecorner, 'journey'), (training, 'journey'), (postgame, 'journey')]:
        goal = goals.get(f'{module.__name__.rsplit(".", 1)[1]}.{name}')
        monkeypatch.setattr(module, name, lambda *args, goal=goal, **kwargs: goal)
    monkeypatch.setattr(npc_trades, 'requests', lambda *args: set())
    monkeypatch.setattr(quests, 'ultra_shortfall', lambda *args: False)
    patrols = []
    monkeypatch.setattr(collection, 'patrol', lambda policy, snapshot, Goal, label: patrols.append(label) or
                        Goal('collection_idle', label, 'ROUTE_29', 12, 8))
    return patrols


def expedition(data):
    return SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, completed={'tower': 1}, returned=set(),
                           in_league=lambda snapshot: False, no_room=lambda snapshot: False, memory=None)


def test_available_work_goes_ahead_of_a_clock_wait_and_names_it(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    walk = Goal('collection_hatch', 'Walk with the eggs and the Day Care partners', 'GOLDENROD_CITY', 20, 10)
    patrols = stub_activities(monkeypatch, **{'breeding.journey': walk})
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    # Lapras is wanted but surfaces only on Fridays, and the Day Care has a wanted pair now.
    goal = journey(expedition(data), state, clock(day=1), Goal)
    assert goal.key == 'collection_hatch' and not patrols
    assert goal.label == 'Walk with the eggs and the Day Care partners while Lapras waits for Friday'
    # Without a clock wait the label stays as it was.
    goal = journey(expedition(data), snapshot([lead()]), clock(day=1), Goal)
    assert goal.label == 'Walk with the eggs and the Day Care partners'


@pytest.mark.parametrize('activity, key', [('training.journey', 'collection_train'), ('postgame.journey', 'postgame_hunt'),
                                           ('quests.stones', 'collection_stone'), ('breeding.hatching', 'collection_hatch_pc')])
def test_the_day_care_wait_trains_or_collects_instead_of_pacing_goldenrod(data, monkeypatch, activity, key):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    walk = Goal('collection_hatch', 'Walk with the eggs and the Day Care partners', 'GOLDENROD_CITY', 20, 10)
    work = Goal(key, 'Other work', 'ROUTE_27', 5, 5)
    # The Day Care counts the steps of any walk, so the wait goes to the other work and Goldenrod is never paced.
    patrols = stub_activities(monkeypatch, **{'breeding.journey': walk, activity: work})
    goal = journey(expedition(data), snapshot([lead()]), clock(), Goal)
    assert goal.key == key and goal.map_name != 'GOLDENROD_CITY' and not patrols


def test_the_day_care_errands_still_go_ahead_of_other_work(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    egg = Goal('collection_breed_egg', 'Receive the Day Care egg', 'ROUTE_34', 15, 15)
    train = Goal('collection_train', 'Train MON toward level 100', 'SILVER_CAVE_ROOM_1', 9, 31)
    stub_activities(monkeypatch, **{'breeding.journey': egg, 'training.journey': train})
    assert journey(expedition(data), snapshot([lead()]), clock(), Goal).key == 'collection_breed_egg'


def test_hatching_and_training_come_before_the_patrol(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    hatch = Goal('collection_hatch_pc', 'Bring eggs from storage to hatch', 'GOLDENROD_POKECENTER_1F', 3, 3)
    train = Goal('collection_train', 'Train MON toward level 100', 'SILVER_CAVE_ROOM_1', 9, 31)
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    patrols = stub_activities(monkeypatch, **{'breeding.hatching': hatch, 'training.journey': train})
    assert journey(expedition(data), state, clock(), Goal).label == 'Bring eggs from storage to hatch while Lapras waits for Friday'
    patrols = stub_activities(monkeypatch, **{'training.journey': train})
    assert journey(expedition(data), state, clock(), Goal).key == 'collection_train' and not patrols
    # With nothing else left the patrol is the last resort, and it says what it waits for.
    patrols = stub_activities(monkeypatch)
    policy = expedition(data)
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'collection_idle' and policy.collection['phase'] == 'waiting'
    assert patrols == ['Walk the grass while Lapras waits for Friday']


def test_an_open_clock_window_is_used_while_it_lasts(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    stub_activities(monkeypatch)
    state = snapshot([lead()], owned=set(range(1, 252)) - {131})
    state.badges = 0
    # On Friday the Lapras window is open. It fails here for lack of the Fog Badge, so the plan moves on
    # to the patrol instead of waiting for Lapras, and nothing names a Friday wait any more.
    labels = stub_activities(monkeypatch)
    goal = journey(expedition(data), state, clock(day=5), Goal)
    assert goal.key == 'collection_idle' and 'Friday' not in labels[0]


def test_patrol_labels_say_what_the_walk_does_and_waits_for(data):
    from pokesim.gen2.collection import waiting_label
    policy = expedition(data)
    owned = set(range(1, 252))
    assert (waiting_label(policy, snapshot([lead()], owned=owned), clock(), 'day')
            == 'Walk the grass until a trade or a return brings new collection work')
    eggs = snapshot([lead(), mon(175, box=None, egg=True)], owned=owned - {131})
    assert waiting_label(policy, eggs, clock(), 'day') == 'Walk the eggs to hatching while Lapras waits for Friday'
    # Contest days come first when the Sun Stone is still needed.
    contest = snapshot([lead()], owned=owned - {182, 192})
    label = waiting_label(policy, contest, clock(day=1), 'day')
    assert label == 'Walk the grass while the Bug-Catching Contest waits for Tuesday'
    entered = clock(day=2)
    entered.byte = lambda name: {'wCurDay': 2, 'wDailyFlags1': 2}.get(name, 0)
    assert waiting_label(policy, contest, entered, 'day').endswith("waits for Thursday, as today's was entered")


def test_full_boxes_with_nothing_to_release_wait_for_no_catch_and_free_the_league(data):
    """A Gold run with all 14 boxes full walked Route 29 for 98% of a replay "while Lapras waits for
    Friday", and the same wait kept the postgame League run from starting. Lapras could not be kept."""
    from pokesim.gen2.collection import clock_wait, postgame_league, waiting_label
    policy = expedition(data)
    policy.completed = {'champion': 1}
    full = snapshot([lead()], owned=set(range(1, 252)) - {131})
    assert clock_wait(policy, full, clock(), 'day') == 'Lapras waits for Friday'
    policy.no_room = lambda snapshot: True
    full.can_catch = False
    assert clock_wait(policy, full, clock(), 'day') is None
    assert waiting_label(policy, full, clock(), 'day') == 'Walk the grass until a trade or a return brings new collection work'
    assert postgame_league(policy, full, clock(), 'day')


def test_a_time_of_day_encounter_names_the_species_and_the_time(data):
    from pokesim.gen2.collection import clock_wait
    night = {row['species'] for row in data.encounters if row['time'] == 'night'}
    day = {row['species'] for row in data.encounters if row['time'] != 'night'}
    species = min(night - day)
    owned = set(range(1, 252)) - {species}
    wait = clock_wait(expedition(data), snapshot([lead()], owned=owned), clock(), 'day')
    assert wait == f'{data.species[species]["name"]} waits for night'
    assert clock_wait(expedition(data), snapshot([lead()], owned=owned), clock(), 'night') is None


def walk_anywhere(monkeypatch):
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal
    monkeypatch.setattr(training, 'walk_goal', lambda policy, snapshot, Goal_, label: Goal(
        'collection_train', label(), 'SILVER_CAVE_ROOM_1', 9, 31))


def test_without_exp_share_a_levelling_plan_trains_the_partner_in_the_lead(data, monkeypatch):
    from pokesim.gen2.breeding import hatching
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import identity, journey
    walk_anywhere(monkeypatch)
    trainee = mon(94, box=3, level=30)
    eggs = [mon(175, box=2, position=i, egg=True, level=5, dvs=(i,) * 5) for i in range(3)]
    state = snapshot([lead()], [trainee, *eggs])
    storage = SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=1, y=1, face='up')
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, storage_goal=lambda snapshot: storage,
                             release_target=lambda snapshot: None, no_room=lambda snapshot: False)
    # A roamer lead plan set this levelling project after the cartridge's only Exp. Share was traded away.
    policy.collection['training'] = {'identity': identity(trainee), 'target': 94, 'item': None, 'species': 94,
                                     'terminal': True, 'level_goal': 37}
    assert journey(policy, state, clock(), Goal, terminal=True).key == 'collection_train_pc'
    # Once it joins, the boxed eggs come out too, and the walk trains it in front.
    # The Togepi line is still unregistered, so its eggs are worth the trip.
    joined = snapshot([lead(), mon(94, box=None, position=1, level=30)], eggs, owned=set(range(1, 252)) - {175, 176})
    assert hatching(policy, joined, Goal).key == 'collection_hatch_pc'
    state = snapshot([lead(), mon(94, box=None, position=1, level=30)])
    goal = journey(policy, state, clock(), Goal, terminal=True)
    assert goal.key == 'collection_train' and goal.label.endswith('toward level 37 in the lead')


def test_without_exp_share_the_terminal_walk_still_trains_someone(data, monkeypatch):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey
    walk_anywhere(monkeypatch)
    state = snapshot([lead(), mon(94, box=None, position=1, level=99, experience=1050000)])
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, no_room=lambda snapshot: False)
    goal = journey(policy, state, clock(), Goal, terminal=True)
    assert goal.key == 'collection_train' and goal.label == 'Train 94 toward level 100 in the lead'
    assert policy.collection['training']['terminal']


def shareless_policy(data, party, project):
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.training import identity
    policy = Policy.__new__(Policy)
    policy.data, policy.goal = data, None
    policy.collection = {'training': {'identity': identity(project), 'target': project.species, 'item': None,
                                      'species': project.species, 'terminal': True}}
    return policy, snapshot(party)


def test_without_exp_share_the_trainee_keeps_the_lead(data):
    trainee = mon(94, box=None, position=1, level=20, hp=60, max_hp=60)
    policy, state = shareless_policy(data, [lead(), trainee], trainee)
    reorder = policy.level_lead(state)
    assert reorder.slot == 1 and tuple(reorder.identity[1]) == trainee.dvs
    policy, state = shareless_policy(data, [trainee, lead()], trainee)
    assert policy.level_lead(state) is None
    # With an Exp. Share the strongest leads again.
    held = snapshot([trainee, lead()])
    held.items = ((data.items['EXP_SHARE'], 1),)
    assert policy.level_lead(held).slot == 1


def test_a_set_aside_roaming_sleeper_does_not_keep_the_trainee_out_of_battle(data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import identity
    sleeper = lead()
    trainee = mon(94, box=None, position=1, level=20, hp=60, max_hp=60)
    policy, state = shareless_policy(data, [sleeper, trainee], trainee)
    # The roaming search was put off for later and left its sleeper on record.
    policy.collection['roam_lead'] = identity(sleeper)
    policy.goal = Goal('collection_train', 'Train 94 toward level 100 in the lead', 'SILVER_CAVE_ROOM_1', 9, 31)
    reorder = policy.level_lead(state)
    assert reorder.slot == 1 and tuple(reorder.identity[1]) == trainee.dvs
    # While the search itself runs, its sleeper keeps the lead.
    policy.goal = Goal('collection_roam_hunt', 'Track Raikou through Johto', 'ROUTE_36', 5, 5)
    assert policy.level_lead(state) is None


def test_a_leading_trainee_switches_out_once_when_outmatched(data):
    trainee = mon(94, box=None, position=0, level=20, hp=60, max_hp=60)
    strong = lead()
    strong.hp, strong.max_hp, strong.position = 300, 300, 1
    policy, state = shareless_policy(data, [trainee, strong], trainee)
    state.enemy_level = 40
    assert policy.trainee_switch(state, 0) == 1
    # Once the partner is out the switch never repeats, and a trainee well above the opponent fights on.
    assert policy.trainee_switch(state, 1) is None
    state.enemy_level = 10
    assert policy.trainee_switch(state, 0) is None


def full_bag(data, *, share=True):
    """An items pocket with every entry taken, holding the Exp. Share when ``share`` is set."""
    rows = [(item, 1) for item, attributes in sorted(data.item_attributes.items())
            if attributes['pocket'] == 'ITEM' and item not in (data.items['EXP_SHARE'], data.items['PEARL'])]
    return ([(data.items['EXP_SHARE'], 1)] if share else []) + rows[:20 - share]


def pc_goal(snapshot):
    return SimpleNamespace(map_name='GOLDENROD_POKECENTER_1F', x=1, y=1, face='up')


def kept_bag(data, *, share=True):
    """An items pocket with every entry taken by items some plan uses, so none can be put away."""
    from pokesim.gen2.training import KEPT_ITEMS
    rows = [(data.items[name], 1) for name in sorted(KEPT_ITEMS - {'EXP_SHARE'}) if name in data.items]
    rows += [(data.items[name], 1) for name in ('FIRE_STONE', 'WATER_STONE', 'THUNDERSTONE', 'LEAF_STONE')]
    return ([(data.items['EXP_SHARE'], 1)] if share else []) + rows[:20 - share]


def test_a_trainee_holding_an_item_the_full_bag_cannot_take_back_trains_in_the_lead(data, monkeypatch):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey, trainee_slot
    walk_anywhere(monkeypatch)
    trainee = mon(90, box=None, position=1, level=30, held_item=data.items['PEARL'])
    policy, state = shareless_policy(data, [lead(), trainee], trainee)
    policy.collection['training']['level_goal'] = 50
    policy.demand, policy.decisions, policy.no_room = {}, 1000, lambda snapshot: False
    policy.storage_goal = pc_goal
    state.map = data.map_ids['GOLDENROD_POKECENTER_1F']
    state.pockets['items'] = full_bag(data)
    state.items = tuple(state.pockets['items'])
    # Giving the share would hand the Pearl back to a pocket with no free entry, which the game refuses,
    # so a spare item goes to the PC first.
    goal = journey(policy, state, clock(), Goal, terminal=True)
    assert goal.key == 'collection_tidy' and policy.collection['tidy_item'] in dict(state.items)
    # A bag of items some plan uses has nothing to put away, so the trainee leads instead.
    state.pockets['items'] = kept_bag(data)
    state.items = tuple(state.pockets['items'])
    goal = journey(policy, state, clock(), Goal, terminal=True)
    assert goal.key == 'collection_train' and goal.label.endswith('in the lead')
    assert trainee_slot(policy, state) == 1
    # One free entry lets the swap through.
    state.pockets['items'] = state.pockets['items'][:-1]
    state.items = tuple(state.pockets['items'])
    assert journey(policy, state, clock(), Goal, terminal=True).key == 'collection_equip'
    assert trainee_slot(policy, state) is None
    # Taking the share from another member needs room for the share itself.
    holder = mon(157, box=None, position=0, dvs=(1,) * 5, moves=(57, 15, 53, 0), level=100, trainer_id=1,
                 held_item=data.items['EXP_SHARE'])
    bare = mon(90, box=None, position=1, level=30)
    policy, state = shareless_policy(data, [holder, bare], bare)
    policy.collection['training']['level_goal'] = 50
    policy.demand, policy.decisions, policy.no_room = {}, 1000, lambda snapshot: False
    policy.storage_goal = pc_goal
    state.map = data.map_ids['GOLDENROD_POKECENTER_1F']
    state.pockets['items'] = kept_bag(data, share=False)
    state.items = tuple(state.pockets['items'])
    assert journey(policy, state, clock(), Goal, terminal=True).label.endswith('in the lead')
    state.pockets['items'] = full_bag(data, share=False)
    state.items = tuple(state.pockets['items'])
    assert journey(policy, state, clock(), Goal, terminal=True).key == 'collection_tidy'


def test_an_item_task_the_game_keeps_refusing_stands_the_project_down(data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import standing_down, train_key
    from pokesim.gen2.training import arrive, identity
    trainee = mon(90, box=None, position=1, level=30, held_item=data.items['PEARL'])
    policy, state = shareless_policy(data, [lead(), trainee], trainee)
    policy.blocked, policy.decisions = {}, 1000
    policy.goal = Goal('collection_equip', 'Give Exp. Share to 90', 'GOLDENROD_POKECENTER_1F', 9, 2)
    state.frame = 0
    assert arrive(policy, state) == 'wait'
    task = policy.menu
    key = policy.task_key(task)
    for refusal in range(1, 3):
        # The game refused the shortcut, so the policy blocks it for a while and the plan waits it out.
        policy.menu = None
        policy.blocked[key] = state.frame + policy.RETRY_FRAMES
        assert arrive(policy, state) == 'wait' and policy.menu is None
        state.frame += 1
        assert arrive(policy, state) == 'wait'
        # Each block counts once however many steps it lasts.
        assert len(policy.collection['training']['refused']) == refusal
        state.frame = policy.blocked[key]
        assert arrive(policy, state) == 'wait' and policy.menu is not None
    # The third refusal in a row drops the project for the stand-down period.
    policy.menu = None
    policy.blocked[key] = state.frame + policy.RETRY_FRAMES
    assert arrive(policy, state) is None
    assert policy.collection['training'] is None
    assert standing_down(policy, train_key(identity(trainee)))


def test_without_exp_share_a_stone_evolution_still_runs(data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.training import journey
    eevee = mon(133, box=None, position=1, level=20)
    state = snapshot([lead(), eevee], owned=set(range(1, 252)) - {134})
    state.items = ((data.items['WATER_STONE'], 1),)
    state.map = data.map_ids['GOLDENROD_CITY']
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1000, no_room=lambda snapshot: False)
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'collection_evolve_item' and policy.collection['training']['target'] == 134


def test_the_exp_share_holder_is_never_released_or_traded(data):
    from pokesim.gen2.release import EXP_SHARE, spares
    from pokesim.gen2.trading import _kept
    assert data.items['EXP_SHARE'] == EXP_SHARE
    holder = mon(16, box=0, position=0, held_item=EXP_SHARE, dvs=(3, 3, 3, 3, 3))
    other = mon(16, box=0, position=1, held_item=data.items['POTION'], dvs=(2, 2, 2, 2, 2))
    best = mon(16, box=0, position=2, dvs=(12, 12, 12, 12, 12))
    state = snapshot([lead()], [holder, other, best])
    assert spares(state, lenient=True) == [other]
    assert _kept({'species': 16, 'held_item': EXP_SHARE, 'trade_key': 'k', 'dvs': [3] * 5}, set()) == 'Holds the Exp. Share'


def test_a_finished_run_loops_the_league_instead_of_walking_the_grass(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    # A live Crystal run with every Pokémon, sixteen badges and a level 100 party walked Route 29 for
    # hours once its last training ended. A finished Gen I run loops the League, and so does this one.
    # Here the League is the only postgame activity left: no balls for a hunt and nobody to train.
    from pokesim.gen2 import postgame
    journey_of_postgame = postgame.journey
    patrols = stub_activities(monkeypatch)
    monkeypatch.setattr(postgame, 'journey', journey_of_postgame)
    monkeypatch.setattr(postgame, 'trainee', lambda policy, snapshot: None)
    party = [mon(157 + i, box=None, position=i, level=100) for i in range(6)]
    state = snapshot(party)
    state.pockets = {'balls': []}
    state.hall_of_fame_count = 180
    state.event = lambda name: name != 'EVENT_WILLS_ROOM_ENTRANCE_CLOSED'
    policy = expedition(data)
    policy.completed = {'tower': 1, 'champion': 1, 'red': 1}
    policy.person = lambda snapshot, key, label, *where: Goal(key, label, where[0], 0, 0)
    goal = journey(policy, state, clock(), Goal)
    assert not patrols and goal.key == 'funds_will' and policy.collection['phase'] == 'league'
    assert goal.label == 'Challenge the Elite Four again for another Hall of Fame entry'
    assert 'Walk the grass' not in goal.label
    # The run continues until its Hall of Fame entry, then the next decision starts another.
    assert policy.collection['league_loop'] == 181
    policy.in_league = lambda snapshot: True
    state.event = lambda name: not name.startswith(('EVENT_BEAT_ELITE_4_', 'EVENT_BEAT_CHAMPION')) or name.endswith('WILL')
    assert journey(policy, state, clock(), Goal).key == 'funds_koga'
    state.hall_of_fame_count = 181
    policy.in_league = lambda snapshot: False
    state.event = lambda name: True
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'funds_arrive' and policy.collection['league_loop'] == 182 and not patrols


def test_a_league_loop_ends_when_the_team_has_too_few_attacks_for_it(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    # A live Crystal run took a level 100 lead and its HM carriers into the League, ran out of
    # attacks at Lance and never finished the battle. Five Hydro Pumps cannot cover 26 opponents.
    patrols = stub_activities(monkeypatch)
    lead = mon(157, box=None, level=100, moves=(56, 0, 0, 0), pp=(5, 0, 0, 0))
    state = snapshot([lead, mon(16, box=None, position=1, level=20)])
    state.pockets = {'balls': []}
    state.hall_of_fame_count = 180
    policy = expedition(data)
    policy.completed = {'tower': 1, 'champion': 1}
    policy.collection['league_loop'] = 181
    policy.person = lambda snapshot, key, label, *where: Goal(key, label, where[0], 0, 0)
    goal = journey(policy, state, clock(), Goal)
    assert 'league_loop' not in policy.collection and not goal.key.startswith('funds_') and patrols
    # Inside the League there is no way back, so an attempt already under way carries on.
    policy.collection['league_loop'] = 181
    policy.in_league = lambda snapshot: True
    assert journey(policy, state, clock(), Goal).key.startswith('funds_') and policy.collection['league_loop'] == 181


def test_the_league_loop_waits_for_unfinished_work(data, monkeypatch):
    from pokesim.gen2.collection import journey
    from pokesim.gen2.policy import Goal
    party = [mon(157, box=None, level=100)]
    policy = expedition(data)
    policy.completed = {'tower': 1, 'champion': 1}
    policy.person = lambda snapshot, key, label, *where: Goal(key, label, where[0], 0, 0)
    # Training still has work, so it goes first.
    train = Goal('collection_train', 'Train MON toward level 100', 'SILVER_CAVE_ROOM_1', 9, 31)
    patrols = stub_activities(monkeypatch, **{'training.journey': train})
    assert journey(policy, snapshot(party), clock(), Goal).key == 'collection_train'
    # A clock-gated encounter keeps the walk that names it.
    patrols = stub_activities(monkeypatch)
    state = snapshot(party, owned=set(range(1, 252)) - {131})
    goal = journey(policy, state, clock(), Goal)
    assert goal.key == 'collection_idle' and patrols == ['Walk the grass while Lapras waits for Friday']
    # Carried eggs hatch on the walk.
    patrols = stub_activities(monkeypatch)
    eggs = snapshot(party + [mon(175, box=None, position=1, egg=True)])
    assert journey(policy, eggs, clock(), Goal).key == 'collection_idle' and patrols
    # A run that has not beaten the Champion has no League loop yet.
    patrols = stub_activities(monkeypatch)
    policy = expedition(data)
    assert journey(policy, snapshot(party), clock(), Goal).key == 'collection_idle'
    assert 'league_loop' not in policy.collection
