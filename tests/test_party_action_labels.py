"""Party action selection reads menu labels without matching nicknames behind them."""
import pytest

from pokesim.policies.battle import Decision
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from test_events import snap
from test_strategy import menu, mon


def action_screen(label, cursor_row=10):
    nickname = 'GRIMBISCUT' if label == 'CUT' else label
    column = min(12, 18 - len(label))
    padding = ' ' * (column + 1)
    return menu({0: '   ' + nickname, 10: padding + label,
                 12: padding + 'STATS', 14: padding + 'SWITCH',
                 16: padding + 'CANCEL'}, (column, cursor_row), top=(column, 10))


@pytest.mark.parametrize('move', ['CUT', 'SURF', 'FLY', 'STRENGTH'])
def test_field_move_ignores_matching_text_in_a_nickname(move):
    policy = StrategicPolicy(0)
    policy.field_move = move
    policy.intent = Decision('field', 0)
    memory = action_screen(move)
    state = snap(party=(mon(),))
    assert policy._dispatch(state, Screen(memory), 'party_action', memory)[0].button == 'a'


def test_field_move_moves_toward_the_menu_option_not_the_nickname():
    policy = StrategicPolicy(0)
    policy.field_move = 'CUT'
    policy.intent = Decision('field', 0)
    memory = action_screen('CUT', cursor_row=8)
    assert policy._dispatch(snap(party=(mon(),)), Screen(memory), 'party_action', memory)[0].button == 'down'


def test_missing_field_option_does_not_select_a_nickname_or_partial_label():
    policy = StrategicPolicy(0)
    policy.field_move = 'CUT'
    policy.intent = Decision('field', 0)
    memory = action_screen('CUTTER')
    assert policy._dispatch(snap(party=(mon(),)), Screen(memory), 'party_action', memory)[0].button == 'b'
    assert policy.intent is None


def test_reorder_matches_switch_in_the_menu_only():
    policy = StrategicPolicy(0)
    policy.intent = Decision('reorder', 0)
    # A nickname contains SWITCH, while the first menu option is STATS.
    memory = menu({0: '   SWITCH', 10: '             STATS',
                   14: '             SWITCH', 16: '             CANCEL'},
                  (12, 14), top=(12, 10))
    assert policy._dispatch(snap(party=(mon(),)), Screen(memory), 'party_action', memory)[0].button == 'a'
    assert policy.order_stage == 'destination'
