from dataclasses import replace

from pokesim.policies.battle import Decision
from pokesim.policies.navigation import Navigator
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from pokesim.strategy_data import MAPS
from test_events import snap
from test_screen import fake_mem
from test_strategy import mon


def test_seafoam_raised_ledge_is_not_a_surf_entry_even_with_an_old_edge():
    nav = Navigator()
    nav.can_surf = True
    source = (MAPS['SEAFOAM_ISLANDS_B3F'], 14, 12)
    water = (source[0], 14, 11)
    assert ('up', water) not in list(nav.neighbors(source, 0))
    nav.edges[source] = {'up': water}
    assert ('up', water) not in list(nav.neighbors(source, 0))
    assert nav.route(source, [water], 0) in ('left', 'right', 'down')


def test_rejected_surf_exits_party_menu_instead_of_repeating_the_move():
    policy = StrategicPolicy(7)
    policy.intent = Decision('field', 0)
    policy.field_move = 'SURF'
    state = snap(party=(mon(moves=(57, 0, 0, 0)),), textbox=True)
    memory = fake_mem({14: 'No SURFing on', 16: 'MUFFIN here'})
    action = policy._dispatch(state, Screen(memory), 'dialogue', memory)[0]
    assert action.button == 'b' and policy.intent is None
    memory = fake_mem({14: 'Choose a POKEMON'})
    assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'b'


def test_pending_surf_still_selects_its_partner_and_battle_replacement_still_works():
    policy = StrategicPolicy(7)
    state = snap(party=(mon(hp=0), mon(moves=(57, 0, 0, 0))),)
    memory = fake_mem({14: 'Choose a POKEMON'})
    policy.intent = Decision('field', 1)
    assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'down'
    policy.intent = None
    policy._dispatch(replace(state, in_battle=2), Screen(memory), 'party', memory)
    assert policy.intent.kind == 'switch' and policy.intent.index == 1
