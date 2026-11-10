from types import SimpleNamespace

import pytest

from pokecore.controls import ControllerPort
from pokecore.state_actions import open_menu, select_visible_option, wait_until


def fixture(kind='overworld'):
    state = SimpleNamespace(frame=0, kind=kind, index=0, inputs=[], confirmations=0)
    rows = [{'text': 'ITEM', 'cursor': [0, 0]}, {'text': 'POKéMON', 'cursor': [0, 2]}]
    def observe():
        return {'kind': state.kind, 'cursor_tile': rows[state.index]['cursor'],
                'selected_text': rows[state.index]['text']}
    def send(button, hold, gap):
        state.inputs.append((button, hold, gap))
        state.frame += hold + gap
        if button == 'start':
            state.kind = 'menu'
        if button == 'down':
            state.index = 1
        if button == 'a':
            state.confirmations += 1
            state.kind = 'party'
        return True
    port = ControllerPort(bytearray(65536), send, lambda _: pytest.fail('Unbudgeted choose used'),
                          observe, lambda: state.frame, menu_rows=lambda: rows)
    return state, port


def test_open_and_select_observe_effect_and_count_frames():
    state, port = fixture()
    assert open_menu(port, max_frames=32)['status'] == 'success'
    result = select_visible_option(port, 'pokemon', max_frames=64, verify=lambda ui: ui['kind'] == 'party')
    assert result['status'] == 'success'
    assert result['frames'] == 64
    assert result['confirmed']
    assert [x[0] for x in state.inputs] == ['start', 'down', 'a']


def test_zero_and_short_budgets_never_send_confirmation():
    state, port = fixture('menu')
    result = select_visible_option(port, 'ITEM', max_frames=31, verify=lambda _: False)
    assert result['status'] == 'timeout'
    assert not result['confirmed']
    assert state.inputs == []
    assert wait_until(port, lambda _: False, max_frames=0)['frames'] == 0


def test_confirmation_is_not_retried_when_effect_is_unverified():
    state, port = fixture('menu')
    result = select_visible_option(port, 'ITEM', max_frames=51, verify=lambda _: False)
    assert result['status'] == 'timeout'
    assert result['frames'] == 51
    assert result['confirmed']
    assert state.confirmations == 1


def test_unexpected_state_duplicate_label_and_disappearing_target():
    state, port = fixture('dialogue')
    assert select_visible_option(port, 'ITEM', max_frames=100, verify=lambda _: False)['status'] == 'unexpected_state'
    state.kind = 'menu'
    port.menu_rows = lambda: [{'text': 'ITEM', 'cursor': [0, 0]}, {'text': 'ITEM', 'cursor': [0, 2]}]
    assert select_visible_option(port, 'ITEM', max_frames=100, verify=lambda _: False)['status'] == 'unexpected_state'
    assert state.inputs == []
    state, port = fixture('menu')
    original = port.send
    def send(*args):
        original(*args)
        state.kind = 'battle'
        return True
    port.send = send
    assert select_visible_option(port, 'POKEMON', max_frames=100, verify=lambda _: False)['status'] == 'unexpected_state'
    assert state.confirmations == 0


def test_transition_wait_success_at_exact_budget_and_detached_observation():
    state, port = fixture('transition')
    original = port.send
    def send(*args):
        original(*args)
        if state.frame >= 9:
            state.kind = 'menu'
        return True
    port.send = send
    result = wait_until(port, lambda ui: ui['kind'] == 'menu', max_frames=9, poll_frames=4)
    assert result['completed'] and result['frames'] == 9
    result['observation']['cursor_tile'][0] = 100
    assert port.observe()['cursor_tile'] == [0, 0]


def test_bad_consumers_cannot_spin_or_silently_exceed_budget():
    state, port = fixture()
    port.send = lambda *args: True
    assert wait_until(port, lambda _: False, max_frames=10)['status'] == 'stalled'
    port.send = lambda *args: False
    assert wait_until(port, lambda _: False, max_frames=10)['status'] == 'consumer_budget'
    port.stopped = lambda: True
    assert open_menu(port, max_frames=40)['status'] == 'stopped'
    port.stopped = lambda: False
    def overrun(*args):
        state.frame += 100
        return True
    port.send = overrun
    with pytest.raises(RuntimeError, match='budget'):
        wait_until(port, lambda _: False, max_frames=10)


def test_horizontal_selection_and_no_duplicate_open():
    state, port = fixture('menu')
    assert open_menu(port, max_frames=10)['frames'] == 0
    rows = [{'text': 'ITEM', 'cursor': [0, 0]}, {'text': 'POKéMON', 'cursor': [8, 0]}]
    port.menu_rows = lambda: rows
    port.observe = lambda: {'kind': state.kind, 'cursor_tile': rows[state.index]['cursor'],
                           'selected_text': rows[state.index]['text']}
    original = port.send
    def send(button, hold, gap):
        if button == 'right':
            state.index = 1
        return original(button, hold, gap)
    port.send = send
    result = select_visible_option(port, 'POKEMON', max_frames=64, verify=lambda ui: ui['kind'] == 'party')
    assert result['completed']
    assert state.inputs[0][0] == 'right'
