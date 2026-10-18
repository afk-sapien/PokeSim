"""A Gen II League attempt that runs out of attacks restarts from before it began instead of hanging.

A live Crystal run took a level 100 Vaporeon and five HM carriers into a postgame League run.
Vaporeon spent its last Hydro Pump and Waterfall before Lance, then kept Growling at his Gyarados
with Rest and Growl PP left, so not even Struggle could end the battle. The battle timeout
reloaded the same save from Karen's room three times and gave up.
"""
from pathlib import Path
from types import SimpleNamespace

from pokesim.gen2 import collection
from pokesim.gen2.emulator import CANNOT_END, LEAGUE_CHECKPOINT, Emulator
from pokesim.gen2.policy import Policy

HYDRO_PUMP, WATERFALL, REST, GROWL, PECK, SURF = 56, 127, 156, 45, 64, 57


def move(name, power, kind, pp):
    return {'name': name, 'effect': 'EFFECT_NORMAL_HIT' if power else 'EFFECT_NONE', 'power': power,
            'type': kind, 'accuracy': 100, 'pp': pp}


DATA = SimpleNamespace(
    species={134: {'types': [21, 21], 'stats': [130, 65, 60, 65, 110, 95]},
             130: {'types': [21, 2], 'stats': [95, 125, 79, 81, 60, 100]},
             84: {'types': [0, 2], 'stats': [35, 85, 45, 75, 35, 35]},
             73: {'types': [21, 3], 'stats': [80, 70, 65, 100, 80, 120]}},
    moves={HYDRO_PUMP: move('Hydro Pump', 120, 21, 5), WATERFALL: move('Waterfall', 80, 21, 15),
           REST: move('Rest', 0, 24, 10), GROWL: move('Growl', 0, 0, 40), PECK: move('Peck', 35, 2, 35),
           SURF: move('Surf', 95, 21, 15)},
    matchups={(21, 21): 0.5}, items={'MAX_ELIXER': 1, 'ELIXER': 2}, map_ids={'INDIGO_PLATEAU_POKECENTER_1F': 7})


def mon(species, level, hp, moves, pp):
    return SimpleNamespace(species=species, level=level, hp=hp, max_hp=max(hp, 1), egg=False, status=0,
                           moves=moves, pp=pp, stats=(hp, 200, 200, 200, 200, 200))


def vaporeon(waterfall=0):
    return mon(134, 100, 359, (HYDRO_PUMP, WATERFALL, REST, GROWL), (0, waterfall, 10, 34))


def lance(party, items=(), in_battle=2):
    return SimpleNamespace(party=party, items=items, in_battle=in_battle, enemy_species=130, enemy_level=44,
                           enemy_hp=150, hall_of_fame_count=215)


def policy():
    fake = SimpleNamespace(data=DATA)
    fake.move_score = lambda mid, mon, snapshot: Policy.move_score(fake, mid, mon, snapshot)
    return fake


def hopeless(snapshot):
    return Policy.hopeless_battle(policy(), snapshot)


def test_a_party_with_nothing_but_rest_and_growl_cannot_end_the_battle():
    fainted = mon(84, 20, 0, (PECK, GROWL, 0, 0), (35, 40, 0, 0))
    assert hopeless(lance((fainted, vaporeon())))
    # One Waterfall left, an Elixir in the bag or a standing partner that can attack still has a way to win.
    assert not hopeless(lance((fainted, vaporeon(waterfall=1))))
    assert not hopeless(lance((vaporeon(),), items=((1, 1),)))
    assert not hopeless(lance((vaporeon(), mon(84, 28, 59, (PECK, 0, 0, 0), (35, 0, 0, 0)))))
    # With no PP at all Struggle attacks, and a wild battle can be run from.
    assert not hopeless(lance((mon(134, 100, 359, (HYDRO_PUMP, REST, 0, 0), (0, 0, 0, 0)),)))
    assert not hopeless(lance((vaporeon(),), in_battle=1))


def guarded(hopeless_now):
    reloads = []
    emu = SimpleNamespace(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                          snapshot=SimpleNamespace(valid=True, started=True, map_name="Lance's Room"), frame=100000,
                          last_reload_frame=0, failure_streak=0, invalid_frame=None, battle_frame=99000,
                          stuck_frame=100000, screen_frame=100000, progress_frame=100000, stuck_ts=0.0,
                          stall=SimpleNamespace(check=lambda frame, now: None),
                          policy=SimpleNamespace(recoveries=0, take_failure=lambda: None, idle=lambda snapshot: False,
                                                 waiting=lambda snapshot: False, recover=lambda level: None,
                                                 hopeless_battle=lambda snapshot: hopeless_now))
    emu._unstick = lambda since, why: reloads.append(why)
    emu._check_stall = lambda: None
    Emulator._check_guards(emu)
    return reloads


def test_a_battle_that_cannot_end_reloads_without_waiting_for_the_timeout():
    assert guarded(True) == [CANNOT_END]
    assert guarded(False) == []


def unstick(why, *, streak=0, in_league=True, entry=True):
    autosave, league = Path('auto-v1-1.state'), Path(LEAGUE_CHECKPOINT)
    loaded = []
    store = SimpleNamespace(autosaves=lambda: [autosave], checkpoint_metadata=lambda path: {'frame': 1, 'settled': True},
                            state_path=lambda name: league if entry and name == LEAGUE_CHECKPOINT else None)
    emu = SimpleNamespace(unstick_streak=streak, snapshot=SimpleNamespace(valid=True, started=True, map_name="Lance's Room"),
                          store=store, frame=100000, reloads=0, last_reload=0, _behind_barrier=lambda metadata: False,
                          policy=SimpleNamespace(recoveries=0, menu=None, collection={}, goal=None, decisions=0,
                                                 in_league=lambda snapshot: in_league),
                          _load_state_file=loaded.append, _tick=lambda frames: None, _reset_watch=lambda: None,
                          _event=lambda event, snapshot: None)
    Emulator._unstick(emu, 100000, why)
    return loaded[0].name


def test_a_lost_league_attempt_restarts_from_the_league_entry_save():
    assert unstick(CANNOT_END) == LEAGUE_CHECKPOINT
    # A battle that only ran long gets one ordinary reload first, as in Red, Blue and Yellow.
    assert unstick('battle never ended').startswith('auto-')
    assert unstick('battle never ended', streak=1) == LEAGUE_CHECKPOINT
    assert unstick(CANNOT_END, in_league=False).startswith('auto-')
    assert unstick(CANNOT_END, entry=False).startswith('auto-')


def test_arriving_at_the_league_pokemon_center_keeps_the_entry_save():
    written = []
    emu = SimpleNamespace(data=DATA, _state_bytes=lambda: b'state', _manifest=lambda: {},
                          store=SimpleNamespace(get=lambda key: None,
                                                write_checkpoint=lambda state, manifest, name: written.append(name)))
    outside, lobby = SimpleNamespace(map=3), SimpleNamespace(map=7)
    Emulator._note_league_entry(emu, outside, lobby)
    assert written == [LEAGUE_CHECKPOINT]
    Emulator._note_league_entry(emu, lobby, lobby)
    Emulator._note_league_entry(emu, None, lobby)
    Emulator._note_league_entry(emu, lobby, outside)
    assert written == [LEAGUE_CHECKPOINT]


def test_a_postgame_league_run_waits_for_a_team_with_attacks_for_every_opponent(monkeypatch):
    monkeypatch.setattr(collection, 'clock_wait', lambda *args: None)
    carrier = mon(73, 39, 123, (SURF, 0, 0, 0), (15, 0, 0, 0))
    run = SimpleNamespace(data=DATA, completed={'champion': 1})
    # Hydro Pump and Waterfall give 20 attacks against 26 opponents, and the level 39 carrier is too weak to count.
    weak = lance((vaporeon(), carrier), in_battle=0)
    assert not collection.league_ready(run, weak) and not collection.postgame_league(run, weak, None, 'day')
    strong = lance((vaporeon(), mon(73, 50, 150, (SURF, 0, 0, 0), (15, 0, 0, 0))), in_battle=0)
    assert collection.league_ready(run, strong) and collection.postgame_league(run, strong, None, 'day')
