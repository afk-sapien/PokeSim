import json

import pytest

from pokesim.policies import POLICIES, make_policy
from pokesim.policies.base import PolicyContext
from pokesim.policies.naming import NamingController, POKEMON_NAMES, TRAINER_NAMES
from pokesim.screen import Screen, W_CURRENT_MENU_ITEM, W_TILEMAP
from test_events import snap
from test_screen import fake_mem


def grid(header="YOUR NAME", entered="", cursor=(1, 5), lowercase=False):
    alphabet = "abcdefghijklmnopqrstuvwxyz" if lowercase else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    mem = fake_mem({1: header, 2: "          " + entered,
                    5: "  " + " ".join(alphabet[:9]),
                    7: "  " + " ".join(alphabet[9:18]),
                    9: "  " + " ".join(alphabet[18:])})
    x, y = cursor
    mem[W_TILEMAP + y * 20 + x] = 0xED
    return mem


def test_names_fit_game_limits_and_supported_alphabet():
    for pool, limit in ((TRAINER_NAMES, 7), (POKEMON_NAMES, 10)):
        assert len(set(pool)) == len(pool)
        assert all(1 <= len(name) <= limit and all("A" <= c <= "Z" for c in name) for name in pool)


@pytest.mark.parametrize("x", range(1, 18, 2))
@pytest.mark.parametrize("lowercase", (False, True))
def test_grid_detection_survives_cursor_across_first_row(x, lowercase):
    assert Screen(grid(cursor=(x, 5), lowercase=lowercase)).naming


@pytest.mark.parametrize("policy_name", POLICIES)
def test_all_policies_accept_nicknames_during_battle(policy_name):
    policy = make_policy(policy_name, 1)
    mem = fake_mem({8: "               YES", 9: "               NO", 14: "Give a NICKNAME"})
    mem[W_TILEMAP + 9 * 20 + 14] = 0xED
    mem[W_CURRENT_MENU_ITEM] = 1
    ctx = PolicyContext(snap(in_battle=1), 100, 0, mem)
    assert policy.step(ctx)[0].button == "up"
    mem[W_CURRENT_MENU_ITEM] = 0
    assert policy.step(ctx)[0].button == "a"
    ctx.mem = grid("NICKNAME")
    policy.step(ctx)
    assert policy.naming.target in POKEMON_NAMES
    assert policy.mode == "naming"


@pytest.mark.parametrize("policy_name", POLICIES)
def test_policy_save_restore_preserves_name_in_progress(policy_name):
    policy = make_policy(policy_name, 1)
    ctx = PolicyContext(snap(), 0, 0, grid())
    policy.step(ctx)
    chosen = policy.naming.target
    state = json.loads(json.dumps(policy.state_dict()))
    restored = make_policy(policy_name, 99)
    restored.load_state_dict(state)
    restored.on_restore()
    ctx.mem = grid(entered=chosen[:2])
    assert restored.step(ctx) == policy.step(ctx)
    assert restored.naming.target == chosen
    ctx.mem = grid(entered=chosen)
    assert restored.step(ctx)[0].button == "start"


def test_missed_inputs_partial_names_case_switch_and_existing_names():
    controller = NamingController(1)
    scr = Screen(grid())
    first = controller.step(scr, snap())
    assert controller.step(scr, snap()) == first
    chosen = controller.target
    assert controller.step(Screen(grid(entered="ZZ")), snap()).button == "b"
    assert controller.step(Screen(grid(lowercase=True)), snap()).button == "select"
    assert controller.target == chosen
    assert controller.step(Screen(fake_mem({})), snap()) is None
    assert controller.target is None


def test_seeded_names_vary_and_avoid_repeats_until_pool_exhausted():
    def sequence(seed):
        controller = NamingController(seed)
        result = []
        for header in ("YOUR NAME", "RIVAL NAME") + ("NICKNAME",) * len(POKEMON_NAMES):
            controller.step(Screen(grid(header)), snap())
            result.append(controller.target)
            controller.step(Screen(fake_mem({})), snap())
        return result
    first = sequence(1)
    assert first == sequence(1)
    assert first != sequence(2)
    assert first[0] != first[1]
    assert len(set(first[2:])) == len(POKEMON_NAMES)


def test_intro_selects_new_name_instead_of_a_preset():
    mem = fake_mem({2: "  NEW NAME", 4: "  RED"})
    mem[W_TILEMAP + 4 * 20 + 1] = 0xED
    mem[W_CURRENT_MENU_ITEM] = 1
    controller = NamingController(1)
    opening = snap(player_name="", map=0, party=(), playtime=(0, 0, 0))
    assert controller.step(Screen(mem), opening).button == "up"
    mem[W_CURRENT_MENU_ITEM] = 0
    assert controller.step(Screen(mem), opening).button == "a"
