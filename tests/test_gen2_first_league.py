"""The first Gen II League trains the bench first, and a loss to a boss is never progress.

A live run reached the League with a level 56 Typhlosion and a bench at levels 2 to 30, ran out of
PP at Lance and lost for 12 hours. Each run earned experience, levels and trainer wins before the
blackout, so the stall alert never fired.
"""
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection, training
from pokesim.gen2.emulator import Emulator
from pokesim.stalls import LOOP_LIMIT, LoopGuard, StallWatch, boss_attempt
from pokesim.store import Store

from test_loop_guard import Clock, add

TYPHLOSION, LAPRAS, PIDGEY, RATTATA = 157, 131, 16, 19
FLAMETHROWER, EMBER, TACKLE, SURF = 53, 52, 33, 57
DATA = SimpleNamespace(
    species={TYPHLOSION: {'stats': [78, 84, 78, 100, 109, 85], 'growth': 'MEDIUM_SLOW'},
             LAPRAS: {'stats': [130, 85, 80, 60, 85, 95], 'growth': 'SLOW'},
             PIDGEY: {'stats': [40, 45, 40, 56, 35, 35], 'growth': 'MEDIUM_SLOW'},
             RATTATA: {'stats': [30, 56, 35, 72, 25, 35], 'growth': 'MEDIUM_FAST'}},
    moves={FLAMETHROWER: {'power': 95, 'pp': 15}, EMBER: {'power': 40, 'pp': 25},
           TACKLE: {'power': 35, 'pp': 35}, SURF: {'power': 95, 'pp': 15}},
    # The top level of Will, Koga, Bruno, Karen and Lance's parties, as every Gen II cartridge has them.
    league_aces=(42, 44, 46, 47, 50))
PARTNER = 41
LEAGUE = {'WILLS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'}


def mon(species, level, moves=(TACKLE,), dvs=(1, 2, 3, 4), experience=None, power=None):
    return SimpleNamespace(species=species, level=level, hp=10 * level, max_hp=10 * level, egg=False, moves=moves,
                           stats=(10 * level, 2 * level, 2 * level, 2 * level, 2 * level, 2 * level), trainer_id=1,
                           dvs=dvs, experience=level ** 3 if experience is None else experience, power=power)


def at(where, party, count=0):
    return SimpleNamespace(party=party, where=where, hall_of_fame_count=count)


@pytest.fixture
def run(monkeypatch):
    # The training walk itself is tested elsewhere. Here it reports the project it was handed.
    monkeypatch.setattr(training, 'journey', lambda policy, snapshot, mem, Goal, terminal=False:
                        ('train', dict(policy.collection['training'])))
    monkeypatch.setattr(collection, 'party_power', lambda data, mon: mon.power)
    monkeypatch.setattr(collection, 'patrol', lambda policy, snapshot, Goal, label: ('patrol', label))
    return SimpleNamespace(data=DATA, collection={}, completed={}, decisions=0,
                           in_league=lambda snapshot: snapshot.where in LEAGUE)


def bench(lapras=20):
    return (mon(PIDGEY, 5, dvs=(5,)), mon(LAPRAS, lapras, (SURF,), dvs=(6,)), mon(RATTATA, 30, dvs=(7,)))


def test_a_lone_starter_trains_its_bench_before_the_first_league(run):
    party = (mon(TYPHLOSION, 56, (FLAMETHROWER, EMBER), dvs=(9,)),) + bench()
    # Typhlosion alone has 40 attacks, but one strong Pokémon never passes the League check.
    assert not collection.league_ready(run, at('VICTORY_ROAD', party))
    kind, project = collection.first_league(run, at('VICTORY_ROAD', party), None, None)
    assert kind == 'train' and project['identity'] == training.identity(party[2])
    assert project['level_goal'] == PARTNER and project['map'] == collection.FIRST_LEAGUE_MAP
    # A partner at the partner level lets the team go in, and the League project is dropped.
    trained = (party[0], party[1], mon(LAPRAS, PARTNER, (SURF,), dvs=(6,)), party[3])
    assert collection.league_ready(run, at('INDIGO_PLATEAU_POKECENTER_1F', trained))
    assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', trained), None, None) is None
    assert run.collection['training'] is None


def test_a_lone_starter_with_no_sturdy_bench_trains_its_strongest_other_member(run):
    # Neither Pidgey nor Rattata has base HP 90, so the partner is the one with the most Battle Power.
    party = (mon(TYPHLOSION, 56, (FLAMETHROWER, EMBER), dvs=(9,), power=300), mon(PIDGEY, 35, dvs=(5,), power=20),
             mon(RATTATA, 30, dvs=(7,), power=90))
    assert not collection.league_ready(run, at('VICTORY_ROAD', party))
    kind, project = collection.first_league(run, at('VICTORY_ROAD', party), None, None)
    assert kind == 'train' and project['identity'] == training.identity(party[2]) and project['level_goal'] == PARTNER


def test_a_first_league_loss_trains_the_team_before_another_entry(run):
    party = (mon(TYPHLOSION, 56, (FLAMETHROWER, EMBER), dvs=(9,)), mon(LAPRAS, PARTNER, (SURF,), dvs=(6,)),
             mon(PIDGEY, 5, dvs=(5,)))
    assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', party), None, None) is None
    assert collection.first_league(run, at('WILLS_ROOM', party), None, None) is None
    assert run.collection['first_league_entered']
    # Blacking out puts the team back outside without a Hall of Fame entry.
    for _ in range(3):
        kind, project = collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', party), None, None)
        assert kind == 'train' and project['league'] and run.collection['league_lost'] == 97
    # The cheapest step is the level 5 Pidgey to level 10.
    assert project['identity'] == training.identity(party[2]) and project['level_goal'] == 10
    # A level 50 Rattata from the PC makes the team strong enough, but nobody has gained a level yet.
    swapped = party[:2] + (mon(RATTATA, 50, dvs=(8,)),)
    assert collection.league_ready(run, at('INDIGO_PLATEAU_POKECENTER_1F', swapped))
    assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', swapped), None, None)[0] == 'train'
    grown = (mon(TYPHLOSION, 57, (FLAMETHROWER, EMBER), dvs=(9,)),) + swapped[1:]
    assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', grown), None, None) is None
    collection.first_league_over(run)
    assert not {'league_lost', 'league_lost_levels', 'first_league_entered'} & set(run.collection)


def test_a_first_league_loss_with_nothing_to_train_asks_for_help_and_never_goes_back(run, monkeypatch):
    party = (mon(TYPHLOSION, 56, (FLAMETHROWER, EMBER), dvs=(9,)), mon(LAPRAS, PARTNER, (SURF,), dvs=(6,)),
             mon(PIDGEY, 5, dvs=(5,)))
    collection.first_league(run, at('WILLS_ROOM', party), None, None)
    # Every trainee is stood down, so no training walk is found.
    monkeypatch.setattr(training, 'journey', lambda policy, snapshot, mem, Goal, terminal=False: None)
    for _ in range(5):
        assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', party), None, None) == (
            'patrol', collection.LEAGUE_BLOCKED)
    assert collection.league_help(run) == 'Cannot get ready for the League'
    # A level gained on the patrol is growth, and the team may go back once it is ready.
    grown = (mon(TYPHLOSION, 66, (FLAMETHROWER, EMBER), dvs=(9,)),) + party[1:]
    assert collection.first_league(run, at('INDIGO_PLATEAU_POKECENTER_1F', grown), None, None) is None
    assert collection.league_help(run) is None


def test_the_partner_level_comes_from_the_cartridge_league_aces():
    import os
    from pokesim.policies.progression import PARTNER_LEVEL
    from pokesim.policies.team import OPPONENTS
    # Red and Blue's aces are at 56 to 62, so the partner trains to 55, one under Lorelei's Lapras.
    assert PARTNER_LEVEL == 55 == min(level for bit, (_, _, level) in OPPONENTS.items() if bit >= 256) - 1
    assert collection.partner_target(DATA) == PARTNER
    assert collection.partner_target(SimpleNamespace()) == collection.LEAGUE_LEVEL
    for game in ('gold', 'silver', 'crystal'):
        rom = os.path.join(os.path.dirname(os.environ.get('ROM_PATH', '')), f'{game}.gbc')
        if not os.path.exists(rom):
            pytest.skip(f'Set ROM_PATH beside a {game} cartridge')
        aces = collection.league_aces(rom, game)
        assert sorted(aces) == [42, 44, 46, 47, 50]
        assert collection.partner_target(SimpleNamespace(league_aces=aces)) == PARTNER


def test_a_randomized_run_reads_its_own_league_aces(monkeypatch):
    import os
    from pokesim import randomized
    for game in ('gold', 'crystal'):
        rom = os.path.join(os.path.dirname(os.environ.get('ROM_PATH', '')), f'{game}.gbc')
        if not os.path.exists(rom):
            pytest.skip(f'Set ROM_PATH beside a {game} cartridge')
        # A trainer shuffle swaps species but keeps levels, so the aces come from the run's own tables.
        monkeypatch.setenv(randomized.ENV, f'PSR1-{game.upper()}-WST-4242')
        assert randomized.current(rom) is not None
        assert sorted(collection.league_aces(rom, game)) == [42, 44, 46, 47, 50]


def test_a_first_league_attempt_restarted_again_and_again_is_called_off(run):
    assert collection.call_off_league(run) and run.collection['first_league_entered']
    run.collection.clear()
    run.completed['champion'] = 1
    assert not collection.call_off_league(run) and not run.collection


def test_victory_road_has_wild_pokemon_to_train_on():
    import os
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    for game in ('gold', 'silver', 'crystal'):
        entry = GameData.load(directory, game).maps
        mid = next(mid for mid, row in entry.items() if row.get('constant') == collection.FIRST_LEAGUE_MAP)
        assert entry[mid]['environment'] == 'CAVE'


def blackout_emu(stall):
    policy = SimpleNamespace(in_league=lambda snapshot: snapshot.where in LEAGUE, constant=lambda snapshot: snapshot.where,
                             goal=None, BOSSES=frozenset())
    return SimpleNamespace(stall=stall, loop_guard=None, store=None, policy=policy, data=SimpleNamespace(map_ids={}),
                           history={'maps': set(), 'league': 0}, best_progress=(0,) * 6, frame=0,
                           unstick_streak=0, reloads_exhausted=False)


def test_repeated_league_blackouts_trip_the_stall_while_experience_keeps_rising():
    stall = StallWatch(game_minutes=120, real_minutes=0)
    emu = blackout_emu(stall)
    experience, before, alerts = 100000, None, []

    def tick(where, fainted=False, gain=0):
        nonlocal experience, before
        experience += gain
        emu.frame += 3600 * 5
        party = (SimpleNamespace(species=TYPHLOSION, trainer_id=1, dvs=(9,), experience=experience, egg=False),)
        snapshot = SimpleNamespace(valid=True, started=True, where=where, all_fainted=fainted, badges=255,
                                   event_flags=b'\x01', owned={1}, party=party)
        Emulator._watch_boss(emu, before, snapshot)
        Emulator._note_progress(emu, snapshot, 0.0)
        before = snapshot
        alerts.append(stall.check(emu.frame, 1e9))

    tick('INDIGO_PLATEAU_POKECENTER_1F')
    for _ in range(12):
        tick('WILLS_ROOM', gain=5000)
        tick('LANCES_ROOM', gain=5000)
        tick('LANCES_ROOM', fainted=True)
        tick('INDIGO_PLATEAU_POKECENTER_1F')
    assert experience == 220000 and any(alerts)


def test_a_boss_won_keeps_its_progress():
    stall = StallWatch()
    stall.progress(10, 1.0)
    boss_attempt(stall, None, None, True, False)
    stall.progress(20, 2.0)
    boss_attempt(stall, None, None, False, False)
    assert stall.held is None and (stall.frame, stall.since) == (20, 2.0)
    boss_attempt(stall, None, None, True, False)
    stall.progress(30, 3.0)
    boss_attempt(stall, None, None, False, True)
    assert stall.held is None and (stall.frame, stall.since) == (20, 2.0)


def test_trainer_wins_before_a_blackout_do_not_reset_the_reload_count(tmp_path):
    store, clock = Store(tmp_path), Clock()
    try:
        guard, stall = LoopGuard(clock=clock), StallWatch()
        for _ in range(LOOP_LIMIT - 1):
            guard.reloaded('league-entry.state')
        boss_attempt(stall, guard, store, True, False)
        add(store, 'trainer', 'Defeated Elite Four Will')
        add(store, 'level', 'TYPHLOSION grew to level 57')
        boss_attempt(stall, guard, store, False, True)
        guard.reloaded('league-entry.state')
        clock.now += 60
        assert 'reloaded league-entry.state 6 times' in guard.looping(store)
        # A won battle outside any boss attempt is real progress again.
        add(store, 'badge', 'Earned the Rising Badge')
        clock.now += 60
        assert guard.looping(store) is None
    finally:
        store.close()
