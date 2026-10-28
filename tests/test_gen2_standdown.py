"""Hunts and training that cannot progress stand down, and a reload does not forget it."""
from types import SimpleNamespace

from pokesim.gen2 import collection, training
from pokesim.gen2.menus import ChangeBox, Release, Use
from pokesim.gen2.standdown import (STAND_DOWN, TRAINING_DECISIONS, carry_over, hunt_key, migrate, pc_key,
                                    search_expected, stalled_objectives, standing_down, team_key, train_key)


class Policy:
    def __init__(self, goal, *, blocked=(), spare=None):
        self.collection, self.decisions, self.menu = {}, 1000, None
        self.goal = SimpleNamespace(key=goal)
        self.data = SimpleNamespace(items={'SUPER_ROD': 61, 'EXP_SHARE': 57})
        self.blocked, self.spare = list(blocked), spare

    def allowed(self, task, snapshot):
        return task not in self.blocked

    def release_target(self, snapshot):
        return self.spare


def mon(name, *, box=None, position=0, trainer_id=1, dvs=(1, 2, 3, 4, 5), species=40):
    return SimpleNamespace(name=name, box=box, position=position, trainer_id=trainer_id, dvs=dvs, species=species,
                           moves=(), held_item=0, level=50, egg=False)


def test_a_refused_rod_drops_the_hunt_and_stands_it_down():
    policy = Policy('collection_fish', blocked=[Use(61)])
    policy.collection['target'] = {'species': 223, 'method': 'super rod'}
    assert collection.arrive(policy, SimpleNamespace()) == 'wait'
    assert policy.menu is None and policy.collection['target'] is None
    assert standing_down(policy, hunt_key(223))
    policy.decisions += STAND_DOWN
    assert not standing_down(policy, hunt_key(223))


def test_a_rod_the_game_accepts_is_used():
    policy = Policy('collection_fish')
    policy.collection['target'] = {'species': 223, 'method': 'super rod'}
    assert collection.arrive(policy, SimpleNamespace()) == 'wait'
    assert policy.menu == Use(61)


def full_party(stored):
    party = tuple(mon(f'p{i}', trainer_id=100 + i) for i in range(6))
    return SimpleNamespace(party=party, stored=(stored,), active_box=0, box_counts=(20,) * 14)


def test_training_with_full_storage_releases_a_spare_first():
    wanted = mon('Wigglytuff', box=4, position=2)
    spare = mon('spare', box=7, position=3, trainer_id=9)
    policy = Policy('collection_train_pc', spare=spare)
    policy.collection['training'] = {'identity': training.identity(wanted)}
    view = full_party(wanted)
    assert training.arrive(policy, view) == 'a'
    assert policy.menu == ChangeBox(7)
    view.active_box = 7
    assert training.arrive(policy, view) == 'a'
    assert isinstance(policy.menu, Release) and (policy.menu.box, policy.menu.position) == (7, 3)


def test_training_that_cannot_make_room_stands_down():
    wanted = mon('Wigglytuff', box=4, position=2)
    policy = Policy('collection_train_pc')
    policy.collection['training'] = {'identity': training.identity(wanted)}
    assert training.arrive(policy, full_party(wanted)) == 'b'
    assert policy.collection['training'] is None
    assert standing_down(policy, train_key(training.identity(wanted)))


def test_a_reload_keeps_the_stalled_hunt_and_training_standing_down():
    stuck = Policy('collection_train_pc')
    stuck.collection['target'] = {'species': 201}
    stuck.collection['training'] = {'identity': [5, [1, 2, 3, 4, 5]]}
    stuck.collection['stood_down'] = {hunt_key(223): 900}
    stalled = stalled_objectives(stuck)
    restored = Policy(None)
    restored.decisions = 400
    restored.collection = {'target': {'species': 201}, 'training': {'identity': [5, [1, 2, 3, 4, 5]]}}
    carry_over(restored, stalled)
    assert restored.collection['target'] is None and restored.collection['training'] is None
    for key in (hunt_key(201), train_key([5, [1, 2, 3, 4, 5]]), hunt_key(223)):
        assert standing_down(restored, key)
    assert restored.collection['stood_down'][hunt_key(223)] == 400


def test_a_reload_during_team_assembly_stands_the_team_down():
    stuck = Policy('collection_activity_team')
    stuck.collection['activity_team'] = ['a', 'b']
    restored = Policy(None)
    restored.collection = {'activity_team': ['a', 'b'], 'progress_frames': {pc_key(['a', 'b']): 3}}
    carry_over(restored, stalled_objectives(stuck))
    assert 'activity_team' not in restored.collection
    assert pc_key(['a', 'b']) not in restored.collection['progress_frames']
    assert standing_down(restored, team_key(['a', 'b']))


def test_training_stands_down_after_three_trips_without_experience_and_gains_reset_the_count():
    trainee = SimpleNamespace(trainer_id=1, dvs=(1, 2, 3, 4, 5), experience=1000)
    policy = Policy('collection_train')
    policy.collection['training'] = {'identity': training.identity(trainee)}
    view = SimpleNamespace(party=(trainee,))
    budget = 3 * TRAINING_DECISIONS
    for _ in range(budget - 1):
        policy.decisions += 1
        training.observe(policy, view)
    gained = SimpleNamespace(party=(SimpleNamespace(trainer_id=1, dvs=(1, 2, 3, 4, 5), experience=1100),))
    training.observe(policy, gained)
    assert policy.collection['training'] and not policy.collection['progress_frames']
    for _ in range(budget):
        policy.decisions += 1
        training.observe(policy, gained)
    assert policy.collection['training'] is None
    # The trip had gained experience, so it waits the base time only.
    assert standing_down(policy, train_key(training.identity(trainee)))
    assert not policy.collection['stand_downs']


def test_a_better_dv_hunt_is_budgeted_per_catch():
    policy = Policy('collection_hunt')
    activity = {'kind': 'quality', 'species': 40, 'row': {'chance': 50}, 'caught': 0,
                'expected': search_expected(50)}
    policy.collection['postgame'] = {'activity': activity}
    budget = round(3 * search_expected(50))
    for _ in range(budget - 1):
        collection.observe_search(policy, SimpleNamespace())
    activity['caught'] = 1
    collection.observe_search(policy, SimpleNamespace())
    assert not standing_down(policy, hunt_key(40))
    for _ in range(budget):
        collection.observe_search(policy, SimpleNamespace())
    assert standing_down(policy, hunt_key(40))


def test_the_catch_battle_does_not_spend_a_better_dv_hunt_budget():
    policy = Policy('collection_hunt')
    activity = {'kind': 'quality', 'species': 55, 'row': {'chance': 50}, 'caught': 0,
                'expected': search_expected(50)}
    policy.collection['postgame'] = {'activity': activity}
    budget = round(3 * search_expected(50))
    for _ in range(budget - 1):
        collection.observe_search(policy, SimpleNamespace(in_battle=1, enemy_species=60))
    # A dozen balls at a Golduck at full health is more than the whole search was expected to take.
    for _ in range(2 * budget):
        collection.observe_search(policy, SimpleNamespace(in_battle=1, enemy_species=55))
    assert not standing_down(policy, hunt_key(55))
    collection.observe_search(policy, SimpleNamespace(in_battle=0, enemy_species=0))
    assert standing_down(policy, hunt_key(55))


def test_an_older_save_moves_its_counts_onto_the_monitor():
    policy = Policy(None)
    policy.collection = {'carrier_decisions': {'61': 500}, 'activity_team': ['a'], 'activity_blocked': 5,
                         'postgame': {'activity': {'kind': 'shiny', 'unavailable_steps': 4}}}
    migrate(policy)
    assert policy.collection['progress_frames'] == {pc_key(['a']): 5}
    assert 'carrier_decisions' not in policy.collection and 'activity_blocked' not in policy.collection
    assert 'unavailable_steps' not in policy.collection['postgame']['activity']
