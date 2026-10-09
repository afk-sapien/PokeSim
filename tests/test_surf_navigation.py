from dataclasses import replace

from pokesim.policies.battle import Decision
from pokesim.policies.navigation import Navigator
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from pokesim.strategy_data import MAPS
from test_events import snap
from test_screen import fake_mem
from test_strategy import mon
from shortcut_fakes import Recorder


def test_seafoam_raised_ledge_is_not_a_surf_entry_even_with_an_old_edge():
    nav = Navigator()
    nav.can_surf = True
    source = (MAPS['SEAFOAM_ISLANDS_B3F'], 14, 12)
    water = (source[0], 14, 11)
    assert ('up', water) not in list(nav.neighbors(source, 0))
    nav.edges[source] = {'up': water}
    assert ('up', water) not in list(nav.neighbors(source, 0))
    assert nav.route(source, [water], 0) in ('left', 'right', 'down')


def test_rejected_surf_blocks_that_shoreline_instead_of_repeating_the_move():
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    state = snap(party=(mon(moves=(57, 0, 0, 0)),), x=4, y=5)
    assert policy._field(state, 'SURF', 0, 'Use Surf', 'up', 'Surf was rejected')
    assert (shortcuts.last.move, shortcuts.last.slot) == ('SURF', 0)
    shortcuts.finish(False, frame=state.frame)
    assert ((state.map, 4, 5), 'up') in policy.nav.blocked
    assert policy.reason == 'Surf was rejected'
    assert policy._field(state, 'SURF', 0, 'Use Surf', 'up') is None


def test_forced_battle_replacement_switches_to_a_healthy_partner():
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    state = snap(party=(mon(hp=0), mon(moves=(57, 0, 0, 0))), in_battle=2)
    memory = fake_mem({14: 'Choose a POKEMON'})
    assert policy._dispatch(state, Screen(memory), 'party', memory)
    assert (shortcuts.last.kind, shortcuts.last.slot) == ('switch_pokemon', 1)
