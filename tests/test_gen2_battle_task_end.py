"""A Gen 2 battle shortcut ends with the battle, and a remedy still runs out of battle.

An Attack, Throw, Learn, Send or Flee task begun in battle kept stepping after the battle byte dropped.
On the leftover battle text it pressed A or waited, twice, before the walk could start.

After that, the script that ran the battle has stopped but ``wScriptRunning`` stays set until the
overworld's next step, so the conversation rule pressed A every 44 frames into a map that read no button.
It now waits with no press until that step.
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


def after_a_script(data, monkeypatch, flags):
    """One step with ``wScriptRunning`` set and no textbox, the script engine's flags at ``flags``."""
    policy, snapshot, _, _ = policy_on_route(data, monkeypatch)
    policy.heal.offer = lambda policy, snapshot: (None, None)
    snapshot.script_running = 255
    cartridge = Cartridge(data, wScriptRunning=255, wScriptFlags=flags, wMapWidth=20)
    return policy.step(PolicyContext(snapshot, policy.clock, cartridge))[0], policy, cartridge


def test_the_walk_waits_with_no_press_while_the_map_loads_after_a_script(data, monkeypatch):
    action, policy, cartridge = after_a_script(data, monkeypatch, 0)
    assert policy.mode == 'conversation' and action.button is None and action.gap == 0
    assert not action.stop(4)
    cartridge.values[tuple(data.symbols['wScriptRunning'])] = 0
    assert action.stop(8)


def test_a_running_script_still_gets_a(data, monkeypatch):
    action, policy, _ = after_a_script(data, monkeypatch, 0b100)
    assert policy.mode == 'conversation' and action.button == 'a'
