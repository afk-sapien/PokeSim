"""A Gen 2 supply errand stays the goal on the menu steps at the clerk.

The menu branch returned after the journey goal was set and before the errand could replace it, so
the purchases ran under the journey goal and the shop trip split at every menu.
"""
from tests.test_gen2_battle_start import Cartridge, data, policy_on_route  # noqa: F401

from pokesim.gen2.pipeline import Ballot
from pokesim.gen2.policy import Goal
from pokesim.runtime.policy import PolicyContext

SHOP = Goal('buy_supplies', 'Buy capture supplies', 'VIOLET_MART', 1, 3, 'left')


def test_a_menu_step_on_the_shop_trip_keeps_the_errand(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    # The trip an earlier decision picked, with the offer it was picked under.
    picked = Ballot()
    picked.errand(SHOP, 'shop')
    policy.trip.start(SHOP, picked.running)
    policy.menu = object()
    policy.menu_step = lambda snapshot, mem: 'a'
    policy.step(PolicyContext(snapshot, policy.clock, Cartridge(data, wMapWidth=20)))
    assert policy.goal is SHOP


def test_a_menu_step_with_no_errand_keeps_the_journey_goal(data, monkeypatch):
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    policy.menu = object()
    policy.menu_step = lambda snapshot, mem: 'a'
    policy.step(PolicyContext(snapshot, policy.clock, Cartridge(data, wMapWidth=20)))
    assert policy.goal.key == 'collection_wait'


def deciding(data, monkeypatch, events=()):
    """A policy on the route whose step decides and then flies, so a test reads the decision alone."""
    from pokesim.gen2 import flight
    policy, snapshot, hunt, _ = policy_on_route(data, monkeypatch)
    snapshot.event = lambda name: name in events
    policy.errand_allowed = lambda snapshot, mem: True
    monkeypatch.setattr(flight, 'shortcut', lambda *args: 'fly')

    def step():
        policy.menu = None
        policy.step(PolicyContext(snapshot, policy.clock, Cartridge(data, wMapWidth=20)))
    return policy, step


def test_a_shop_errand_writes_its_purchase_only_when_the_step_runs_it(data, monkeypatch):
    # Rule A, from slice 4b: a restock with no route lately gives way to the journey goal and leaves no
    # purchase and no chosen shop behind.
    policy, step = deciding(data, monkeypatch)
    writes, waiting = [], {SHOP.key}
    policy.heal.offer = lambda policy, snapshot: (None, None)
    policy.shop.offer = lambda policy, snapshot: (SHOP, lambda: writes.append(SHOP.key))
    policy.no_route_waiting = lambda goal: goal.key in waiting
    step()
    assert policy.goal.key == 'collection_wait' and policy.trip.goal is None and writes == []
    waiting.clear()
    step()
    assert policy.goal is policy.trip.goal is SHOP and writes == [SHOP.key]


def test_a_partner_trip_sets_its_field_move_only_when_it_runs(data, monkeypatch):
    # A behaviour change of slice 4b: a partner trip that a heal overrides leaves the field move the
    # battles check as it was.
    heal = Goal('heal', 'Restore the team at a Pokémon Center', 'VIOLET_POKECENTER_1F', 3, 3, 'up')
    partner = Goal('fish_surf', 'Fish for a partner that can learn Surf', 'OLIVINE_CITY', 5, 5)
    policy, step = deciding(data, monkeypatch, events={'EVENT_GOT_HM03_SURF'})
    shores = []
    policy.no_room = lambda snapshot: False
    policy.partner_goal = lambda snapshot, move, shore=None: shores.append(shore) or partner
    policy.heal.offer = lambda policy, snapshot: (heal, None)
    step()
    assert policy.goal is heal and policy.partner_move is None and shores == [57]
    policy.heal.offer = lambda policy, snapshot: (None, None)
    step()
    assert policy.goal is partner and policy.partner_move == 57
