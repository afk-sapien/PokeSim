"""The Tower team's chosen lead is not swapped back by the general reorder that leads with the highest level."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokesim.gen2.menus import Lead
from pokesim.gen2.teams import key


@pytest.fixture(scope='module')
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'crystal')


def mon(trainer_id, level, stats):
    dvs = (1, 2, 3, 4, 5)
    return SimpleNamespace(trainer_id=trainer_id, dvs=dvs, level=level, stats=stats, moves=(33,), species=16,
                           egg=False, held_item=0, to_dict=lambda: {'trainer_id': trainer_id, 'dvs': list(dvs)})


def view(crystal, party):
    return SimpleNamespace(map=crystal.map_ids['OLIVINE_POKECENTER_1F'], party=tuple(party), stored=(), items=(),
                           x=9, y=2, frame=1)


def test_the_tower_lead_and_the_level_lead_do_not_swap_forever(crystal):
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2.tower import journey
    policy = Policy(crystal, seed=1, starter='cyndaquil')
    policy.memory = None
    # The live Crystal stall: the strongest partner sat more than five levels below the highest-level one.
    high, strong, third = mon(1, 70, (150, 90, 90, 90, 90, 90)), mon(2, 55, (200, 160, 160, 160, 160, 160)), \
        mon(3, 60, (150, 90, 90, 90, 90, 90))
    team = [high, strong, third]
    policy.collection['tower'] = {'team': [key(row) for row in team], 'original': [key(row) for row in team],
                                  'cap': 70, 'entered': False, 'returning': False, 'trained': True,
                                  'preparation_center': True, 'previous_training': None}
    assert journey(policy, view(crystal, team), Goal).key == 'tower_lead'
    assert policy.menu == Lead(1, (2, (1, 2, 3, 4, 5)))
    policy.menu = None
    reordered = view(crystal, [strong, high, third])
    assert journey(policy, reordered, Goal).key == 'tower_enter'
    assert policy.level_lead(reordered) is None
    # Outside a prepared challenge the highest level still leads.
    policy.collection.pop('tower')
    assert policy.level_lead(reordered) == Lead(1, (1, (1, 2, 3, 4, 5)))
