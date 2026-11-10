import pytest

from pokecore.state_actions import open_menu, select_visible_option, wait_until
from test_state_actions import fixture


@pytest.mark.parametrize('accepted,advanced,expected', [
    (False, 0, 'consumer_budget'), (False, 3, 'consumer_budget'),
    (True, 0, 'stalled'), (True, 3, 'interrupted'),
])
def test_partial_confirmation_never_retries(accepted, advanced, expected):
    state, port = fixture('menu')
    def send(button, hold, gap):
        state.inputs.append(button)
        state.frame += advanced
        return accepted
    port.send = send
    result = select_visible_option(port, 'ITEM', verify=lambda _: False, max_frames=100)
    assert result['status'] == expected
    assert result['confirmed']
    assert not result['completed']
    assert result['frames'] == advanced
    assert state.inputs == ['a']


def test_wait_stops_when_consumer_stops_during_action():
    state, port = fixture('transition')
    port.stopped = lambda: state.frame >= 4
    result = wait_until(port, lambda _: False, max_frames=100)
    assert result['status'] == 'stopped'
    assert result['frames'] == 4
    assert state.inputs == [(None, 4, 0)]


def test_selection_rejects_stale_cursor_text_without_confirmation():
    state, port = fixture('menu')
    observe = port.observe
    port.observe = lambda: dict(observe(), selected_text='CANCEL')
    result = select_visible_option(port, 'ITEM', verify=lambda _: True, max_frames=100)
    assert result['status'] == 'unexpected_state'
    assert not result['confirmed']
    assert state.inputs == []


def test_open_menu_waits_for_overworld_and_presses_start_only_once():
    state, port = fixture('transition')
    def send(button, hold, gap):
        state.inputs.append(button)
        state.frame += hold + gap
        if state.frame == 4:
            state.kind = 'overworld'
        elif button == 'start':
            state.kind = 'transition'
        elif state.frame >= 44:
            state.kind = 'menu'
        return True
    port.send = send
    result = open_menu(port, max_frames=44)
    assert result['completed']
    assert result['frames'] == 44
    assert state.inputs == [None, 'start', None, None]


@pytest.mark.parametrize('invalid', [-1, True, 1.5])
@pytest.mark.parametrize('action', ['wait', 'open', 'select'])
def test_invalid_frame_budgets_never_send_inputs(invalid, action):
    state, port = fixture('menu')
    with pytest.raises(ValueError):
        if action == 'wait':
            wait_until(port, lambda _: False, max_frames=invalid)
        elif action == 'open':
            open_menu(port, max_frames=invalid)
        else:
            select_visible_option(port, 'ITEM', verify=lambda _: False, max_frames=invalid)
    assert state.inputs == []
    assert state.frame == 0


def test_wait_rejects_consumer_time_moving_backwards():
    state, port = fixture()
    state.frame = 10
    def send(*args):
        state.frame -= 1
        return True
    port.send = send
    with pytest.raises(RuntimeError, match='backwards'):
        wait_until(port, lambda _: False, max_frames=10)
