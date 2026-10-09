"""A stalled healing trip can spend one rope without a persistent item retry loop."""
from dataclasses import replace

import pytest

from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS, MAPS
from test_collection import state
from test_strategy import mon
from shortcut_fakes import PRESS, Recorder


def depleted(**changes):
    return state(map=MAPS['VICTORY_ROAD_1F'], frame=1000,
                 party=(mon(hp=10, max_hp=100),), items=((ITEMS['ESCAPE_ROPE'], 2),), **changes)


def policy():
    p = StrategicPolicy(42)
    p.heal_latch = True
    p.goal = Goal('heal', 'Heal the party', 'Restore supplies')
    return p


def test_recovery_uses_one_rope_through_the_item_shortcut():
    p = policy()
    recorder = Recorder.on(p)
    actions = p._recover(depleted())
    assert actions[0] == PRESS
    assert recorder.last.kind == 'use_item' and recorder.last.item == ITEMS['ESCAPE_ROPE']
    assert p.escape_attempted and p.mode == 'escaping to heal'


def test_failed_attempt_does_not_repeat_after_checkpoint_or_trade_restore():
    p = policy()
    Recorder.on(p)
    s = depleted()
    p._recover(s)
    saved = p.state_dict()
    restored = policy()
    recorder = Recorder.on(restored)
    restored.load_state_dict(saved)
    restored.on_restore()
    restored.heal_latch = True
    for frame in (2000, 20000, 200000):
        restored._recover(replace(s, frame=frame))
    assert not recorder.started
    assert restored.escape_attempted


@pytest.mark.parametrize('change', [dict(items=()), dict(in_battle=1), dict(textbox=True),
                                   dict(start_menu=True), dict(map=MAPS['PALLET_TOWN'])])
def test_unavailable_rope_or_unsafe_context_does_not_use_an_item(change):
    p = policy()
    recorder = Recorder.on(p)
    p._recover(replace(depleted(), **change))
    assert not recorder.started and not p.escape_attempted


def test_normal_healthy_exploration_does_not_spend_rope():
    p = policy()
    recorder = Recorder.on(p)
    p.heal_latch = False
    p._recover(depleted())
    assert not recorder.started and not p.escape_attempted


def test_successful_healing_allows_a_future_emergency_attempt():
    p = policy()
    p.escape_attempted = True
    healed = replace(depleted(), map=MAPS['PALLET_TOWN'], party=(mon(hp=100, max_hp=100),))
    p._overworld(healed, bytearray(65536))
    assert not p.escape_attempted
    p.heal_latch = True
    recorder = Recorder.on(p)
    assert p._recover(depleted())[0] == PRESS
    assert recorder.last.item == ITEMS['ESCAPE_ROPE']
