from types import SimpleNamespace

import pytest

from pokecore.capabilities import capabilities, capability
from pokecore.controls import ControllerPort
from pokecore.dialogue import Transcript, collect_dialogue
from pokecore.movement import walk_tiles


def controller(kind='overworld'):
    state = SimpleNamespace(frame=0, kind=kind, stopped=False, calls=[], on_send=None)
    memory = bytearray(65536)
    memory[0xD362] = 5
    memory[0xD361] = 5
    def send(button, hold, release):
        state.calls.append((button, hold, release))
        state.frame += hold + release
        if state.on_send:
            state.on_send(button)
        return not state.stopped
    port = ControllerPort(memory, send, lambda _: pytest.fail('Unexpected menu choice'),
                          lambda: {'kind': state.kind}, lambda: state.frame,
                          stopped=lambda: state.stopped, continue_ready=lambda: True, version='red')
    return state, port


def transcript(state):
    return Transcript(observe=lambda _: {'kind': state.kind},
                      screen_reader=lambda _: {'textbox': False, 'tiles': []})


def test_walk_turns_once_then_moves_requested_tiles():
    state, port = controller()
    def step(button):
        if button == 'right':
            if port.memory[0xC109] != 12:
                port.memory[0xC109] = 12
            else:
                port.memory[0xD362] += 1
    state.on_send = step
    result = walk_tiles(port, 'right', 3, max_frames=200)
    assert port.memory[0xD362] == 8
    assert result['tiles_moved'] == 3
    assert result['control']['completed'] and result['control']['settled']
    assert state.frame == 96
    assert [c[0] for c in state.calls] == ['right'] * 4


def test_walk_stops_at_warp_without_using_new_coordinates_as_distance():
    state, port = controller()
    def warp(button):
        port.memory[0xD35E] = 7
        port.memory[0xD362] = 200
    state.on_send = warp
    result = walk_tiles(port, 'up', 8, max_frames=500)
    assert result['control']['stop_reason'] == 'map_changed'
    assert result['tiles_moved'] == 0
    assert len(state.calls) == 1


def test_walk_stops_on_obstacle_battle_and_input_lock():
    state, port = controller()
    blocked = walk_tiles(port, 'up', 8, max_frames=500)
    assert blocked['control']['stop_reason'] == 'blocked'
    assert len(state.calls) == 1
    state.calls.clear()
    state.kind = 'battle_menu'
    assert walk_tiles(port, 'up', 8, max_frames=500)['control']['stop_reason'] == 'choice'
    assert not state.calls
    state.kind = 'overworld'
    assert walk_tiles(port, 'up', 8, max_frames=500, input_locked=lambda: True)['control']['stop_reason'] == 'input_locked'
    assert not state.calls


def test_walk_local_and_consumer_budgets_are_observed():
    state, port = controller()
    assert walk_tiles(port, 'up', 8, max_frames=23)['control']['stop_reason'] == 'budget'
    assert not state.calls
    def stop(button):
        port.memory[0xD361] -= 1
        state.stopped = True
    state.on_send = stop
    result = walk_tiles(port, 'up', 8, max_frames=200)
    assert result['tiles_moved'] == 1
    assert result['control']['stop_reason'] == 'stopped'
    assert len(state.calls) == 1


@pytest.mark.parametrize('direction,count', [('north', 1), ('up', 0), ('up', 9), ('up', True)])
def test_invalid_walk_never_sends_input(direction, count):
    state, port = controller()
    with pytest.raises(ValueError):
        walk_tiles(port, direction, count, max_frames=500)
    assert not state.calls


def test_dialogue_confirms_only_continue_and_returns_choice():
    state, port = controller('dialogue')
    state.on_send = lambda button: setattr(state, 'kind', 'menu') if button == 'a' else None
    result = collect_dialogue(port, max_frames=300, transcript=transcript(state))
    assert result['control']['stop_reason'] == 'choice'
    assert result['control']['settled']
    assert [c for c in state.calls if c[0]] == [('a', 1, 1)]
    state.calls.clear()
    collect_dialogue(port, max_frames=300, transcript=transcript(state))
    assert not state.calls


def test_dialogue_unknown_readiness_only_waits_and_is_bounded():
    state, port = controller('dialogue')
    port.continue_ready = lambda: False
    result = collect_dialogue(port, max_frames=90, transcript=transcript(state))
    assert result['control']['stop_reason'] == 'budget'
    assert result['frames'] == state.frame == 90
    assert all(button is None for button, _, _ in state.calls)
    assert not result['control']['settled']


def test_dialogue_cancellation_and_choice_never_send_input():
    state, port = controller('dialogue')
    state.stopped = True
    result = collect_dialogue(port, max_frames=100, transcript=transcript(state))
    assert result['control']['stop_reason'] == 'stopped'
    assert not state.calls
    state.stopped = False
    state.kind = 'naming'
    assert collect_dialogue(port, max_frames=100, transcript=transcript(state))['stop_reason'] == 'choice'
    assert not state.calls


def test_capabilities_are_detached_and_generation_specific():
    first = capabilities('red')
    first['walk_tiles']['arguments']['direction']['enum'].clear()
    assert capability('walk_tiles')['arguments']['direction']['enum'] == ['up', 'down', 'left', 'right']
    assert 'walk_tiles' not in capabilities('gold')
    with pytest.raises(ValueError):
        capability('walk_tiles', 'gold')
    state, port = controller()
    port.version = 'gold'
    with pytest.raises(ValueError):
        walk_tiles(port, 'up', 1, max_frames=50)
    with pytest.raises(ValueError):
        collect_dialogue(port, max_frames=50)
    assert not state.calls
