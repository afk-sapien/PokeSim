from dataclasses import replace

from pokesim.policies.base import PolicyContext
from pokesim.policies.battle import Decision, choose_battle
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import read_box_counts, W_CURRENT_BOX, W_BOX_COUNT
from pokesim.screen import Screen, W_TILEMAP
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import flags, mon, menu


def full_box(**changes):
    base = dict(party=(mon(hp=100, max_hp=100, defense=100),) * 6,
                boxed_pokemon=((165, 3),) * 20, box_counts=(20,) + (0,) * 11,
                map=MAPS['LAVENDER_POKECENTER'], x=13, y=4, frame=100,
                event_flags=flags('EVENT_GOT_POKEDEX'))
    base.update(changes)
    return snap(**base)


def test_capture_requires_party_or_active_box_space():
    s = full_box(in_battle=1, items=((ITEMS['POKE_BALL'], 4),))
    enemy = mon(species=0x54, hp=3, max_hp=40, level=30, moves=(33,), pp=(35,))
    assert choose_battle(s, s.party[0], enemy, 0, required_move=57).kind != 'item'
    assert choose_battle(replace(s, party=s.party[:5]), s.party[0], enemy, 0).kind == 'item'
    assert choose_battle(replace(s, boxed_pokemon=s.boxed_pokemon[:19]), s.party[0], enemy, 0).kind == 'item'


def test_bank_counts_use_live_active_box_and_skip_full_boxes():
    class Memory:
        def __getitem__(self, key):
            if key == W_CURRENT_BOX:
                return 0x80
            if key == W_BOX_COUNT:
                return 20
            bank, address = key
            return 7 if (bank, address) == (3, 0xA000) else 20
    counts = read_box_counts(Memory())
    s = full_box(box_counts=counts)
    assert counts == (20,) * 6 + (7,) + (20,) * 5
    assert s.next_free_box == 6


def test_first_box_change_treats_uninitialized_sram_as_empty():
    memory = bytearray(65536)
    memory[W_BOX_COUNT] = 20
    assert read_box_counts(memory) == (20,) + (0,) * 11


def test_full_storage_does_not_offer_another_full_box():
    s = full_box(box_counts=(20,) * 12)
    assert s.next_free_box is None
    assert not s.can_catch


def test_full_box_routes_to_pc_and_overrides_pending_upgrade():
    p = StrategicPolicy(7)
    p.storage_species = 17
    p.storage_map = MAPS['LAVENDER_POKECENTER']
    s = full_box(textbox=True)
    p.observed_map = s.map
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 1), top=(1, 1))
    action = p.step(PolicyContext(s, 0, 0, memory))[0]
    assert p.goal.key == 'party_box'
    assert p.storage_species is None
    assert all(m != MAPS['LAVENDER_MART'] for m, x, y in p.goal.targets)
    assert action.button == 'down'


def test_change_box_menu_selects_space_and_then_exits_after_success():
    p = StrategicPolicy(7)
    p.goal = Goal('party_box', 'Switch boxes', 'Make room')
    memory = menu({1: '             BOX 1', 2: '             BOX 2', 12: '             BOX12'}, (12, 1), top=(12, 1))
    memory[W_TILEMAP + 1 * 20 + 17] = 0xF7
    memory[W_TILEMAP + 12 * 20 + 16] = 0xF7
    memory[W_TILEMAP + 12 * 20 + 17] = 0xF8
    scr = Screen(memory)
    s = full_box()
    assert scr.kind(s) == 'change_box'
    assert p._dispatch(s, scr, 'change_box', memory)[0].button == 'down'
    p.goal = Goal('secret_key', 'Continue', 'Resume the adventure')
    s = replace(s, active_box=1, boxed_pokemon=(), box_counts=(20,) + (0,) * 11)
    assert p._dispatch(s, scr, 'change_box', memory)[0].button == 'b'


def test_pc_change_box_never_selects_release():
    p = StrategicPolicy(7)
    p.goal = Goal('party_box', 'Switch boxes', 'Make room')
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 5), index=2, top=(1, 1))
    assert p._dispatch(full_box(), Screen(memory), 'pc', memory)[0].button == 'down'
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 7), index=3, top=(1, 1))
    assert p._dispatch(full_box(), Screen(memory), 'pc', memory)[0].button == 'a'


def test_pending_ball_intent_is_cancelled_when_box_is_full():
    p = StrategicPolicy(7)
    p.intent = Decision('item', 0)
    memory = menu({4: 'POKE BALL', 6: 'CANCEL'}, (5, 4), top=(5, 4))
    s = full_box(in_battle=1, items=((ITEMS['POKE_BALL'], 3),))
    assert p._dispatch(s, Screen(memory), 'list', memory)[0].button == 'b'
    assert p.intent is None


def test_no_deposit_when_active_box_is_full():
    p = StrategicPolicy(7)
    p.pc_operation = 'deposit'
    assert p._pc_target(full_box()) is None


def test_seafoam_current_cannot_be_used_as_a_route_to_the_pc():
    from pokesim.policies.navigation import Navigator
    nav = Navigator()
    s = full_box(map=MAPS['SEAFOAM_ISLANDS_B4F'])
    nav.update_story(s)
    exit_tile = (s.map, 20, 17)
    assert exit_tile in nav.story_blocks
    nav.update_story(replace(s, event_flags=flags('EVENT_SEAFOAM3_BOULDER1_DOWN_HOLE',
                                                 'EVENT_SEAFOAM3_BOULDER2_DOWN_HOLE')))
    assert exit_tile not in nav.story_blocks
