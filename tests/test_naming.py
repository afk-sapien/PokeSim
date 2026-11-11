import json

import pytest

from pokesim.policies import POLICIES, make_policy
from pokesim.runtime.policy import PolicyContext
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
    ctx = PolicyContext(snap(in_battle=1), 0, mem)
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
    ctx = PolicyContext(snap(), 0, grid())
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


def test_every_name_is_one_the_cartridge_can_hold():
    """The naming screen types A-Z only and the nickname field keeps ten characters."""
    import re
    from pokesim.policies.naming import NAME_LIMIT

    for name in POKEMON_NAMES + TRAINER_NAMES:
        assert re.fullmatch(f'[A-Z]{{1,{NAME_LIMIT}}}', name), name


def test_the_pool_outgrows_a_single_adventure_and_keeps_the_written_names():
    """Names ran out after 100 catches and started repeating; pairs push that well past a run."""
    from pokesim.policies.naming import CURATED_NAMES

    assert len(POKEMON_NAMES) == len(set(POKEMON_NAMES))
    assert POKEMON_NAMES[:len(CURATED_NAMES)] == CURATED_NAMES
    assert len(POKEMON_NAMES) > 1000


def test_names_are_drawn_without_repeating_until_the_pool_is_spent():
    """The same rule step() uses: draw from what is left, and remember what was taken."""
    controller = NamingController(7)
    drawn = []
    for _ in range(400):
        remaining = [name for name in POKEMON_NAMES if name not in controller.used]
        chosen = controller.rng.choice(remaining)
        controller.used.add(chosen)
        drawn.append(chosen)
    assert len(set(drawn)) == len(drawn)


def test_custom_parts_validate_and_extend_defaults_without_truncation():
    from pokesim.nicknames import validate_parts, name_pool
    parts = validate_parts({'nickname_prefixes': [' chaos ', 'CHAOS'], 'nickname_suffixes': ['goose']})
    assert parts == {'nickname_prefixes': ['CHAOS'], 'nickname_suffixes': ['GOOSE']}
    pool = name_pool(tuple(parts['nickname_prefixes']), tuple(parts['nickname_suffixes']))
    assert 'CHAOSGOOSE' in pool and 'CHAOSLORD' in pool and 'MEATGOOSE' in pool
    assert set(POKEMON_NAMES) <= set(pool)
    assert all(len(name) <= 10 for name in pool)
    assert name_pool() == POKEMON_NAMES
    for value in [['BAD!'], [''], ['TOOLONGGG'], ['é'], [5], ['A'] * 101, 'SOUP']:
        with pytest.raises(ValueError):
            validate_parts({'nickname_prefixes': value, 'nickname_suffixes': []})


def test_custom_pool_applies_to_new_names_and_keeps_partial_name(monkeypatch):
    from pokesim import config
    controller = NamingController(1)
    controller.used.update(POKEMON_NAMES)
    monkeypatch.setattr(config, 'NICKNAME_PREFIXES', ('CHAOS',))
    monkeypatch.setattr(config, 'NICKNAME_SUFFIXES', ())
    controller.step(Screen(grid('NICKNAME')), snap())
    chosen = controller.target
    assert chosen.startswith('CHAOS')
    monkeypatch.setattr(config, 'NICKNAME_PREFIXES', ())
    controller.step(Screen(grid('NICKNAME', entered=chosen[:2])), snap())
    assert controller.target == chosen


@pytest.mark.parametrize('header,expected', [('YOUR NAME', 'TY'), ('RIVAL NAME', 'GARY')])
def test_configured_intro_name_is_typed_and_survives_restore(monkeypatch, header, expected):
    from pokesim import config
    monkeypatch.setattr(config, 'TRAINER_NAME', 'TY', raising=False)
    monkeypatch.setattr(config, 'RIVAL_NAME', 'GARY', raising=False)
    controller = NamingController(1)
    controller.step(Screen(grid(header)), snap())
    assert controller.target == expected
    restored = NamingController(2)
    restored.load_state_dict(json.loads(json.dumps(controller.state_dict())))
    assert restored.step(Screen(grid(header, entered=expected)), snap()).button == 'start'
    assert restored.target == expected


def test_configured_rival_is_reserved_from_random_trainer(monkeypatch):
    from pokesim import config
    import pokesim.policies.naming as naming
    monkeypatch.setattr(config, 'TRAINER_NAME', '', raising=False)
    monkeypatch.setattr(config, 'RIVAL_NAME', 'ASH', raising=False)
    monkeypatch.setattr(naming, 'TRAINER_NAMES', ('ASH', 'GARY'))
    controller = NamingController(1)
    controller.step(Screen(grid('YOUR NAME')), snap())
    assert controller.target == 'GARY'


def test_full_names_and_exclusions_reach_the_effective_pool(monkeypatch):
    from pokesim.nicknames import configured_pool, name_pool, nickname_defaults, validate_parts
    from pokesim import config
    settings = validate_parts({**nickname_defaults(), 'nickname_names': [' velcro ', 'VELCRO'],
                               'nickname_excluded_prefixes': ['MEAT'],
                               'nickname_excluded_suffixes': ['BARON'],
                               'nickname_excluded_names': ['TAXFRAUD', 'SOUPLORD']})
    for key, value in settings.items():
        monkeypatch.setattr(config, key.upper(), tuple(value))
    pool = configured_pool()
    assert pool.count('VELCRO') == 1
    assert 'MEATBARON' not in pool and 'SOUPBARON' not in pool
    assert 'MEATKING' not in pool and 'MEATBALL' in pool
    assert 'TAXFRAUD' not in pool and 'SOUPLORD' not in pool
    assert 'SOUPKING' in pool
    assert name_pool() != pool


def test_an_empty_nickname_pool_is_accepted_and_long_full_names_are_rejected():
    import pytest
    from pokesim.nicknames import CURATED_NAMES, NAME_PREFIXES, name_pool, nickname_defaults, validate_parts
    empty = validate_parts({**nickname_defaults(), 'nickname_excluded_prefixes': list(NAME_PREFIXES),
                            'nickname_excluded_names': list(CURATED_NAMES)})
    assert empty['nickname_excluded_names'] == list(CURATED_NAMES)
    assert name_pool(*(tuple(value) for value in empty.values())) == ()
    with pytest.raises(ValueError, match='1 to 10'):
        validate_parts({**nickname_defaults(), 'nickname_names': ['ELEVENABCDE']})
    result = validate_parts({**nickname_defaults(), 'nickname_names': ['TENLETTERS']})
    assert result['nickname_names'] == ['TENLETTERS']


def nickname_mode(monkeypatch, mode):
    """Set up nicknames as on with no saved pool, off, or on with a saved pool that leaves nothing."""
    from pokesim import config
    from pokesim.nicknames import CURATED_NAMES, NAME_PREFIXES, NICKNAME_FIELDS
    for field in NICKNAME_FIELDS:
        monkeypatch.setattr(config, field.upper(), ())
    monkeypatch.setattr(config, 'NICKNAMES', mode != 'off')
    if mode == 'empty':
        monkeypatch.setattr(config, 'NICKNAME_EXCLUDED_PREFIXES', NAME_PREFIXES)
        monkeypatch.setattr(config, 'NICKNAME_EXCLUDED_NAMES', CURATED_NAMES)


def nickname_prompt(menu_index):
    mem = fake_mem({8: "               YES", 9: "               NO", 14: "Give a NICKNAME"})
    mem[W_TILEMAP + (8 + menu_index) * 20 + 14] = 0xED
    mem[W_CURRENT_MENU_ITEM] = menu_index
    return Screen(mem)


def test_gen1_no_saved_pool_still_gives_built_in_nicknames(monkeypatch):
    from pokesim.nicknames import configured_pool
    nickname_mode(monkeypatch, 'unsaved')
    assert configured_pool() and set(configured_pool()) <= set(POKEMON_NAMES)
    controller = NamingController(1)
    assert controller.step(nickname_prompt(0), snap()).button == "a"
    controller.step(Screen(grid('NICKNAME')), snap())
    assert controller.target in POKEMON_NAMES


@pytest.mark.parametrize('mode', ('off', 'empty'))
def test_gen1_answers_no_when_nicknames_are_off_or_the_saved_pool_is_empty(monkeypatch, mode):
    from pokesim.nicknames import configured_pool
    nickname_mode(monkeypatch, mode)
    assert configured_pool() == ()
    controller = NamingController(1)
    assert controller.step(nickname_prompt(0), snap()).button == "down"
    assert controller.step(nickname_prompt(1), snap()).button == "a"
    # A naming screen opened before the switch clears its letters and accepts the species name.
    assert controller.step(Screen(grid('NICKNAME', entered='AB')), snap()).button == "b"
    assert controller.step(Screen(grid('NICKNAME')), snap()).button == "start"
    # Player and rival naming still pick names.
    controller.step(Screen(grid('YOUR NAME')), snap())
    assert controller.target in TRAINER_NAMES


def gen2_nickname_prompt():
    from types import SimpleNamespace
    rows = [''] * 18
    rows[8], rows[9] = '              ▶YES', '               NO'
    rows[14], rows[16] = 'Give a nickname to', 'the received EEVEE?'
    return SimpleNamespace(text='\n'.join(rows), tiles=rows)


def test_gen2_no_saved_pool_leaves_the_nickname_prompt_to_the_policy(monkeypatch):
    from pokesim.gen2.naming import Naming
    nickname_mode(monkeypatch, 'unsaved')
    assert Naming(1).step(gen2_nickname_prompt(), None) is None


@pytest.mark.parametrize('mode', ('off', 'empty'))
def test_gen2_answers_no_when_nicknames_are_off_or_the_saved_pool_is_empty(monkeypatch, mode):
    from pokesim.gen2.naming import Naming
    nickname_mode(monkeypatch, mode)
    assert Naming(1).step(gen2_nickname_prompt(), None) == 'b'
    other = gen2_nickname_prompt()
    other.tiles[14], other.tiles[16] = 'Save the game?', ''
    assert Naming(1).step(other, None) is None


@pytest.mark.parametrize('mode,expected', [('unsaved', 'caller'), ('off', 'no'), ('empty', 'no')])
def test_gen2_catches_hand_the_nickname_prompt_to_core_only_when_naming(monkeypatch, mode, expected):
    from pokesim.gen2.menus import Throw
    nickname_mode(monkeypatch, mode)
    task = Throw(4)
    monkeypatch.setattr(Throw, 'options', lambda self, snapshot: {})
    assert task.build(None).nickname == expected


@pytest.mark.parametrize('mode', ('off', 'empty'))
def test_rewards_keep_the_species_name_without_nicknames(monkeypatch, mode):
    from pokesim.trade import event
    nickname_mode(monkeypatch, 'unsaved')
    named = event.gift_slot('reward-name', random_name=True)
    nickname_mode(monkeypatch, mode)
    plain = event.gift_slot('reward-name', random_name=True)
    assert plain == event.gift_slot('reward-name')
    assert plain.nick == 'MEW' and named.nick != 'MEW'
