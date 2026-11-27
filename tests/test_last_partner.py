"""The last partner standing fights on instead of trying to switch to itself."""
from pokesim.policies.battle import W_ENEMY_MON, Decision
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen, W_PLAYER_MON_NUMBER
from test_events import snap
from test_strategy import menu, mon
from shortcut_fakes import Recorder


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


def test_a_fainted_battler_is_replaced_by_a_partner_that_can_hurt_the_foe():
    # Against Agatha's Gengar the replacement went by HP alone, so Kangaskhan's Normal moves came in.
    policy = StrategicPolicy(7)
    recorder = Recorder.on(policy)
    tackle, night_shade = 33, 101
    kangaskhan = mon(hp=200, max_hp=200, types=(0, 0), moves=(tackle, 0, 0, 0), pp=(35, 0, 0, 0))
    haunter = mon(hp=40, types=(8, 3), moves=(night_shade, 0, 0, 0), pp=(15, 0, 0, 0))
    state = snap(party=(mon(hp=0), kangaskhan, haunter), in_battle=2)
    memory = party_menu(0)
    memory[W_ENEMY_MON + 2], memory[W_ENEMY_MON + 5], memory[W_ENEMY_MON + 6] = 129, 8, 3
    policy._dispatch(state, Screen(memory), 'party', memory)
    assert recorder.last.kind == 'switch_pokemon' and recorder.last.slot == 2


def test_a_healthy_reserve_is_still_chosen():
    policy = StrategicPolicy(7)
    recorder = Recorder.on(policy)
    state = snap(party=(mon(hp=0), mon(hp=30), mon(hp=11)), in_battle=2)
    memory = party_menu(0)
    policy._dispatch(state, Screen(memory), 'party', memory)
    assert recorder.last.kind == 'switch_pokemon' and recorder.last.slot == 1
