"""A Gen 2 battle shortcut ends with the battle, and a remedy still runs out of battle.

An Attack, Throw, Learn, Send or Flee task begun in battle kept stepping after the battle byte dropped.
On the leftover battle text it pressed A or waited, twice, before the walk could start.
"""
from tests.test_gen2_battle_start import Cartridge, data, policy_on_route  # noqa: F401

from pokesim.gen2.menus import Attack, Remedy
from pokesim.runtime.policy import PolicyContext


class Walked(Exception):
    """The step went on past the battle shortcuts to the overworld decision."""


def stepped(data, monkeypatch, task):
    """One step out of battle with ``task`` running: the policy, its menu steps, and whether it went on."""
    policy, snapshot, _, _ = policy_on_route(data, monkeypatch)
    calls = []
    policy.menu = task
    policy.menu_step = lambda snapshot, mem: calls.append(snapshot.frame) or 'a'

    def observe(snapshot, interrupted=False):
        raise Walked
    policy.nav.observe = observe
    try:
        policy.step(PolicyContext(snapshot, policy.clock, Cartridge(data, wMapWidth=20)))
    except Walked:
        return policy, calls, True
    return policy, calls, False


def test_an_attack_begun_in_battle_ends_when_the_battle_ends(data, monkeypatch):
    policy, calls, walked = stepped(data, monkeypatch, Attack(0))
    assert calls == [] and policy.menu is None and walked


def test_a_remedy_still_runs_out_of_battle(data, monkeypatch):
    task = Remedy(data.items['POTION'], 0, 1)
    policy, calls, walked = stepped(data, monkeypatch, task)
    assert calls and policy.menu is task and policy.mode == 'Heal the team' and not walked
