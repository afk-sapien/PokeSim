"""The heal goal holds through dialogue on the way to a Pokémon Center.

Gold, badges_8 rung: on Victory Road the heal spans alternated with 44-frame league_will spans, because
each conversation step set the journey goal and returned before the heal could replace it. The nurse
talk ran under league_will, so the restore never landed in a heal span (#261).
"""
from tests.test_gen2_battle_start import Cartridge, data, policy_on_route  # noqa: F401

from pokesim.gen2.policy import Goal

HEAL = Goal('heal', 'Restore the team at a Pokémon Center', 'VIOLET_POKECENTER_1F', 3, 3, 'up')


def test_a_conversation_on_the_heal_trip_keeps_the_heal_goal(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.healing = lambda snapshot: HEAL
    policy.step(snapshot, Cartridge(data, wScriptRunning=255, wMapWidth=20))
    assert policy.mode == 'conversation' and policy.goal is HEAL


def test_a_conversation_with_nothing_to_heal_keeps_the_journey_goal(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.healing = lambda snapshot: None
    policy.step(snapshot, Cartridge(data, wScriptRunning=255, wMapWidth=20))
    assert policy.mode == 'conversation' and policy.goal.key == 'collection_wait'


def test_a_starting_battle_keeps_its_goal_through_the_script(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.goal = hunt
    policy.healing = lambda snapshot: HEAL
    policy.step(snapshot, Cartridge(data, wScriptRunning=255, wTempWildMonSpecies=55, wMapWidth=20))
    assert policy.goal is hunt
