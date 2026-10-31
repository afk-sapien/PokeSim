"""A Gen 2 supply errand stays the goal on the menu steps at the clerk.

The menu branch returned after the journey goal was set and before the errand could replace it, so
the purchases ran under the journey goal and the shop trip split at every menu.
"""
from tests.test_gen2_battle_start import Cartridge, data, policy_on_route  # noqa: F401

from pokesim.gen2.policy import Goal

SHOP = Goal('buy_supplies', 'Buy capture supplies', 'VIOLET_MART', 1, 3, 'left')


def test_a_menu_step_on_the_shop_trip_keeps_the_errand(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.errand = SHOP
    policy.menu = object()
    policy.menu_step = lambda snapshot, mem: 'a'
    policy.step(snapshot, Cartridge(data, wMapWidth=20))
    assert policy.goal is SHOP


def test_a_menu_step_with_no_errand_keeps_the_journey_goal(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.menu = object()
    policy.menu_step = lambda snapshot, mem: 'a'
    policy.step(snapshot, Cartridge(data, wMapWidth=20))
    assert policy.goal.key == 'collection_wait'
