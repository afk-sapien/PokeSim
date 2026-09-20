"""The last partner standing fights on instead of trying to switch to itself."""
from pokesim.policies.battle import Decision
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen, W_PLAYER_MON_NUMBER
from test_events import snap
from test_strategy import menu, mon


def party_menu(active):
    memory = menu({1: ' BULBASAUR', 3: ' BEEDRILL', 5: ' YELLMAN'}, (0, 1), top=(0, 1))
    memory[W_PLAYER_MON_NUMBER] = active
    return memory


def test_party_menu_closes_when_nobody_else_can_battle():
    # The game answers "YELLMAN is already out!" and reopens the menu, which repeated for six game hours.
    policy = StrategicPolicy(7)
    state = snap(party=(mon(hp=0), mon(hp=0), mon(hp=11, nick='YELLMAN')), in_battle=2)
    memory = party_menu(2)
    assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'b'
    assert policy.intent is None


def test_a_switch_aimed_at_a_fainted_or_active_partner_is_dropped():
    state = snap(party=(mon(hp=0), mon(hp=0), mon(hp=11)), in_battle=2)
    for index in (0, 2):
        policy = StrategicPolicy(7)
        policy.intent = Decision('switch', index)
        memory = party_menu(2)
        assert policy._dispatch(state, Screen(memory), 'party', memory)[0].button == 'b'
        assert policy.intent is None


def test_a_healthy_reserve_is_still_chosen():
    policy = StrategicPolicy(7)
    state = snap(party=(mon(hp=0), mon(hp=30), mon(hp=11)), in_battle=2)
    memory = party_menu(0)
    policy._dispatch(state, Screen(memory), 'party', memory)
    assert policy.intent.kind == 'switch' and policy.intent.index == 1
