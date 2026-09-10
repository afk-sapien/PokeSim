from pokesim.policies.battle import (Decision, W_BATTLE_MON, W_ENEMY_MON,
                                     W_PLAYER_DISABLED_MOVE, choose_battle, read_battler)
from pokesim.policies.strategic import StrategicPolicy
from pokesim.screen import Screen
from test_events import snap
from test_strategy import menu, mon


def battler(memory, base, pokemon):
    memory[base] = pokemon.species
    memory[base + 4] = pokemon.status
    memory[base + 5:base + 7] = bytes(pokemon.types)
    memory[base + 8:base + 12] = bytes(pokemon.moves)
    memory[base + 14] = pokemon.level
    for offset, value in ((1, pokemon.hp), (15, pokemon.max_hp), (17, pokemon.attack),
                          (19, pokemon.defense), (21, pokemon.speed), (23, pokemon.special)):
        memory[base + offset:base + offset + 2] = value.to_bytes(2, 'big')
    memory[base + 25:base + 29] = bytes(pokemon.pp)


def battle(memory):
    me = mon(moves=(33, 45, 73, 22), pp=(25, 40, 9, 10))
    enemy = mon(species=92, types=(21, 21), moves=(33, 0, 0, 0), pp=(35, 0, 0, 0))
    battler(memory, W_BATTLE_MON, me)
    battler(memory, W_ENEMY_MON, enemy)
    memory[W_PLAYER_DISABLED_MOVE] = 0x43
    return snap(party=(me,), in_battle=2, enemy_species=92, enemy_level=15)


def test_disabled_slot_is_unavailable_only_while_disable_is_active():
    memory = bytearray(65536)
    state = battle(memory)
    player = read_battler(memory, W_BATTLE_MON)
    enemy = read_battler(memory, W_ENEMY_MON)
    assert player.pp == (25, 40, 9, 0)
    assert memory[W_BATTLE_MON + 28] == 10
    assert enemy.pp == (35, 0, 0, 0)
    assert choose_battle(state, player, enemy, 0).index == 0
    memory[W_PLAYER_DISABLED_MOVE] = 0
    player = read_battler(memory, W_BATTLE_MON)
    assert player.pp[3] == 10
    assert choose_battle(state, player, enemy, 0).index == 3


def test_move_menu_exits_the_disabled_choice_instead_of_retrying_it():
    policy = StrategicPolicy(1)
    policy.intent = Decision('fight', 3)
    buttons = []
    for index in (4, 3, 2, 1):
        memory = menu({13: '      TACKLE', 14: '      GROWL', 15: '      LEECH SEED',
                       16: '      VINE WHIP'}, (5, 12 + index), index, (5, 12))
        state = battle(memory)
        buttons.append(policy._dispatch(state, Screen(memory), 'moves', memory)[0].button)
    assert buttons == ['up', 'up', 'up', 'a']


def test_battle_root_discards_stale_disabled_move_intent():
    memory = menu({14: '          FIGHT PKMN', 16: '          ITEM  RUN'}, (9, 14))
    state = battle(memory)
    policy = StrategicPolicy(1)
    policy.intent = Decision('fight', 3)
    policy.last_kind = 'battle'
    policy._dispatch(state, Screen(memory), 'battle', memory)
    assert policy.intent.kind == 'fight' and policy.intent.index == 0


def test_no_available_moves_returns_to_fight_for_struggle():
    memory = menu({13: '      VINE WHIP'}, (5, 13), 1, (5, 12))
    state = battle(memory)
    memory[W_BATTLE_MON + 25:W_BATTLE_MON + 29] = bytes((0, 0, 0, 10))
    policy = StrategicPolicy(1)
    assert policy._dispatch(state, Screen(memory), 'moves', memory)[0].button == 'b'
    player = read_battler(memory, W_BATTLE_MON)
    enemy = read_battler(memory, W_ENEMY_MON)
    decision = choose_battle(state, player, enemy, 0)
    assert decision.kind == 'fight'
