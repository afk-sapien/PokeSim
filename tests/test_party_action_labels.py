"""Field moves and reorders run as Core shortcuts, so the party action menu is only a fallback."""
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from shortcut_fakes import Recorder
from test_events import snap
from test_strategy import menu, mon


def action_menu():
    return menu({10: '             STATS', 12: '             SWITCH', 14: '             CANCEL'},
                (12, 10), top=(12, 10))


def test_party_action_menu_closes_outside_battle_and_switches_inside():
    policy = StrategicPolicy(0)
    memory = action_menu()
    assert policy._dispatch(snap(party=(mon(),)), Screen(memory), 'party_action', memory)[0].button == 'b'
    assert policy._dispatch(snap(party=(mon(),), in_battle=1), Screen(memory), 'party_action', memory)[0].button == 'a'


def test_field_move_names_the_move_and_partner():
    policy = StrategicPolicy(0)
    shortcuts = Recorder.on(policy)
    assert policy._field(snap(party=(mon(), mon(moves=(15, 0, 0, 0)))), 'CUT', 1, 'Use Cut')
    assert (shortcuts.last.kind, shortcuts.last.move, shortcuts.last.slot) == ('use_field_move', 'CUT', 1)


def test_reorder_moves_the_partner_to_the_lead():
    policy = StrategicPolicy(0)
    shortcuts = Recorder.on(policy)
    assert policy._reorder(snap(party=(mon(), mon(level=9), mon(level=30))), 2, 'Lead')
    assert (shortcuts.last.first, shortcuts.last.second) == (2, 0)
