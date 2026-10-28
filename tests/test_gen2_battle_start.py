"""The plan must not be rebuilt while a wild battle is starting.

Gold and Silver postgame hunts in Silver Cave planned during the battle transition, when the screen
effect had drawn over the map blocks. The hunt found no grass, took it for an unloaded map and set a
wait goal that then lasted the whole battle, so most postgame hunting was counted as waiting.
"""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokecore.textmatch import ScreenText


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def memory(**values):
    return SimpleNamespace(byte=lambda name: values.get(name, 0))


class Cartridge:
    """Zeroed RAM with chosen bytes, read through the same symbols as the real cartridge."""

    def __init__(self, data, **values):
        self.values = {tuple(data.symbols[name]): value for name, value in values.items()}

    def __getitem__(self, key):
        bank, window = key if isinstance(key, tuple) else (0, key)
        return [self.values.get((bank, address), 0) for address in range(window.start, window.stop)]


def policy_on_route(data, monkeypatch):
    from pokesim.gen2 import contest, policy as module, ruins, tower
    from pokesim.gen2.policy import Goal, Policy
    monkeypatch.setattr(module, 'update_world', lambda *args: None)
    for part in (ruins, contest, tower):
        monkeypatch.setattr(part, 'control', lambda *args: None)
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.naming.step = lambda snapshot, mem: None
    policy.unloaded = lambda snapshot, mem: False
    policy.nav.observe = lambda snapshot: None
    policy.release_goal = lambda *args: None
    planned = []

    def journey(snapshot, mem):
        planned.append(snapshot.frame)
        return Goal('collection_wait', 'Wait for the encounter map to finish loading', 'SILVER_CAVE_ROOM_2', 7, 7)
    policy.journey = journey
    rows = tuple(' ' * 20 for _ in range(18))
    snapshot = SimpleNamespace(started=True, valid=True, in_battle=0, hall_of_fame_count=1, frame=10,
                               map=data.map_ids['SILVER_CAVE_ROOM_2'], x=7, y=7, party=(), event_flags=bytes(256), money=0, items=(),
                               tiles=rows, text=ScreenText('\n'.join(rows)))
    hunt = Goal('collection_hunt', 'Search for a stronger Golduck in Silver Cave Room 2', 'SILVER_CAVE_ROOM_2', 8, 7)
    return policy, snapshot, hunt, planned


def test_the_hunt_goal_carries_through_the_battle_transition(data, monkeypatch):
    policy, snapshot, hunt, planned = policy_on_route(data, monkeypatch)
    policy.goal = hunt
    # The wild battle script is running and has picked its Pokémon, but the battle screen is not up yet.
    policy.step(snapshot, Cartridge(data, wScriptRunning=255, wTempWildMonSpecies=55, wMapWidth=20))
    assert planned == []
    assert policy.goal is hunt


def test_other_scripts_still_replan(data, monkeypatch):
    policy, snapshot, hunt, planned = policy_on_route(data, monkeypatch)
    policy.goal = hunt
    # A script with no wild Pokémon chosen, such as a conversation, is planned as before.
    policy.step(snapshot, Cartridge(data, wScriptRunning=255, wMapWidth=20))
    assert planned == [10]
    assert policy.goal.key == 'collection_wait'


def test_battle_starting_reads_the_script_and_the_chosen_pokemon(data):
    from pokesim.gen2.policy import Policy
    policy = Policy(data, seed=1, starter='cyndaquil')
    assert policy.battle_starting(memory(wScriptRunning=255, wTempWildMonSpecies=200))
    assert not policy.battle_starting(memory(wScriptRunning=255))
    assert not policy.battle_starting(memory(wTempWildMonSpecies=55))
