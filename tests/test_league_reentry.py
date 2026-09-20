from dataclasses import replace

from pokesim.policies.base import PolicyContext
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import journey, milestones, story_goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.team import next_opponent
from pokesim.strategy_data import ITEMS, MAPS
from test_events import snap
from test_strategy import flags, mon


WINS = ('EVENT_BEAT_LORELEIS_ROOM_TRAINER_0', 'EVENT_BEAT_BRUNOS_ROOM_TRAINER_0',
        'EVENT_BEAT_AGATHAS_ROOM_TRAINER_0', 'EVENT_BEAT_LANCE')


def returning_trainer(**changes):
    base = dict(map=MAPS['ROUTE_22_GATE'], x=8, y=6, badges=255,
                party=(mon(level=80, moves=(15, 57, 70, 22)),),
                event_flags=flags('EVENT_GOT_POKEDEX', *WINS))
    base.update(changes)
    return snap(**base)


def test_old_league_wins_route_to_reachable_lobby_before_champion():
    s = returning_trainer()
    goal = story_goal(s)
    assert goal.key == 'league_entrance'
    assert goal.targets == ((MAPS['INDIGO_PLATEAU_LOBBY'], 8, 10),)
    nav = Navigator()
    nav.update_story(s)
    assert nav.route((s.map, s.x, s.y), goal.targets, 0) is not None
    assert next_opponent(s) == 256


def test_lobby_starts_with_lorelei_even_before_old_flags_reset():
    s = returning_trainer(map=MAPS['INDIGO_PLATEAU_LOBBY'])
    assert story_goal(s).key == 'league_lorelei'
    assert story_goal(replace(s, event_flags=flags('EVENT_GOT_POKEDEX'))).key == 'league_lorelei'


def test_inside_a_room_challenge_its_trainer_without_backtracking():
    s = returning_trainer(map=MAPS['AGATHAS_ROOM'], event_flags=flags('EVENT_GOT_POKEDEX'))
    assert story_goal(s).key == 'league_agatha'
    assert next_opponent(s) == 258


def test_after_winning_advance_to_the_immediate_next_room():
    s = returning_trainer(map=MAPS['LORELEIS_ROOM'])
    assert story_goal(s).key == 'league_bruno'
    assert next_opponent(s) == 257
    s = replace(s, map=MAPS['LANCES_ROOM'])
    assert story_goal(s).key == 'league_rival'
    assert next_opponent(s) == 260


def test_actual_champion_victory_still_completes_campaign():
    s = returning_trainer(event_flags=flags('EVENT_GOT_POKEDEX', *WINS, 'EVENT_BEAT_CHAMPION_RIVAL'))
    assert story_goal(s).key == 'champion'


def test_saved_championship_remains_visible_after_league_flags_reset():
    s = returning_trainer(hall_of_fame_count=6, event_flags=flags('EVENT_GOT_POKEDEX'))
    assert milestones(s)['champion']
    assert journey(s, 'collect_train')[-1]['done']
    assert not milestones(replace(s, hall_of_fame_count=0))['champion']


def postgame_policy(**changes):
    s = returning_trainer(map=MAPS['INDIGO_PLATEAU_LOBBY'], x=8, y=10,
                          hall_of_fame_count=6, frame=100,
                          items=((ITEMS['POKE_BALL'], 10), (ITEMS['SUPER_POTION'], 10),
                                 (ITEMS['REVIVE'], 5), (ITEMS['FULL_HEAL'], 3)), **changes)
    p = StrategicPolicy(7)
    p.observed_map = s.map
    p.collection.cooldown = 1200
    return p, s


def test_postgame_cooldown_does_not_start_an_accidental_league_attempt():
    p, s = postgame_policy()
    for frame in range(100, 1100, 12):
        actions = p.step(PolicyContext(replace(s, frame=frame), 0, frame / 60,
                                       bytearray(65536)))
        assert p.goal.key == 'collect_plan'
        assert all(action.button is None for action in actions)
    assert p.recoveries == 0


def test_postgame_planning_still_selects_the_next_expedition():
    p, s = postgame_policy()
    p.collection.cooldown = 0
    actions = p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    assert p.collection.project is not None
    assert p.goal.key != 'collect_plan'


def test_explicit_postgame_rematch_can_still_enter_the_league():
    p, s = postgame_policy()
    p.collection.project = {'method': 'rematch', 'hof_count': 6, 'key': 'rematch'}
    p.collection.remaining = 300000
    p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    assert p.goal.key == 'league_lorelei'


def test_postgame_policy_finishes_a_league_attempt_already_in_progress():
    p, s = postgame_policy()
    s = replace(s, map=MAPS['AGATHAS_ROOM'], event_flags=flags('EVENT_GOT_POKEDEX'))
    p.observed_map = s.map
    p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    assert p.goal.key == 'league_agatha'


def test_empty_plateau_planner_returns_through_victory_road():
    p, s = postgame_policy()
    s = replace(s, map=MAPS['INDIGO_PLATEAU'], x=9, y=7)
    p.observed_map = s.map
    p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    assert p.goal.key == 'collect_passage'
    assert p.goal.targets == ((MAPS['VICTORY_ROAD_3F'], 27, 15),)
    assert p.mode != 'planning the next expedition'


def test_empty_planner_leaves_the_isolated_east_patch_of_route_23():
    p, s = postgame_policy()
    s = replace(s, map=MAPS['ROUTE_23'], x=19, y=32)
    p.observed_map = s.map
    p.step(PolicyContext(s, 0, 0, bytearray(65536)))
    assert p.goal.key == 'collect_passage'
