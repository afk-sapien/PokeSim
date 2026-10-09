"""Locks protect the selected individual, including at release confirmation."""
from dataclasses import asdict

from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.progression import Goal
from pokesim.screen import Screen
from pokesim.trade.preferences import identity
from test_duplicates import stored, snapshot
from test_strategy import menu, mon
from shortcut_fakes import PRESS, Recorder


def test_lock_protects_only_that_individual_from_release():
    copies = [stored(i, trainer_id=100, dvs=(i + 1,) * 5, level=10 + i) for i in range(3)]
    s = snapshot(copies)
    key = identity(asdict(copies[0]))
    choices = {key: {'state': 'locked'}}
    policy = StrategicPolicy(7)
    policy.trade_preferences = lambda: choices
    assert policy._release_target(s) == (0, 1)
    choices[key] = {'state': 'auto'}
    assert policy._release_target(s) == (0, 0)


def test_lock_during_release_cancels_it():
    copies = [stored(i, trainer_id=100, dvs=(i + 1,) * 5, level=10 + i) for i in range(3)]
    s = snapshot(copies)
    policy = StrategicPolicy(7)
    recorder = Recorder.on(policy)
    choices = {}
    policy.trade_preferences = lambda: choices
    policy.goal = Goal('party_release', 'Make room', 'Free a slot')
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 1), top=(1, 1))
    assert policy._dispatch(s, Screen(memory), 'pc', memory)[0] == PRESS
    assert recorder.last.kind == 'release_pokemon'
    released = recorder.last.position
    assert not policy.release_changed(s) and policy.shortcut.active
    choices[identity(asdict(copies[released]))] = {'state': 'locked'}
    assert policy._release_target(s) != (0, released)
    assert policy.release_changed(s) and not policy.shortcut.active
    # A release prompt the shortcut does not own is always refused.
    confirm = menu({0: 'Once released, BULBASAUR', 1: 'is gone forever. OK?', 12: '  YES', 13: '  NO'},
                   (1, 12), top=(1, 12))
    assert policy._dispatch(s, Screen(confirm), 'yes_no', confirm)[0].button == 'down'


def test_locked_party_member_is_not_given_to_an_in_game_trader():
    partner = mon(trainer_id=100, dvs=(8,) * 5)
    s = snapshot([], party=(partner, mon(level=80)))
    policy = StrategicPolicy(7)
    policy.goal = Goal('collect_trade', 'Trade', 'Meet the trader')
    policy.collection.project = {'give': partner.species, 'map': s.map}
    choices = {identity(asdict(partner)): {'state': 'locked'}}
    policy.trade_preferences = lambda: choices
    memory = menu({1: '  BULBASAUR'}, (1, 1), top=(1, 1))
    assert policy._dispatch(s, Screen(memory), 'party', memory)[0].button == 'b'
    choices.clear()
    assert policy._dispatch(s, Screen(memory), 'party', memory)[0].button == 'a'
    choices[identity(asdict(partner))] = {'state': 'locked'}
    confirm = menu({12: '  YES', 13: '  NO'}, (1, 12), top=(1, 12))
    assert policy._dispatch(s, Screen(confirm), 'yes_no', confirm)[0].button == 'down'


def test_preference_update_uses_current_emulator_state_and_discards_pending_input(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from pokesim.emulator import Emulator
    from pokesim.store import Store
    partner = mon(trainer_id=100, dvs=(8,) * 5)
    s = snapshot([], party=(partner,))
    emu = Emulator.__new__(Emulator)
    emu.store = Store(tmp_path)
    emu.pb = Mock()
    emu.frame = 100
    emu.input_epoch = 7
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: s)
    key = identity(asdict(partner))
    emu._set_trade_preference(key, 'locked')
    assert emu.store.trade_preferences()[key]['state'] == 'locked'
    assert emu.input_epoch == 8
    assert emu.snapshot == s
    emu.store.close()
