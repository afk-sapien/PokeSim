"""Gen II readiness: a matchup score against each boss's ace and the gates that train before a boss."""
import os
from types import SimpleNamespace

import pytest

from pokecore.gen2.ram import calculated_stats
from pokesim.planning.losses import ace_slot
from pokesim.planning.readiness import MATCHUP, Boss, Team, Train, judge, score

TACKLE, EMBER, LEER, HARDEN, CUT, STRENGTH, FLAMETHROWER = 33, 52, 43, 106, 15, 70, 53

# The boss parties of a clean Gold cartridge, as boss_parties reads them, by trainer class.
BUGSY = [{'level': 14, 'species': 11, 'moves': [33, 81, 106, 0]}, {'level': 14, 'species': 14, 'moves': [40, 81, 106, 0]},
         {'level': 16, 'species': 123, 'moves': [98, 43, 210, 0]}]
LEAGUE = {
    11: [{'level': 40, 'species': 178, 'moves': [98, 248, 109, 94]}, {'level': 42, 'species': 178, 'moves': [98, 248, 109, 94]}],
    15: [{'level': 44, 'species': 169, 'moves': [104, 98, 17, 92]}],
    13: [{'level': 46, 'species': 68, 'moves': [157, 193, 233, 238]}],
    14: [{'level': 47, 'species': 229, 'moves': [46, 228, 53, 242]}],
    16: [{'level': 47, 'species': 149, 'moves': [86, 239, 87, 63]}, {'level': 50, 'species': 149, 'moves': [126, 219, 200, 63]}],
}


@pytest.fixture
def real_data():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, 'gold')
    data.boss_parties = {3: BUGSY, **LEAGUE}
    return data


@pytest.fixture
def walks(real_data, monkeypatch):
    """Every training map has a reachable tile, since these snapshots carry no route to follow."""
    from pokesim.gen2 import training
    monkeypatch.setattr(training, 'walk_points', lambda policy, snapshot, mid: [(10, 10, 0)])


def mon(data, species, level, moves, egg=False):
    stats = calculated_stats(data.species[species]['stats'], level, (8, 8, 8, 8, 8), (0,) * 5)
    return SimpleNamespace(species=species, level=level, egg=egg, max_hp=stats[0], hp=stats[0], stats=stats,
                           status=0, moves=moves)


def at(data, map_name, party, badges=1):
    return SimpleNamespace(map=data.map_ids[map_name], x=5, y=5, frame=1000, badges=badges, party=party,
                           event=lambda name: True)


def test_the_shared_score_and_gates():
    # A member that survives four hits and needs two to win scores 100. One that deals nothing scores 0.
    assert score(40, 20, 10, 40, False) == 100
    assert score(40, 0, 10, 40, False) == 0
    assert score(20, 10, 10, 40, True) == 40
    # A gym trains while the best score is under 75 and the best fighter is under the ace + 10.
    gym = lambda best: Boss('hive', 16, scores=(best,))
    assert judge(gym(74), Team(25)) == Train(MATCHUP, 26)
    assert judge(gym(75), Team(13)) is None and judge(gym(10), Team(26)) is None
    # The League trains while a room scores under 60 and the best fighter is under the top ace.
    league = lambda *scores: Boss('league', 50, scores=scores, league=True)
    assert judge(league(100, 59), Team(49)) == Train(MATCHUP, 50) and judge(league(60, 60), Team(10)) is None
    assert judge(league(0), Team(50)) is None


def test_one_fighter_and_a_bench_of_non_attackers_trains_before_bugsy(real_data, walks):
    # The Gold run at Azalea Gym: Cyndaquil at Lv 13 and a Metapod with only Harden. Nothing gated
    # gyms after Falkner, so the team went in, could not end the battle and blacked out four times.
    from pokesim.gen2.policy import Goal, Policy
    from pokesim.gen2.readiness import readiness
    policy = Policy(real_data)
    cyndaquil = mon(real_data, 155, 13, (TACKLE, LEER, EMBER, 0))
    party = (cyndaquil, mon(real_data, 11, 7, (HARDEN, 0, 0, 0)))
    goal = Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up')
    assert readiness(policy, party, 'hive') < 75
    training = policy.boss_training(at(real_data, 'AZALEA_TOWN', party), goal)
    assert training.key == 'collection_train' and training.map_name == 'ROUTE_33'
    assert 'Bugsy' in training.label and 'level 26' in training.label
    # Inside the gym the battle carries on.
    assert policy.boss_training(at(real_data, 'AZALEA_GYM', party), goal) is None
    # A few levels later Cyndaquil matches up with Scyther, and the team goes in.
    cyndaquil = mon(real_data, 155, 16, (TACKLE, LEER, EMBER, 0))
    party = (cyndaquil, party[1])
    assert readiness(policy, party, 'hive') >= 75
    assert policy.boss_training(at(real_data, 'AZALEA_TOWN', party), goal) is None


def test_a_poor_matchup_goes_in_ten_levels_over_the_ace(real_data, walks):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    goal = Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up')
    # A Caterpie with Tackle never matches up, so only the level margin over Scyther's Lv 16 ends the training.
    assert policy.boss_training(at(real_data, 'AZALEA_TOWN', (mon(real_data, 10, 25, (TACKLE, 0, 0, 0)),)), goal)
    assert policy.boss_training(at(real_data, 'AZALEA_TOWN', (mon(real_data, 10, 26, (TACKLE, 0, 0, 0)),)), goal) is None


def test_without_the_cartridge_tables_the_gyms_keep_their_level_rules(real_data, walks):
    from pokesim.gen2.policy import Goal, Policy
    real_data.boss_parties = {}
    policy = Policy(real_data)
    party = (mon(real_data, 155, 13, (TACKLE, 0, 0, 0)),)
    goal = Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up')
    assert policy.boss_training(at(real_data, 'AZALEA_TOWN', party), goal) is None
    assert policy.boss_ace('hive') == policy.BOSS_ACES['hive']


def test_the_ace_levels_come_from_the_cartridge(real_data):
    from pokesim.gen2.policy import Policy
    real_data.boss_parties = {**real_data.boss_parties, 3: [{**BUGSY[2], 'level': 21}]}
    policy = Policy(real_data)
    assert policy.boss_ace('hive') == 21
    # The League's ace is the top one across the Elite Four and Lance.
    assert policy.boss_ace('league_will') == 50


def test_the_first_league_trains_until_the_team_matches_up_or_reaches_the_top_ace(real_data, walks):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(real_data)
    goal = Goal('league_will', 'Challenge Will', 'WILLS_ROOM', 5, 5)
    party = (mon(real_data, 157, 45, (TACKLE, FLAMETHROWER, 0, 0)),)
    training = policy.boss_training(at(real_data, 'INDIGO_PLATEAU_POKECENTER_1F', party, badges=255), goal)
    assert training.map_name == 'VICTORY_ROAD' and 'level 50' in training.label
    # Lance's Lv 50 Dragonite is the top ace on the cartridge, so Lv 50 goes in whatever the score.
    party = (mon(real_data, 157, 50, (TACKLE, FLAMETHROWER, 0, 0)),)
    assert policy.boss_training(at(real_data, 'INDIGO_PLATEAU_POKECENTER_1F', party, badges=255), goal) is None
    # Inside the League nothing turns back.
    party = (mon(real_data, 157, 45, (TACKLE, FLAMETHROWER, 0, 0)),)
    assert policy.boss_training(at(real_data, 'KOGAS_ROOM', party, badges=255), goal) is None


def test_a_field_move_goes_to_another_member_before_the_ace():
    power = lambda move: move in (TACKLE, EMBER)  # noqa: E731
    party = (SimpleNamespace(level=50, egg=False, moves=(TACKLE,)), SimpleNamespace(level=60, egg=False, moves=(HARDEN,)),
             SimpleNamespace(level=50, egg=False, moves=(EMBER,)))
    # The Lv 60 Pokémon knows no attack, so the first Lv 50 fighter is the ace.
    assert ace_slot(party, power) == 0
    assert ace_slot(party[1:2], power) is None


def test_gen1_teaches_cut_to_a_partner_before_the_ace():
    from pokesim.policies.progression import story_goal
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.strategy_data import ITEMS
    from shortcut_fakes import PRESS, Recorder
    from test_events import snap
    from test_strategy import flags, mon as gen1_mon
    policy = StrategicPolicy(7)
    shortcuts = Recorder.on(policy)
    s = snap(party=(gen1_mon(level=30), gen1_mon(level=12)), badges=3, items=((ITEMS['HM01'], 1),),
             event_flags=flags('EVENT_GOT_POKEDEX', 'EVENT_BEAT_CERULEAN_ROCKET_THIEF'))
    policy.goal = story_goal(s)
    assert policy.goal.key == 'teach_cut'
    assert policy._overworld(s, bytearray(65536))[0] == PRESS
    assert (shortcuts.last.kind, shortcuts.last.item, shortcuts.last.target) == ('use_item', ITEMS['HM01'], 1)
