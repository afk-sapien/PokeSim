"""Choosing a Pokémon Center to heal at."""
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


def policy_at(data, monkeypatch, walks):
    from pokesim.gen2 import ledger
    from pokesim.gen2.policy import Policy
    monkeypatch.setattr(ledger, 'walk_spent', lambda data, snapshot, goal='walk': True)
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.completed['ice_path'] = 0
    policy.healing_map = data.map_ids['BLACKTHORN_POKECENTER_1F']
    # Each center's walk, as the maps it passes. A center left out has no known walk.
    steps = {data.map_ids[center]: [(None, (data.map_ids[name], 0, 0)) for name in names]
             for center, names in walks.items()}
    monkeypatch.setattr(policy.nav.regions, 'route', lambda snapshot, mid, targets, **flags: steps.get(mid))
    return policy


def snapshot(data, name, x, y):
    return SimpleNamespace(map=data.map_ids[name], x=x, y=y, frame=0, badges=255,
                           party=(SimpleNamespace(egg=False, moves=()),), event=lambda name: True)


def test_a_center_past_ice_path_is_never_the_healing_trip(data, monkeypatch):
    # Randomized Gold, badges_8 rung: the trip kept Blackthorn, whose walk goes through Ice Path, where
    # healing stands down. The party stepped into the cave, stepped out again for Will and chose
    # Blackthorn again, for 29000 frames.
    policy = policy_at(data, monkeypatch, {
        'BLACKTHORN_POKECENTER_1F': ['ROUTE_42', 'MAHOGANY_TOWN', 'ROUTE_44', 'ICE_PATH_1F', 'ICE_PATH_B1F',
                                     'BLACKTHORN_CITY', 'BLACKTHORN_POKECENTER_1F'],
        'VIOLET_POKECENTER_1F': ['VIOLET_POKECENTER_1F']})
    goal = policy.healing(snapshot(data, 'VIOLET_CITY', 31, 25))
    assert goal is not None and goal.map_name == 'VIOLET_POKECENTER_1F'
    assert policy.healing_map == data.map_ids['VIOLET_POKECENTER_1F']


def test_a_center_with_no_known_walk_is_chosen_by_the_map_links(data, monkeypatch):
    policy = policy_at(data, monkeypatch, {})
    assert policy.healing(snapshot(data, 'BLACKTHORN_CITY', 21, 30)).map_name == 'BLACKTHORN_POKECENTER_1F'


def mon(data, species, level, moves, pp):
    ids = {entry['constant']: mid for mid, entry in data.moves.items()}
    return SimpleNamespace(egg=False, species=species, level=level, hp=200, max_hp=200, status=0,
                           moves=tuple(ids[name] for name in moves), pp=tuple(pp))


def test_a_spare_weak_attack_does_not_hide_spent_strong_ones(data):
    # Gold after the League: a lone level 84 Typhlosion carried Kanto with Flamethrower and Strength.
    # Both ran out, but 30 PP of Cut kept the heal walk away, so it met Misty and Brock with Cut and
    # Swift alone. It fainted and the weak rest of the party could not finish either battle.
    from pokesim.gen2.ledger import battle_room, walk_spent
    from pokesim.planning.ledger import PP
    moves = ('FLAMETHROWER', 'STRENGTH', 'CUT', 'SWIFT')
    farfetchd = mon(data, 83, 18, ('PECK', 'SAND_ATTACK', 'LEER', 'FLY'), (35, 15, 30, 15))
    spent = SimpleNamespace(party=(mon(data, 157, 84, moves, (0, 0, 30, 20)), farfetchd))
    assert battle_room(data, spent)[PP] == 0
    assert walk_spent(data, spent)
    # One use of Strength left is still an attack worth fighting with.
    left = SimpleNamespace(party=(mon(data, 157, 84, moves, (0, 1, 30, 20)), farfetchd))
    assert battle_room(data, left)[PP] == 1
    assert not walk_spent(data, left)
    # A Pokémon whose attacks are all weak counts every one of them.
    assert battle_room(data, SimpleNamespace(party=(farfetchd,)))[PP] == 50
