from dataclasses import replace
import json

from pokesim.benchmark import Metrics, aggregate
from pokesim.policies.base import PolicyContext
from pokesim.policies.battle import (Decision, choose_battle, damage, effectiveness, healing_item,
                                    needs_healing, ranked_moves, replacement_slot, shopping_item)
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import milestones, story_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import PartyMon, read_snapshot, W_PARTY_MONS, W_PARTY_COUNT, W_EVENT_FLAGS
from pokesim.screen import Screen, W_CURRENT_MENU_ITEM, W_TOP_MENU_X, W_TOP_MENU_Y, W_TILEMAP
from pokesim.strategy_data import EVENTS, ITEMS, MAPS, MOVES, SPECIES, WORLD
from test_events import snap
from test_screen import fake_mem


def mon(**changes):
    return replace(PartyMon(0x99, 40, 40, 15, 'BULBASAUR', types=(22, 3),
                            moves=(33, 22, 45, 0), pp=(35, 10, 40, 0), attack=25,
                            defense=25, speed=25, special=35), **changes)


def flags(*names):
    data = bytearray(320)
    for name in names:
        bit = EVENTS[name]
        data[bit // 8] |= 1 << (bit % 8)
    return bytes(data)


def menu(lines, cursor, index=0, top=(9, 14)):
    mem = fake_mem(lines)
    x, y = cursor
    mem[W_TILEMAP + y * 20 + x] = 0xED
    mem[W_CURRENT_MENU_ITEM] = index
    mem[W_TOP_MENU_X], mem[W_TOP_MENU_Y] = top
    return mem


def test_generation_one_rules_and_move_choice():
    assert effectiveness(8, (24, 24)) == 0
    assert effectiveness(7, (3, 3)) == 2
    assert effectiveness(25, (20, 20)) == 1
    assert effectiveness(22, (5, 4)) == 4
    me = mon()
    onix = mon(species=34, types=(5, 4), defense=80)
    assert ranked_moves(me, onix)[0][1] == 1
    assert damage(69, me, mon(types=(8, 8))) == me.level
    assert damage(82, me, onix) == 40
    assert ranked_moves(replace(me, pp=(35, 0, 40, 0)), onix)[0][1] != 1


def test_catching_conserves_balls_and_master_ball():
    me = mon(hp=100, max_hp=100, defense=100)
    enemy = mon(species=0x54, hp=3, max_hp=40, level=3, moves=(33,), pp=(35,))
    s = snap(party=(me,), in_battle=1, items=((ITEMS['MASTER_BALL'], 1), (ITEMS['POKE_BALL'], 4)))
    decision = choose_battle(s, me, enemy, 0)
    assert decision.kind == 'item' and decision.index == 1
    owned = replace(s, owned=frozenset({1, SPECIES[enemy.species]['dex']}))
    assert choose_battle(owned, me, enemy, 0).kind != 'item'
    assert choose_battle(replace(s, in_battle=2), me, enemy, 0).kind != 'item'
    assert choose_battle(replace(s, items=((ITEMS['MASTER_BALL'], 1),)), me, enemy, 0).kind != 'item'
    assert choose_battle(s, me, enemy, 0, catch_attempts=5).kind != 'item'


def test_heal_switch_run_and_resource_thresholds():
    me = mon(hp=4)
    enemy = mon(level=10)
    strong = mon(hp=100, max_hp=100, defense=100)
    s = snap(party=(me, strong), in_battle=2)
    assert choose_battle(s, me, enemy, 0).kind == 'switch'
    assert choose_battle(replace(s, party=(me,), in_battle=1), me, enemy, 0).kind == 'run'
    assert healing_item(((ITEMS['POTION'], 1),), me) == 0
    assert healing_item(((ITEMS['POTION'], 1),), replace(me, hp=39)) is None
    assert needs_healing((replace(me, hp=40, pp=(0, 0, 0, 0)),))
    assert needs_healing((replace(me, hp=40, status=8),))
    assert not needs_healing((strong,))


def test_shopping_respects_budget_and_inventory():
    stock = [ITEMS['POKE_BALL'], ITEMS['POTION'], ITEMS['ANTIDOTE']]
    assert shopping_item((), stock, 3000) == ITEMS['POKE_BALL']
    assert shopping_item((), stock, 300) is None
    items = ((ITEMS['POKE_BALL'], 5), (ITEMS['POTION'], 3), (ITEMS['ANTIDOTE'], 2))
    assert shopping_item(items, stock, 3000) is None
    full = tuple((50 + i, 1) for i in range(20))
    assert shopping_item(full, stock, 3000) is None


def test_move_learning_protects_hms_and_improves_moveset():
    me = mon(moves=(15, 33, 45, 73))
    assert replacement_slot(me, 22) in (1, 2, 3)
    assert replacement_slot(mon(moves=(15, 19, 57, 70)), 22) is None
    assert replacement_slot(me, 45) is None


def test_progression_uses_flags_and_training_prerequisite():
    assert story_goal(snap(party=())).key == 'meet_oak'
    assert story_goal(snap(party=(), event_flags=flags('EVENT_FOLLOWED_OAK_INTO_LAB'))).key == 'starter'
    assert story_goal(snap()).key == 'parcel'
    assert story_goal(snap(items=((ITEMS['OAKS_PARCEL'], 1),))).key == 'pokedex'
    ready = snap(party=(mon(),), event_flags=flags('EVENT_GOT_POKEDEX'))
    assert story_goal(ready).key == 'boulder'
    assert story_goal(replace(ready, party=(mon(level=5, hp=20, max_hp=20, attack=10, defense=10, special=10, moves=(33, 45), pp=(35, 40)),))).key == 'train_brock'
    assert story_goal(replace(ready, badges=1)).key == 'train_cascade'
    assert story_goal(replace(ready, badges=1, party=(mon(level=20, hp=60, max_hp=60, attack=40, defense=40, special=55),))).key == 'cascade'


def test_directed_edges_observation_and_restore():
    nav = Navigator()
    nav.use_world = False
    a, b = (1, 3, 4), (2, 8, 9)
    nav.issued(a, 'up', 0)
    nav.observe(b, 30)
    assert list(nav.neighbors(a, 30)) == [('up', b)]
    assert list(nav.neighbors(b, 30)) == []
    assert nav.route(a, [b], 30) == 'up'
    saved = json.loads(json.dumps(nav.state_dict()))
    loaded = Navigator()
    loaded.use_world = False
    loaded.load_state_dict(saved)
    assert loaded.route(a, [b], 0) == 'up'
    loaded.issued(b, 'left', 0)
    loaded.observe(b, 30, interrupted=True)
    assert not loaded.failures


def test_failed_movement_expires_and_movement_is_not_a_wall():
    nav = Navigator()
    nav.use_world = False
    p = (1, 0, 0)
    nav.issued(p, 'up', 0)
    nav.observe(p, 30, walking=True)
    assert not nav.failures
    nav.observe(p, 40)
    nav.issued(p, 'up', 50)
    nav.observe(p, 80)
    assert nav.blocked[(p, 'up')] > 80
    assert nav.blocked[(p, 'up')] < 1000
    nav.restore()
    assert nav.attempt is None and not nav.blocked


def test_route_from_bedroom_through_doors_to_oak_and_mart():
    nav = Navigator()
    home = (MAPS['REDS_HOUSE_2F'], 3, 6)
    oak = (MAPS['PALLET_TOWN'], 10, 1)
    assert nav.route(home, [oak], 0) in ('up', 'right', 'left', 'down')
    assert len({p[0] for _, _, p in nav.path}) >= 3
    assert nav.route(oak, [(MAPS['VIRIDIAN_MART'], 2, 5)], 0) is not None
    assert any(a[0] != b[0] for a, _, b in nav.path)


def test_visible_menu_states_and_one_action_per_decision():
    s = snap(in_battle=1, party=(mon(),))
    mem = menu({14: '          FIGHT PKMN', 16: '          ITEM  RUN'}, (9, 14))
    assert Screen(mem).kind(s) == 'battle'
    # The strategic controller never emits a blind sequence of menu commands.
    pol = StrategicPolicy(1)
    actions = pol.step(PolicyContext(s, 0, 0, mem))
    assert len(actions) == 1
    pol.intent = Decision('switch', 1)
    pol.on_restore()
    assert pol.intent is None
    mem = menu({13: '      TACKLE', 14: '      GROWL'}, (5, 13), 1, (5, 12))
    assert Screen(mem).kind(s) == 'moves'
    mem = menu({8: '      TACKLE', 14: 'Which move to forget'}, (5, 8), 0, (5, 8))
    assert Screen(mem).kind(s) == 'learn_move'
    mem = menu({0: '   BULBASAUR', 14: 'Choose a MON.'}, (0, 0), 0, (0, 0))
    assert Screen(mem).kind(s) == 'party'


def test_healing_prompt_and_shop_transition_do_not_cancel():
    s = snap(party=(mon(hp=8),), playtime=(0, 10, 0))
    mem = menu({8: '             HEAL', 10: '             CANCEL'}, (12, 8), 0, (12, 8))
    scr = Screen(mem)
    pol = StrategicPolicy(1)
    assert scr.kind(s) == 'heal'
    assert pol._dispatch(s, scr, 'heal', mem)[0].button == 'a'
    mem = fake_mem({1: '  BUY', 3: '  SELL', 5: '  QUIT', 14: 'May I help you?'})
    # The greeting and shop menu overlap before the cursor becomes active.
    assert pol._dispatch(s, Screen(mem), 'dialogue', mem)[0].button == 'a'


def test_map_transition_does_not_record_mismatched_coordinates():
    pol = StrategicPolicy(1)
    mem = fake_mem({})
    s = snap(map=MAPS['VIRIDIAN_FOREST_NORTH_GATE'], x=3, y=43, frame=100)
    action = pol.step(PolicyContext(s, 0, 0, mem))[0]
    assert action.button is None
    assert not pol.nav.visits and not pol.nav.edges


def test_snapshot_reads_moves_stats_and_flags():
    mem = bytearray(65536)
    mem[W_PARTY_COUNT] = 1
    b = W_PARTY_MONS
    mem[b] = 0x99
    mem[b + 4] = 8
    mem[b + 5:b + 7] = bytes((22, 3))
    mem[b + 8:b + 12] = bytes((33, 22, 45, 0))
    mem[b + 29:b + 33] = bytes((0xC4, 9, 40, 0))
    mem[b + 36:b + 44] = bytes((0, 20, 0, 30, 0, 40, 0, 50))
    mem[W_EVENT_FLAGS:W_EVENT_FLAGS + 320] = flags('EVENT_GOT_POKEDEX')
    s = read_snapshot(mem, 0)
    p = s.party[0]
    assert p.pp == (4, 9, 40, 0)
    assert (p.attack, p.defense, p.speed, p.special) == (20, 30, 40, 50)
    assert milestones(s)['pokedex']


def test_metrics_count_transitions_and_first_completion_only():
    m = Metrics()
    m.observe(snap(), 10)
    m.observe(snap(), 20)
    dead = snap(party=(mon(hp=0),))
    m.observe(dead, 30)
    m.observe(dead, 40)
    m.observe(dead, 60)
    assert m.blackouts == 1 and m.milestones['starter'] == 10
    m.observe(snap(), 70)
    m.observe(dead, 80)
    m.observe(dead, 110)
    assert m.blackouts == 2
    results = [dict(scenario='boot', policy='strategic', blackouts=0, recovery_reloads=0, milestones={'boulder': 100}),
               dict(scenario='boot', policy='strategic', blackouts=1, recovery_reloads=0, milestones={})]
    summary = aggregate(results)[0]
    assert summary['milestones']['boulder'] == {'completion_rate': 0.5, 'mean_frames_on_success': 100}
    failed = aggregate([dict(scenario='boot', policy='old', target='boulder', blackouts=0,
                             recovery_reloads=0, milestones={})])[0]
    assert failed['milestones']['boulder'] == {'completion_rate': 0, 'mean_frames_on_success': None}


def test_weak_partners_pp_does_not_hide_an_exhausted_lead():
    lead = mon(level=40, pp=(0, 0, 40, 0))
    reserve = mon(level=5)
    assert needs_healing((lead, reserve))
