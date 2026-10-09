"""Activity teams are assembled copy for copy at the PC and stand down when they cannot be."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokesim.gen2.menus import ChangeBox, Release, Storage
from pokesim.gen2.teams import BLOCKED_LIMIT, arrive, assemble, assembled, key


@pytest.fixture(scope='module')
def real_data():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'crystal')


def mon(name, *, box=None, position=0, dvs=(8, 8, 8, 8, 8), trainer_id=None, species=16):
    trainer = trainer_id if trainer_id is not None else sum(map(ord, name))
    return SimpleNamespace(name=name, box=box, position=position, dvs=dvs, trainer_id=trainer, species=species,
                           to_dict=lambda: {'trainer_id': trainer, 'dvs': list(dvs)})


def snapshot(party, stored=(), *, active_box=0, boxes=(10,) * 14):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), active_box=active_box, box_counts=boxes)


class Policy:
    def __init__(self, spare=None):
        self.collection, self.decisions, self.menu, self.spare = {}, 100, None, spare
        self.goal = SimpleNamespace(key='collection_activity_team')

    def storage_goal(self, _):
        return SimpleNamespace(map_name='OLIVINE_POKECENTER_1F', x=9, y=2, face='up')

    def release_target(self, _):
        return self.spare


def Goal(key, label, map_name, x, y, face=None):
    return SimpleNamespace(key=key, label=label, map_name=map_name)


def test_twins_sharing_an_identity_are_counted_copy_for_copy():
    a, b, c = mon('a'), mon('b'), mon('c')
    twin = mon('twin', trainer_id=a.trainer_id)
    policy = Policy()
    view = snapshot([a, twin, b, c])
    wanted = [key(a), key(b), key(c)]
    assert not assembled(view, wanted)
    assert assemble(policy, view, wanted, Goal, 'Prepare').key == 'collection_activity_team'
    assert arrive(policy, view) == 'a'
    assert policy.menu == Storage('DEPOSIT', 1, 4)


def test_full_storage_releases_a_spare_to_make_room():
    a, b, extra = mon('a'), mon('b'), mon('extra')
    spare = mon('spare', box=3, position=7)
    policy = Policy(spare)
    policy.collection['activity_team'] = [key(a), key(b)]
    assert arrive(policy, snapshot([a, b, extra], boxes=(20,) * 14)) == 'a'
    assert policy.menu == ChangeBox(3)
    assert arrive(policy, snapshot([a, b, extra], active_box=3, boxes=(20,) * 14)) == 'a'
    assert isinstance(policy.menu, Release) and (policy.menu.box, policy.menu.position) == (3, 7)


def test_withdrawing_comes_first_so_deposits_find_room():
    a, b, wanted = mon('a'), mon('b'), mon('w', box=2, position=4)
    policy = Policy()
    policy.collection['activity_team'] = [key(wanted)]
    assert arrive(policy, snapshot([a, b], [wanted], active_box=2, boxes=(20,) * 14)) == 'a'
    assert policy.menu == Storage('WITHDRAW', 4, 2)


def test_a_partner_that_is_gone_stands_the_team_down():
    a, gone = mon('a'), mon('gone')
    policy = Policy()
    wanted = [key(a), key(gone)]
    assert assemble(policy, snapshot([a]), wanted, Goal, 'Prepare') is None
    assert 'activity_team' not in policy.collection
    assert policy.collection['activity_failed']['team'] == wanted


def test_a_team_with_nothing_left_to_do_stands_down_and_waits_before_retrying():
    a, b, extra = mon('a'), mon('b'), mon('extra')
    policy = Policy()
    wanted = [key(a), key(b)]
    view = snapshot([a, b, extra], boxes=(20,) * 14)
    for _ in range(BLOCKED_LIMIT):
        assert assemble(policy, view, wanted, Goal, 'Prepare') is not None
        assert arrive(policy, view) == 'b'
    assert assemble(policy, view, wanted, Goal, 'Prepare') is None
    policy.decisions += 10
    assert assemble(policy, view, wanted, Goal, 'Prepare') is None
    policy.decisions += 10 ** 6
    assert assemble(policy, view, wanted, Goal, 'Prepare') is not None


def test_tower_challenge_stands_down_when_its_team_cannot_be_assembled(real_data):
    from pokesim.gen2.policy import Goal as RealGoal, Policy as RealPolicy
    from pokesim.gen2.tower import journey
    policy = RealPolicy(real_data, seed=1, starter='cyndaquil')
    policy.memory = None
    a, gone = mon('a'), mon('gone')
    previous = {'identity': [1, [1, 2, 3, 4]]}
    policy.collection['training'] = None
    policy.collection['tower'] = {'team': [key(a), key(gone)], 'original': [key(a)], 'cap': 30, 'entered': False,
                                  'returning': False, 'trained': True, 'preparation_center': True,
                                  'previous_training': previous}
    view = SimpleNamespace(map=real_data.map_ids['OLIVINE_POKECENTER_1F'], party=(a,), stored=(), frame=1)
    assert journey(policy, view, RealGoal) is None
    assert 'tower' not in policy.collection
    assert 'tower' not in policy.completed
    assert policy.collection['training'] == previous
    assert policy.collection['tower_after'] > policy.decisions
