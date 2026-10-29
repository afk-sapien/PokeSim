"""A Tower partner that trained past the challenge level stands the challenge down instead of looping."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokesim.gen2.teams import key


@pytest.fixture(scope='module')
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'crystal')


def mon(trainer_id, level):
    dvs = (1, 2, 3, 4, 5)
    return SimpleNamespace(trainer_id=trainer_id, dvs=dvs, level=level, stats=(60,) * 6, moves=(33,), species=16,
                           egg=False, held_item=0, to_dict=lambda **_: {'trainer_id': trainer_id, 'dvs': list(dvs)})


def screen(crystal, party, text, tiles=()):
    return SimpleNamespace(map=crystal.map_ids['BATTLE_TOWER_1F'], party=tuple(party), stored=(), items=(),
                           x=7, y=7, frame=1, text=text, tiles=list(tiles))


def test_partner_past_the_cap_stands_the_challenge_down(crystal, monkeypatch):
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(crystal, seed=1, starter='cyndaquil')
    policy.memory = None
    # The live Crystal stall: chosen for level 20 at 16 to 18, two partners trained to 21 at Silver Cave.
    team = [mon(1, 21), mon(2, 20), mon(3, 21)]
    original = [key(mon(9, 100))]
    policy.collection['tower'] = {'team': [key(row) for row in team], 'original': original, 'cap': 20,
                                  'entered': False, 'returning': False, 'trained': True,
                                  'preparation_center': True, 'previous_training': None}
    level_menu = SimpleNamespace(byte=lambda name: {'wBattleTowerRoomMenuJumptableIndex': 2, 'wcd4f': 2}[name])
    # At the level question the receptionist would only answer "A party POKéMON tops this level."
    assert tower.control(policy, screen(crystal, team, 'What level do you want to challenge? L:20'), level_menu) == 'b'
    prompt = screen(crystal, team, 'Cancel your BATTLE ROOM challenge? YES NO', ['│ YES│', '│▶NO │'])
    assert tower.control(policy, prompt, level_menu) == 'up'
    restore = Goal('restore', 'Restore the adventure team', 'OLIVINE_POKECENTER_1F', 5, 6)
    monkeypatch.setattr(tower, 'assemble', lambda policy, view, wanted, *args: restore if wanted == original else None)
    assert tower.journey(policy, screen(crystal, team, ''), Goal).key == 'restore'
    state = policy.collection['tower']
    assert state['abandoned'] and state['returning']
    assert 20 in tower.resting_caps(policy)
    monkeypatch.setattr(tower, 'assemble', lambda *args: None)
    assert tower.journey(policy, screen(crystal, team, ''), Goal) is None
    assert 'tower' not in policy.collection and 'tower_after' not in policy.collection


def test_partners_within_the_cap_still_choose_the_level(crystal):
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Policy
    policy = Policy(crystal, seed=1, starter='cyndaquil')
    team = [mon(1, 20), mon(2, 19), mon(3, 20)]
    policy.collection['tower'] = {'team': [key(row) for row in team], 'original': [], 'cap': 20,
                                  'entered': False, 'returning': False}
    level_menu = SimpleNamespace(byte=lambda name: {'wBattleTowerRoomMenuJumptableIndex': 2, 'wcd4f': 1}[name])
    assert tower.control(policy, screen(crystal, team, 'What level do you want to challenge? L:10'), level_menu) == 'up'
