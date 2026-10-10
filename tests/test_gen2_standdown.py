"""Hunts and training that cannot progress stand down, and a reload does not forget it."""
from types import SimpleNamespace

from pokesim.gen2 import collection, training
from pokesim.gen2.menus import ChangeBox, Release, Use
from pokesim.gen2.standdown import (STAND_DOWN, carry_over, hunt_key, stalled_objectives, standing_down,
                                    train_key)


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
    restored.collection = {'activity_team': ['a', 'b'], 'activity_blocked': 3}
    carry_over(restored, stalled_objectives(stuck))
    assert 'activity_team' not in restored.collection
    assert restored.collection['activity_failed']['team'] == ['a', 'b']
    assert restored.collection['activity_failed']['until'] > restored.decisions
