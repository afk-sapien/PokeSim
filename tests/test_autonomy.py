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
    policy.progress_goal = 'blocked'
    policy.progress_frame = 0
    s = snap(frame=3000, party=(mon(),))
    action = policy._overworld(s, bytearray(65536))[0]
    assert action.button in ('a', 'up', 'down', 'left', 'right')
    assert policy.mode == 'finding another approach'
    assert policy.recoveries == 1 and policy.recovery_until > s.frame
    assert not getattr(policy, 'needs_help', None)


def test_hm_goal_starts_using_item_on_a_compatible_partner():
    policy = StrategicPolicy(7)
    s = snap(party=(mon(),), badges=3, items=((ITEMS['HM01'], 1),),
             event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_CERULEAN_ROCKET_THIEF'))
    policy.goal = story_goal(s)
    assert policy.goal.key == 'teach_cut'
    assert policy._overworld(s, bytearray(65536))[0].button == 'start'
    assert policy.intent.kind == 'item' and policy.intent.index == 0 and policy.intent.target == 0


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


def test_pending_field_action_survives_pause_menu_opening():
    from pokesim.policies.battle import Decision
    from pokesim.screen import Screen
    from test_screen import fake_mem
    policy = StrategicPolicy(7)
    policy.intent = Decision('field', 0, reason='Use Cut')
    policy.intent_since = 100
    memory = fake_mem({})
    s = snap(frame=118, party=(mon(),))
    action = policy._dispatch(s, Screen(memory), 'overworld', memory)[0]
    assert action.button is None
    assert policy.intent.kind == 'field'


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
    policy.pc_operation = 'deposit'
    assert policy._pc_target(s) == 1
    policy.pc_operation = 'withdraw'
    assert policy._pc_target(replace(s, party=party[:5])) == 0
