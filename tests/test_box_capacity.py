from dataclasses import replace
import random

from pokesim.policies.base import PolicyContext
from pokesim.policies.battle import Decision, choose_battle
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import read_box_counts, W_CURRENT_BOX, W_BOX_COUNT
from pokesim.policies.team import release_target, spare_copies, storage_headroom
from pokesim.screen import Screen, W_TILEMAP
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import fake_mem, flags, mon, menu


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


def collection_with_full_box(party_size=5):
    from pokesim.policies.collection import EVOS
    p = StrategicPolicy(7)
    p.collection.project = {'method': 'evolve', 'parent': 124, 'species': 125,
                            'box': 0, 'evolution': EVOS[124][0], 'key': 'butterfree'}
    p.collection.remaining = 36000
    s = full_box(party=(mon(hp=100, max_hp=100, defense=100),) * party_size,
                 boxed_pokemon=((124, 8),) + ((165, 3),) * 19, textbox=True)
    p.observed_map = s.map
    return p, s


def test_full_source_box_allows_withdrawal_instead_of_switching_away():
    p, s = collection_with_full_box()
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                  (1, 1), top=(1, 1))
    action = p.step(PolicyContext(s, 0, 0, memory))[0]
    assert p.goal.key == 'party_collection'
    assert p.pc_operation == 'withdraw'
    assert action.button == 'a'
    assert p._pc_target(s) == 0

    s = replace(s, frame=s.frame + 100, party=s.party + (mon(species=124, level=8),),
                boxed_pokemon=s.boxed_pokemon[1:], box_counts=(19,) + (0,) * 11)
    action = p.step(PolicyContext(s, 0, 0, memory))[0]
    assert p.goal.key == 'collect_train'
    assert action.button == 'b'


def test_full_party_still_makes_deposit_space_before_retrieving_partner():
    p, s = collection_with_full_box(party_size=6)
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                  (1, 1), top=(1, 1))
    p.step(PolicyContext(s, 0, 0, memory))
    assert p.goal.key == 'party_box'


def test_full_box_without_requested_partner_still_switches_to_free_space():
    p, s = collection_with_full_box()
    s = replace(s, boxed_pokemon=((165, 3),) * 20)
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                  (1, 1), top=(1, 1))
    p.step(PolicyContext(s, 0, 0, memory))
    assert p.goal.key == 'party_box'


def test_collection_leaves_box_selector_when_source_box_is_already_active():
    p, s = collection_with_full_box()
    p.goal = p.collection.goal(s)
    memory = bytearray(65536)
    assert p._dispatch(s, Screen(memory), 'change_box', memory)[0].button == 'b'


def test_full_box_can_reach_the_indigo_plateau_pc_from_route_23():
    p = StrategicPolicy(7)
    s = full_box(map=MAPS['ROUTE_23'], x=18, y=20, badges=255)
    p.observed_map = s.map
    p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    target = (MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8)
    assert target in p.goal.targets
    assert p.nav.route((s.map, s.x, s.y), p.goal.targets, s.frame) is not None
    assert p.nav.path[-1][2] == target

def test_completely_full_storage_abandons_a_withdrawal_instead_of_reopening_the_pc():
    # Every box full and a full party: the exchange cannot happen, so no PC goal is offered.
    p, s = collection_with_full_box(party_size=6)
    s = replace(s, box_counts=(20,) * 12)
    assert s.next_free_box is None and not s.can_catch
    assert p.collection.goal(s) is None
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                  (1, 1), top=(1, 1))
    p.observed_map = s.map
    p.step(PolicyContext(s, 0, 0, memory))
    assert p.goal.key not in ('party_collection', 'party_collection_space', 'party_box')


def test_a_free_party_slot_still_retrieves_a_partner_from_completely_full_storage():
    p, s = collection_with_full_box(party_size=5)
    s = replace(s, box_counts=(20,) * 12)
    assert p.collection.goal(s).key == 'party_collection'


def test_full_storage_stops_offering_projects_that_need_the_pc():
    from pokesim.policies.collection import EVOS
    p, s = collection_with_full_box(party_size=6)
    p.collection.completed_champion = True
    boxed = replace(s, box_counts=(20,) * 12, boxed_pokemon=((124, 8),) * 20)
    for seed in range(12):
        p.collection.project = None
        p.collection.last_choice = -100000
        goal = p.collection.choose(boxed, p.nav, random.Random(seed), Goal('idle', 'Idle', 'Idle'))
        assert (p.collection.project or {}).get('box') is None, 'chose a project needing a withdrawal'
        assert goal is None or not goal.key.startswith('party_')

    # One box with room makes the exchange possible again, so the partner is worth fetching.
    p.collection.project = {'method': 'evolve', 'parent': 124, 'species': 125,
                            'box': 0, 'evolution': EVOS[124][0], 'key': 'butterfree'}
    assert p.collection.goal(replace(boxed, box_counts=(20,) * 11 + (19,))).key == 'party_collection'

def stuffed(**changes):
    """Every box full, with duplicates of a common species and one unique Pokémon."""
    base = dict(party=(mon(hp=100, max_hp=100, defense=100),) * 6,
                boxed_pokemon=((165, 3),) * 19 + ((171, 40),),
                stored_pokemon=tuple((box, 165, 3 + box, '') for box in range(11) for _ in range(20))
                               + tuple((11, 165, 3, '') for _ in range(19)) + ((11, 171, 40, ''),),
                box_counts=(20,) * 12, active_box=11,
                map=MAPS['LAVENDER_POKECENTER'], x=13, y=4, frame=100,
                event_flags=flags('EVENT_GOT_POKEDEX'))
    base.update(changes)
    return snap(**base)


def test_one_copy_of_every_species_always_survives_a_release():
    s = stuffed()
    spare = spare_copies(s)
    assert storage_headroom(s) == 0
    assert (11, 19) not in [entry[:2] for entry in spare], 'the only Aerodactyl must never be offered'
    # 239 copies of one species, minus the single keeper the rule protects.
    assert len(spare) == 238
    box, position = release_target(s)
    assert (box, position) == (0, 0), 'the lowest level duplicate goes first'


def test_a_party_member_counts_as_the_surviving_copy():
    s = snap(party=(mon(species=171, level=50),), stored_pokemon=((0, 171, 9, ''),),
             box_counts=(1,) + (0,) * 11, boxed_pokemon=((171, 9),))
    assert release_target(s) == (0, 0)


def test_a_lone_stored_species_is_never_released():
    s = snap(party=(mon(),), stored_pokemon=((0, 171, 9, ''),), box_counts=(1,) + (0,) * 11,
             boxed_pokemon=((171, 9),))
    assert release_target(s) is None and spare_copies(s) == []


def test_equal_level_duplicates_keep_exactly_one():
    s = snap(party=(mon(),), stored_pokemon=((0, 171, 9, ''), (0, 171, 9, ''), (0, 171, 9, '')),
             box_counts=(3,) + (0,) * 11, boxed_pokemon=((171, 9),) * 3)
    assert len(spare_copies(s)) == 2


def test_an_evolution_partner_is_protected_from_release():
    s = snap(party=(mon(),), stored_pokemon=((0, 124, 8, ''), (0, 124, 5, '')),
             box_counts=(2,) + (0,) * 11, boxed_pokemon=((124, 8), (124, 5)))
    assert release_target(s) == (0, 1)
    assert release_target(s, {124}) is None


def test_storage_buffer_sends_the_run_to_a_pc_to_free_slots():
    p = StrategicPolicy(7)
    s = stuffed(textbox=True)
    p.observed_map = s.map
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 1), top=(1, 1))
    p.step(PolicyContext(s, 0, 0, memory))
    assert p.goal.key == 'party_release'

    # With room to spare the run leaves storage alone.
    roomy = stuffed(box_counts=(20,) * 11 + (10,))
    assert storage_headroom(roomy) >= 5
    p2 = StrategicPolicy(7)
    p2.observed_map = roomy.map
    p2.step(PolicyContext(roomy, 0, 0, memory))
    assert p2.goal.key != 'party_release'


def test_release_menu_is_only_opened_for_the_release_goal():
    p = StrategicPolicy(7)
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 1), top=(1, 1))
    s = stuffed(textbox=True)
    p.goal = Goal('party_release', 'Make room in storage', 'Free a slot')
    # The duplicate to give up lives in box 1, so the box selector comes first.
    assert p._dispatch(s, Screen(memory), 'pc', memory)[0].button == 'down'
    here = stuffed(stored_pokemon=tuple((11, 165, 3 + i, '') for i in range(19)) + ((11, 171, 40, ''),),
                   box_counts=(0,) * 11 + (20,), textbox=True)
    assert p._release_target(here)[0] == here.active_box
    assert p._pc_target(here) == 0
    p.goal = Goal('party_box', 'Switch boxes', 'Make room')
    assert p._pc_target(here) is None


def test_release_confirmation_is_refused_unless_the_policy_asked_for_it():
    p = StrategicPolicy(7)
    memory = menu({0: 'Once released, RATTATA', 1: 'is gone forever. OK?', 12: '  YES', 13: '  NO'},
                  (1, 12), top=(1, 12))
    scr = Screen(memory)
    assert scr.yes_no
    p.goal = Goal('secret_key', 'Continue', 'Resume the adventure')
    assert p._dispatch(stuffed(), scr, 'yes_no', memory)[0].button == 'down', 'must land on NO'
    p.goal = Goal('party_release', 'Make room in storage', 'Free a slot')
    assert p._dispatch(stuffed(), scr, 'yes_no', memory)[0].button == 'a', 'YES is already selected'

def test_the_box_change_confirmation_is_answered_yes():
    # Gen I asks "data will be saved. Is that okay?" with the PC menu still drawn behind it, so the
    # prompt carries CHANGE BOX and RELEASE PKMN. Answering no reopens the menu forever.
    behind = {1: '  WITHDRAW PKMN', 3: '  DEPOSIT PKMN', 5: '  RELEASE PKMN', 7: '  CHANGE BOX',
              14: 'Is that okay?'}
    memory = menu({**behind, 11: '  YES', 12: '  NO'}, (1, 12), index=1, top=(1, 11))
    p = StrategicPolicy(7)
    p.goal = Goal('party_box', 'Make room for new catches', 'Switch to a box with space')
    p.menu_context = 'pc'
    assert p._dispatch(full_box(), Screen(memory), 'yes_no', memory)[0].button == 'up'


def test_a_release_confirmation_is_still_refused_outside_a_release():
    # The real prompt says the Pokémon is gone forever; the PC menu's RELEASE entry must not count.
    confirm = {5: '  RELEASE PKMN', 13: 'Once released, RATTATA', 14: 'is gone forever. OK?'}
    memory = menu({**confirm, 11: '  YES', 12: '  NO'}, (1, 11), index=0, top=(1, 11))
    p = StrategicPolicy(7)
    p.menu_context = 'pc'
    p.goal = Goal('party_box', 'Make room for new catches', 'Switch to a box with space')
    assert p._dispatch(full_box(), Screen(memory), 'yes_no', memory)[0].button == 'down'
    p.goal = Goal('party_release', 'Make room in storage', 'Free a slot')
    assert p._dispatch(full_box(), Screen(memory), 'yes_no', memory)[0].button == 'a'
