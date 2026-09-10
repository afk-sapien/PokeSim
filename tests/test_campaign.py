from dataclasses import replace
import random

from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import story_goal
from pokesim.ram import read_snapshot, W_STATUS_FLAGS1
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import flags, mon


def ready(**kwargs):
    return snap(party=(mon(level=60, moves=(15, 57, 70, 22)),),
                event_flags=flags('EVENT_GOT_POKEDEX'), **kwargs)


def test_bill_prerequisites_and_cut_teaching():
    s = ready(badges=3)
    s = replace(s, party=(mon(level=25),))
    assert story_goal(s).key == 'bill'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BILL_SAID_USE_CELL_SEPARATOR'))
    assert story_goal(s).key == 'bill_pc'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_USED_CELL_SEPARATOR_ON_BILL'))
    assert story_goal(s).key == 'ticket'
    s = replace(s, items=((ITEMS['S_S_TICKET'], 1),))
    assert story_goal(s).key == 'rocket_thief'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_CERULEAN_ROCKET_THIEF'))
    assert story_goal(s).key == 'cut'
    goal = story_goal(replace(s, items=s.items + ((ITEMS['HM01'], 1),)))
    assert goal.key == 'teach_cut' and 'HM01' in goal.reason


def test_later_badges_require_story_items_and_real_completion_flags():
    s = ready(badges=15)
    assert story_goal(s).key == 'poster_guard'
    s = replace(s, items=((ITEMS['SILPH_SCOPE'], 1),))
    assert story_goal(s).key == 'fuji'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_RESCUED_MR_FUJI'))
    assert story_goal(s).key == 'flute'
    s = replace(s, items=((ITEMS['POKE_FLUTE'], 1),))
    assert story_goal(s).key == 'snorlax'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_ROUTE12_SNORLAX'))
    assert story_goal(s).key == 'soul'
    s = ready(badges=31)
    assert story_goal(s).key == 'guard_drink'
    s = replace(s, saffron_open=True)
    assert story_goal(s).key == 'card_key'
    s = replace(s, items=((ITEMS['CARD_KEY'], 1),))
    assert story_goal(s).key == 'silph'
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_SILPH_CO_GIOVANNI'))
    assert story_goal(s).key == 'marsh'
    s = ready(badges=63)
    assert story_goal(s).key == 'secret_key'
    assert story_goal(replace(s, items=((ITEMS['SECRET_KEY'], 1),))).key == 'volcano'
    assert story_goal(ready(badges=127)).key == 'earth'


def test_league_advances_through_all_five_trainers():
    completed = ['EVENT_GOT_POKEDEX']
    pairs = [('lorelei', 'EVENT_BEAT_LORELEIS_ROOM_TRAINER_0'),
             ('bruno', 'EVENT_BEAT_BRUNOS_ROOM_TRAINER_0'),
             ('agatha', 'EVENT_BEAT_AGATHAS_ROOM_TRAINER_0'),
             ('lance', 'EVENT_BEAT_LANCE'), ('rival', 'EVENT_BEAT_CHAMPION_RIVAL')]
    rooms = ['LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM']
    for room, (trainer, flag) in zip(rooms, pairs):
        s = replace(ready(badges=255), map=MAPS[room], event_flags=flags(*completed))
        goal = story_goal(s)
        assert goal.key == 'league_' + trainer
        assert goal.targets and goal.interact
        completed.append(flag)
    assert story_goal(replace(s, event_flags=flags(*completed))).key == 'champion'


def test_guidance_keeps_goal_bias_but_allows_seeded_detours():
    nav = Navigator()
    start = (MAPS['PALLET_TOWN'], 9, 10)
    target = (MAPS['PALLET_TOWN'], 10, 1)
    forward = nav.route(start, [target], 0)
    assert forward
    rng = random.Random(14)
    choices = [nav.guided(start, [target], 0, rng, 0.3) for _ in range(100)]
    assert choices.count(forward) > 50
    assert any(choice != forward for choice in choices)
    assert all(nav.guided(start, [target], 0, rng, 0) == forward for _ in range(5))


def test_snapshot_reads_saffron_gate_unlock():
    memory = bytearray(65536)
    memory[W_STATUS_FLAGS1] = 64
    assert read_snapshot(memory, 0).saffron_open


def test_collected_fossils_open_the_route_to_misty():
    nav = Navigator()
    source = (MAPS['ROUTE_4'], 18, 6)
    state = ready(badges=1, map=source[0], x=18, y=6)
    assert story_goal(state).key == 'moon_trainer'
    state = replace(state, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_GOT_HELIX_FOSSIL'))
    goal = story_goal(state)
    nav.update_story(state)
    assert goal.key == 'cascade'
    assert nav.route(source, goal.targets, 0) is not None
    assert any(target[0] == MAPS['CERULEAN_CITY'] for _, _, target in nav.path)


def test_bill_pc_is_reached_from_below_the_computer():
    state = replace(ready(badges=3), party=(mon(level=25),),
                    event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BILL_SAID_USE_CELL_SEPARATOR'))
    goal = story_goal(state)
    nav = Navigator()
    assert goal.targets == ((MAPS['BILLS_HOUSE'], 1, 5),)
    assert goal.facing == 'up'
    assert nav.route((MAPS['BILLS_HOUSE'], 3, 6), goal.targets, 0)


def test_league_supplies_use_remaining_bag_space_and_prioritize_revives():
    from pokesim.policies.battle import shopping_item
    bag = tuple((item, 1) for item in range(200, 218))
    stock = [ITEMS['FULL_RESTORE'], ITEMS['HYPER_POTION'], ITEMS['REVIVE']]
    assert shopping_item(bag, stock, 30000, league=True) == ITEMS['REVIVE']
    assert shopping_item(bag, stock, 30000) is None
    bag += ((ITEMS['REVIVE'], 5),)
    assert shopping_item(bag, stock, 30000, league=True) == ITEMS['HYPER_POTION']


def test_league_restores_depleted_attacks_before_the_next_battle():
    from pokesim.policies.strategic import StrategicPolicy
    policy = StrategicPolicy(7)
    s = replace(ready(badges=255), map=MAPS['LANCES_ROOM'],
                party=(mon(level=60, moves=(15, 75, 76, 22), pp=(30, 0, 7, 0)),),
                items=((ITEMS['ELIXER'], 1),))
    policy.goal = story_goal(s)
    assert policy._overworld(s, bytearray(65536))[0].button == 'start'
    assert policy.intent.kind == 'item' and policy.intent.index == 0


def test_hidden_guard_opens_robbed_house_after_bill():
    from pokesim.strategy_data import DATA
    m = MAPS['CERULEAN_CITY']
    nav = Navigator()
    state = ready(badges=3)
    nav.update_story(state)
    assert ('up', (m, 27, 12)) not in list(nav.neighbors((m, 27, 13), 0))
    hidden = bytearray(32)
    index = DATA['toggle_objects'].index([m, 10])
    hidden[index // 8] |= 1 << (index % 8)
    nav.update_story(replace(state, hidden_objects=bytes(hidden)))
    assert ('up', (m, 27, 12)) in list(nav.neighbors((m, 27, 13), 0))


def test_observed_step_onto_doorway_keeps_its_map_transition():
    nav = Navigator()
    source = (MAPS['VERMILION_CITY'], 18, 30)
    nav.edges[source] = {'down': (MAPS['VERMILION_CITY'], 18, 31)}
    assert ('down', (MAPS['VERMILION_DOCK'], 14, 0)) in list(nav.neighbors(source, 0))


def test_saffron_gate_requires_drink_and_route7_uses_the_real_exit():
    from pokesim.strategy_data import WORLD
    nav = Navigator()
    s = ready(badges=7)
    nav.update_story(s)
    source = (MAPS['ROUTE_6_GATE'], 3, 3)
    assert ('up', (source[0], 3, 2)) not in list(nav.neighbors(source, 0))
    nav.update_story(replace(s, items=((ITEMS['FRESH_WATER'], 1),)))
    assert ('up', (source[0], 3, 2)) in list(nav.neighbors(source, 0))
    w = WORLD[MAPS['UNDERGROUND_PATH_ROUTE_7']]
    assert w['name'] == 'UndergroundPathRoute7'
    assert nav._warp(MAPS['UNDERGROUND_PATH_ROUTE_7'], w['warps'][0]) == (MAPS['ROUTE_7'], 5, 13)


def test_switch_search_tries_a_neighbor_after_finding_first_lock():
    from pokesim.policies.strategic import StrategicPolicy
    policy = StrategicPolicy(7)
    s = ready(badges=3)
    policy._trash_goal(s)
    first = policy.trash_target
    policy.trash_pending = first
    s = replace(s, event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_1ST_LOCK_OPENED'))
    policy._trash_goal(s)
    second = policy.trash_target
    assert abs(first // 3 - second // 3) + abs(first % 3 - second % 3) == 1
    policy.trash_pending = second
    policy._trash_goal(replace(s, event_flags=flags('EVENT_GOT_POKEDEX')))
    assert policy.trash_first is None


def test_mansion_plan_accounts_for_switches_and_floor_drops():
    from pokesim.policies.puzzles import MansionPlanner, FALLS
    from pokesim.policies.progression import object_goal
    state = ready(badges=63, map=MAPS['POKEMON_MANSION_1F'], x=5, y=26)
    goal = object_goal('secret_key', '', '', 'POKEMON_MANSION_B1F', 'SECRET_KEY')
    planner = MansionPlanner()
    assert planner.route(state, goal.targets, Navigator())
    assert any(action == 'switch' for _, action, _ in planner.path)
    assert any(source[0] == MAPS['POKEMON_MANSION_3F'] and target[:3] in FALLS.values()
               for source, action, target in planner.path)


def test_victory_road_boulder_plan_preserves_a_walkable_push_route():
    from pokesim.policies.puzzles import BoulderPlanner, boulder_task
    from pokesim.strategy_data import WORLD
    s = ready(badges=255, map=MAPS['VICTORY_ROAD_1F'], x=8, y=16)
    nav = Navigator()
    nav.update_story(s)
    nav.live_map = s.map
    nav.live_positions = [tuple(o[:2]) for o in WORLD[s.map]['objects']]
    planner = BoulderPlanner()
    task = boulder_task(s)
    assert task == ('BOULDER1', (17, 13))
    assert planner.route(s, nav, task)
    state, direction = planner.path[-1]
    from pokesim.policies.navigation import DIRS
    dx, dy = DIRS[direction]
    assert (state[2] + dx, state[3] + dy) == task[1]
