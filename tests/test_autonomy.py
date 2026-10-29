import queue
from dataclasses import replace
from unittest.mock import Mock

from pokesim.emulator import Emulator
from pokesim.policies.base import Action, PolicyContext
from pokesim.policies.progression import Goal, story_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_strategy import flags, mon
from shortcut_fakes import PRESS, Recorder


def test_policy_help_signal_cannot_take_over_the_emulator(monkeypatch):
    emu = Emulator.__new__(Emulator)
    emu.input_epoch = 0
    emu.commands = queue.Queue()
    emu.manual = queue.Queue()
    emu.paused = emu.manual_mode = False
    emu.frame = 0
    emu.stuck_since = 0
    emu.policy = Mock()
    emu.policy.needs_help = 'Legacy request that must not pause the simulator'
    emu.policy.step.return_value = [Action('right', 8, 2)]
    emu.pb = Mock()
    emu._autosave = Mock()
    emu._check_guards = Mock()
    ticks = []
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda *_: snap())
    def tick(frames):
        ticks.append(frames)
        if len(ticks) == 4:
            emu.commands.put(('stop', None))
    emu._tick = tick
    emu._run()
    assert not emu.paused and not emu.manual_mode
    assert emu.policy.step.call_count == 2
    emu.policy.on_restore.assert_not_called()
    assert ticks == [8, 2, 8, 2]


def test_stalled_goal_recovers_without_waiting_for_a_person():
    policy = StrategicPolicy(7)
    policy.goal = Goal('blocked', 'Cross the obstacle', 'Explore', ((255, 1, 1),))
    policy.progress_goal, policy.progress_targets = 'blocked', frozenset(policy.goal.targets)
    policy.progress_frame = 0
    s = snap(frame=3000, party=(mon(),))
    action = policy._overworld(s, bytearray(65536))[0]
    assert action.button in ('a', 'up', 'down', 'left', 'right')
    assert policy.mode == 'finding another approach'
    assert policy.recoveries == 1 and policy.recovery_until > s.frame
    assert not getattr(policy, 'needs_help', None)


def test_new_targets_under_the_same_goal_key_restart_the_stall_timer():
    policy = StrategicPolicy(7)
    first = Goal('collect_hunt', 'Hunt', 'Find grass', ((255, 1, 1), (255, 2, 1)))
    moved = Goal('collect_hunt', 'Hunt', 'Find grass', ((255, 9, 9), (255, 9, 8)))
    policy.collection.choose = lambda *_: goals.pop(0)
    goals = [first, first, moved]
    policy._overworld(snap(frame=0, party=(mon(),)), bytearray(65536))
    assert policy.progress_frame == 0
    # Same key and targets: the timer keeps running.
    policy._overworld(snap(frame=600, party=(mon(),)), bytearray(65536))
    assert policy.progress_frame == 0
    # Same key, new targets, past the stall limit: a fresh leg starts instead of a recovery.
    policy._overworld(snap(frame=3000, party=(mon(),)), bytearray(65536))
    assert policy.progress_frame == 3000 and policy.recoveries == 0
    assert policy.progress_targets == frozenset(moved.targets)


def test_hm_goal_starts_using_item_on_a_compatible_partner():
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    s = snap(party=(mon(),), badges=3, items=((ITEMS['HM01'], 1),),
             event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_CERULEAN_ROCKET_THIEF'))
    policy.goal = story_goal(s)
    assert policy.goal.key == 'teach_cut'
    assert policy._overworld(s, bytearray(65536))[0] == PRESS
    assert (shortcuts.last.kind, shortcuts.last.item, shortcuts.last.target) == ('use_item', ITEMS['HM01'], 0)


def test_battles_refresh_navigation_stall_timer():
    policy = StrategicPolicy(7)
    policy.progress_frame = 0
    policy.observed_map = 1
    s = snap(frame=6000, in_battle=1, party=(mon(),))
    policy.step(PolicyContext(s, 100, 100, bytearray(65536)))
    assert policy.progress_frame == 6000


def test_hm_dialogue_advances_despite_bag_quantity_behind_it():
    from pokesim.policies.battle import Decision
    from pokesim.screen import Screen, W_TILEMAP
    from test_screen import fake_mem
    memory = fake_mem({2: 'HM01', 14: 'Booted up an HM'})
    memory[W_TILEMAP + 2 * 20 + 15:W_TILEMAP + 2 * 20 + 18] = bytes([0xF1, 0xF6, 0xF7])
    s = snap(party=(mon(),), textbox=True)
    screen = Screen(memory)
    assert screen.kind(s) == 'dialogue'
    policy = StrategicPolicy(7)
    policy.intent = Decision('item', 0)
    assert policy._dispatch(s, screen, 'dialogue', memory)[0].button == 'a'


def test_active_shortcut_keeps_control_until_it_is_done():
    from pokecore.shortcuts import Done

    class Machine:
        kind, inputs = 'use_field_move', 1

        def __init__(self):
            self.results = ['start', None, Done('Used CUT.', True)]

        def step(self, memory, ui):
            return self.results.pop(0)

    policy = StrategicPolicy(7)
    memory = bytearray(65536)
    policy.mem = memory
    s = snap(frame=118, party=(mon(),))
    assert policy.shortcut.start(Machine(), 'cut', s.frame, memory)[0].button == 'start'
    assert policy.step(PolicyContext(s, 0, 0, memory))[0].button is None
    assert policy.mode == 'shortcut: use_field_move'
    policy.step(PolicyContext(s, 0, 0, memory))
    assert not policy.shortcut.active and policy.shortcut.last.completed


def test_battle_turn_after_the_game_takes_the_decision_is_not_a_recovery():
    from pokecore.shortcuts import Done
    from pokesim.policies.battle import Decision
    from shortcut_fakes import Scripted

    policy = StrategicPolicy(7)
    memory = bytearray(65536)
    policy.mem = memory
    policy.intent, policy.intent_since = Decision('fight', 0), 0
    policy.observed_map = snap().map
    policy.shortcut.start(Scripted('choose_move', ['a', Done('Chose the move.', True)]), 'move', 0, memory)
    policy.step(PolicyContext(snap(frame=118, in_battle=1, party=(mon(),)), 0, 0, memory))
    assert not policy.shortcut.active and policy.intent_since is None
    # A knockout, a forced switch and a level up can keep the turn going well past the pending limit.
    policy.step(PolicyContext(snap(frame=1500, in_battle=1, party=(mon(),), textbox=True), 0, 0, memory))
    assert policy.recoveries == 0


def test_battle_decision_the_game_never_took_is_still_recovered():
    from pokesim.policies.battle import Decision

    policy = StrategicPolicy(7)
    memory = bytearray(65536)
    policy.intent, policy.intent_since = Decision('fight', 0), 0
    s = snap(frame=1000, in_battle=1, party=(mon(),), textbox=True)
    policy.observed_map = s.map
    policy.step(PolicyContext(s, 0, 0, memory))
    assert policy.recoveries == 1 and policy.intent is None


def test_move_replacement_recovers_after_trying_to_delete_an_hm():
    from pokesim.screen import Screen
    from test_strategy import menu
    memory = menu({8: '      CUT', 9: '      GROWL', 10: '      LEECH SEED',
                   11: '      VINE WHIP', 14: 'HM techniques', 16: 'cannot be deleted!'}, (5, 8))
    assert Screen(memory).kind(snap(party=(mon(),), in_battle=1, textbox=True)) == 'learn_move'


def test_surf_partner_uses_storage_without_releasing_pokemon():
    from pokesim.policies.progression import teaching_goal
    from pokesim.strategy_data import MAPS
    party = (mon(level=50, moves=(15, 22, 33, 45)),) + tuple(mon(level=5) for _ in range(5))
    s = snap(party=party, boxed_pokemon=((132, 30),), map=MAPS['FUCHSIA_POKECENTER'])
    goal = teaching_goal('teach_surf', 'Teach Surf', 'Cross water', s)
    assert goal.key == 'party_surf'
    assert (s.map, 13, 4) in goal.targets
    policy = StrategicPolicy(7)
    policy.goal = goal
    policy.pc.operation = 'deposit'
    assert policy._pc_target(s) == 1
    policy.pc.operation = 'withdraw'
    assert policy._pc_target(replace(s, party=party[:5])) == 0
