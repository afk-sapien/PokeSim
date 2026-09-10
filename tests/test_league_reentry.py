from dataclasses import replace

from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import story_goal
from pokesim.policies.team import next_opponent
from pokesim.strategy_data import MAPS
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
