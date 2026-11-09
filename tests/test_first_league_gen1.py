"""Red, Blue and Yellow twins of the Gen II first League tests: train the bench, and a boss loss is not progress."""
from types import SimpleNamespace

from pokesim.emulator import Emulator
from pokesim.policies.progression import league_partner, story_goal
from pokesim.stalls import StallWatch, advanced
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import flags, mon

WINS = ('EVENT_BEAT_LORELEIS_ROOM_TRAINER_0', 'EVENT_BEAT_BRUNOS_ROOM_TRAINER_0',
        'EVENT_BEAT_AGATHAS_ROOM_TRAINER_0', 'EVENT_BEAT_LANCE')


def test_a_lone_starter_trains_its_bench_before_the_league():
    charizard = mon(species=180, level=56, max_hp=170, hp=170, attack=110, moves=(53, 0, 0, 0), pp=(15, 0, 0, 0))
    lapras = mon(species=19, level=20, max_hp=70, hp=70, attack=40)
    party = (charizard, mon(level=5), lapras, mon(level=30))
    s = snap(map=MAPS['ROUTE_22_GATE'], x=8, y=6, badges=255, party=party, event_flags=flags('EVENT_GOT_POKEDEX', *WINS))
    assert party[league_partner(s)] is lapras
    assert story_goal(s).key == 'train_league_partner'


def test_a_lone_starter_with_no_sturdy_bench_trains_its_strongest_other_member():
    # No bench member has base HP 90, so the partner is the one with the most Battle Power.
    charizard = mon(species=180, level=56, max_hp=170, hp=170, attack=110, moves=(53, 0, 0, 0), pp=(15, 0, 0, 0))
    strong = mon(level=30, max_hp=80, hp=80, moves=(22, 75, 0, 0), dvs=(15, 15, 15, 15, 15), stat_exp=(9000,) * 5)
    weak = mon(level=32, max_hp=90, hp=90, moves=(45, 0, 0, 0), dvs=(0, 0, 0, 0, 0), stat_exp=(0,) * 5)
    party = (charizard, weak, mon(level=5), strong)
    s = snap(map=MAPS['ROUTE_22_GATE'], x=8, y=6, badges=255, party=party, event_flags=flags('EVENT_GOT_POKEDEX', *WINS))
    assert party[league_partner(s)] is strong
    assert story_goal(s).key == 'train_league_partner'


def test_repeated_league_blackouts_trip_the_stall_while_experience_keeps_rising():
    stall = StallWatch(game_minutes=120, real_minutes=0)
    emu = SimpleNamespace(stall=stall, loop_guard=None, store=None, policy=SimpleNamespace(goal=None))
    experience, before, alerts, frame = 100000, None, [], 0

    def tick(room, fainted=False, gain=0):
        nonlocal experience, before, frame
        experience += gain
        frame += 3600 * 5
        party = (mon(level=56, hp=0 if fainted else 100, max_hp=100, experience=experience),)
        s = snap(map=MAPS[room], party=party, badges=255)
        Emulator._watch_boss(emu, before, s)
        # As Emulator._observe_snapshot does after the boss watch.
        if before is None or advanced(before, s):
            stall.progress(frame, 0.0)
        before = s
        alerts.append(stall.check(frame, 1e9))

    tick('INDIGO_PLATEAU_LOBBY')
    for _ in range(12):
        tick('LORELEIS_ROOM', gain=5000)
        tick('LANCES_ROOM', gain=5000)
        tick('LANCES_ROOM', fainted=True)
        tick('INDIGO_PLATEAU_LOBBY')
    assert experience == 220000 and any(alerts)
