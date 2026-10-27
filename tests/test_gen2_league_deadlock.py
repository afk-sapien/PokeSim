"""A Gen II League attempt that runs out of attacks restarts from before it began instead of hanging.

A live Crystal run took a level 100 Vaporeon and five HM carriers into a postgame League run.
Vaporeon spent its last Hydro Pump and Waterfall before Lance, then kept Growling at his Gyarados
with Rest and Growl PP left, so not even Struggle could end the battle. The battle timeout
reloaded the same save from Karen's room three times and gave up.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.gen2 import collection
from pokesim.gen2 import policy as policy_module
from pokesim.gen2.emulator import CANNOT_END, LEAGUE_CHECKPOINT, LEAGUE_RESTARTS, Emulator
from pokesim.gen2.policy import SUBSTATUS_TRANSFORMED, Policy, transformed

HYDRO_PUMP, WATERFALL, REST, GROWL, PECK, SURF, TRANSFORM = 56, 127, 156, 45, 64, 57, 144
DITTO, GYARADOS = 132, 130


def move(name, power, kind, pp):
    return {'name': name, 'effect': 'EFFECT_NORMAL_HIT' if power else 'EFFECT_NONE', 'power': power,
            'type': kind, 'accuracy': 100, 'pp': pp}


DATA = SimpleNamespace(
    species={134: {'types': [21, 21], 'stats': [130, 65, 60, 65, 110, 95]},
             130: {'types': [21, 2], 'stats': [95, 125, 79, 81, 60, 100]},
             84: {'types': [0, 2], 'stats': [35, 85, 45, 75, 35, 35]},
             73: {'types': [21, 3], 'stats': [80, 70, 65, 100, 80, 120]},
             132: {'types': [0, 0], 'stats': [48, 48, 48, 48, 48, 48]}},
    moves={HYDRO_PUMP: move('Hydro Pump', 120, 21, 5), WATERFALL: move('Waterfall', 80, 21, 15),
           REST: move('Rest', 0, 24, 10), GROWL: move('Growl', 0, 0, 40), PECK: move('Peck', 35, 2, 35),
           SURF: move('Surf', 95, 21, 15), TRANSFORM: dict(move('Transform', 0, 0, 10), effect='EFFECT_TRANSFORM')},
    matchups={(21, 21): 0.5}, items={'MAX_ELIXER': 1, 'ELIXER': 2}, map_ids={'INDIGO_PLATEAU_POKECENTER_1F': 7, 'ROUTE_23': 3})


@pytest.fixture(scope='module', params=['synthetic', 'gold', 'silver', 'crystal'])
def data(request):
    """The moves, species and maps above, then each cartridge's own."""
    if request.param == 'synthetic':
        return DATA
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def mon(species, level, hp, moves, pp):
    return SimpleNamespace(species=species, level=level, hp=hp, max_hp=max(hp, 1), egg=False, status=0,
                           moves=moves, pp=pp, stats=(hp, 200, 200, 200, 200, 200))


def vaporeon(waterfall=0):
    return mon(134, 100, 359, (HYDRO_PUMP, WATERFALL, REST, GROWL), (0, waterfall, 10, 34))


def lance(party, items=(), in_battle=2):
    return SimpleNamespace(party=party, items=items, in_battle=in_battle, enemy_species=130, enemy_level=44,
                           enemy_hp=150, hall_of_fame_count=215)


def policy(data):
    fake = SimpleNamespace(data=data)
    fake.move_score = lambda mid, mon, snapshot: Policy.move_score(fake, mid, mon, snapshot)
    return fake


def test_a_party_with_nothing_but_rest_and_growl_cannot_end_the_battle(data):
    def hopeless(snapshot):
        return Policy.hopeless_battle(policy(data), snapshot)
    fainted = mon(84, 20, 0, (PECK, GROWL, 0, 0), (35, 40, 0, 0))
    assert hopeless(lance((fainted, vaporeon())))
    # One Waterfall left, an Elixir in the bag or a standing partner that can attack still has a way to win.
    assert not hopeless(lance((fainted, vaporeon(waterfall=1))))
    assert not hopeless(lance((vaporeon(),), items=((data.items['MAX_ELIXER'], 1),)))
    assert not hopeless(lance((vaporeon(),), items=((data.items['ELIXER'], 1),)))
    assert not hopeless(lance((vaporeon(), mon(84, 28, 59, (PECK, 0, 0, 0), (35, 0, 0, 0)))))
    # With no PP at all Struggle attacks, and a wild battle can be run from.
    assert not hopeless(lance((mon(134, 100, 359, (HYDRO_PUMP, REST, 0, 0), (0, 0, 0, 0)),)))
    assert not hopeless(lance((vaporeon(),), in_battle=1))


class BattleMemory:
    """The few battle bytes the policy reads, with the active Pokémon optionally Transformed."""

    def __init__(self, active=1, transformed=False, moves=(SURF, 0, 0, 0), pp=(5, 0, 0, 0)):
        self.bytes = {'wCurBattleMon': active, 'wPlayerSubStatus5': SUBSTATUS_TRANSFORMED if transformed else 0,
                      'wBattleMonSpecies': GYARADOS}
        self.lists = {'wBattleMonMoves': moves, 'wBattleMonPP': pp}

    def byte(self, name):
        return self.bytes[name]

    def word(self, name):
        return 150

    def read(self, name, count):
        return self.lists[name][:count]


def ditto(pp=10):
    from pokecore.gen2.ram import Mon
    return Mon(DITTO, 'DITTO', 100, 285, 285, 0, 0, (TRANSFORM, 0, 0, 0), (pp, 0, 0, 0), (10, 0, 0, 0),
               (285, 200, 200, 200, 200, 200), 1000000, (15, 15, 15, 15), (0,) * 5, 1, 70)


def test_a_ditto_left_standing_can_still_transform_and_end_the_battle(data, monkeypatch):
    # A live Crystal run lost everyone but a level 100 Ditto to Koga's Muk and Crobat. Its only move
    # is Transform, which has no power, so the guards reloaded the League entry fourteen times in half
    # an hour before Ditto ever took the foe's moves.
    fake = policy(data)
    fainted = mon(84, 20, 0, (PECK, GROWL, 0, 0), (35, 40, 0, 0))
    fake.memory = None
    assert not Policy.hopeless_battle(fake, lance((fainted, ditto())))
    # Once Transformed it has five PP for each copied move, so Struggle is a few turns away even
    # after its copied attack runs out. Played on, it beat Koga's Crobat this way.
    fake.memory = object()
    monkeypatch.setattr(policy_module, 'Memory', lambda memory, data: BattleMemory(transformed=True, moves=(REST, 0, 0, 0)))
    assert not Policy.hopeless_battle(fake, lance((fainted, vaporeon())))
    monkeypatch.setattr(policy_module, 'Memory', lambda memory, data: BattleMemory())
    assert Policy.hopeless_battle(fake, lance((fainted, vaporeon())))


def test_a_transformed_battler_takes_the_foes_species_moves_and_pp():
    own = ditto()
    assert transformed(BattleMemory(), own) is own and transformed(None, own) is own
    fighting = transformed(BattleMemory(transformed=True, pp=(0xC5, 0, 0, 0)), own)
    assert (fighting.species, fighting.moves, fighting.pp) == (GYARADOS, (SURF, 0, 0, 0), (5, 0, 0, 0))
    assert fighting.stats == (own.stats[0], 150, 150, 150, 150, 150) and fighting.level == 100


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


def test_a_league_attempt_restarted_again_and_again_is_called_off(monkeypatch):
    # The live Crystal run restarted the same attempt from the entry save fourteen times. Experience
    # earned before each loss counted as progress, so the reload streak never reached its cap.
    league = Path(LEAGUE_CHECKPOINT)
    calls = []
    store = SimpleNamespace(autosaves=lambda: [Path('auto-v1-1.state')], checkpoint_metadata=lambda path: {'frame': 1, 'settled': True},
                            state_path=lambda name: league if name == LEAGUE_CHECKPOINT else None)
    run = SimpleNamespace(recoveries=0, menu=None, collection={}, goal=None, decisions=0, in_league=lambda snapshot: True)
    emu = SimpleNamespace(unstick_streak=0, store=store, frame=100000, reloads=0, last_reload=0,
                          _behind_barrier=lambda metadata: False, policy=run,
                          _tick=lambda frames: None, _reset_watch=lambda: None, _event=lambda event, snapshot: None)

    def restart(wins=231):
        # Each reload restores the entry save's policy, which forgets the attempt.
        emu.snapshot = SimpleNamespace(valid=True, started=True, map_name="Koga's Room", hall_of_fame_count=wins)
        emu.unstick_streak = 0
        emu._load_state_file = lambda path: (calls.append(path.name), run.collection.clear(), run.collection.update(league_loop=wins + 1))
        Emulator._unstick(emu, 100000, CANNOT_END)
        return 'league_entered' in run.collection

    assert [restart() for _ in range(LEAGUE_RESTARTS)] == [False] * (LEAGUE_RESTARTS - 1) + [True]
    assert calls == [LEAGUE_CHECKPOINT] * LEAGUE_RESTARTS
    # Outside the League the loop then reads it as a lost run, and the team trains before the next.
    monkeypatch.setattr(collection, 'league_funding', lambda policy, snapshot, Goal, again=False: 'challenge')
    run.in_league = lambda snapshot: False
    party = (mon(73, 53, 200, (SURF, 0, 0, 0), (15, 0, 0, 0)),)
    lobby = SimpleNamespace(party=party, where='INDIGO_PLATEAU_POKECENTER_1F', hall_of_fame_count=231)
    assert collection.league_loop(run, lobby, None) is None and run.collection['league_lost'] == 53
    # A new Hall of Fame entry starts the count again.
    run.in_league = lambda snapshot: True
    assert not restart(232) and not restart(232)


def test_a_lost_league_attempt_restarts_from_the_league_entry_save():
    assert unstick(CANNOT_END) == LEAGUE_CHECKPOINT
    # A battle that only ran long gets one ordinary reload first, as in Red, Blue and Yellow.
    assert unstick('battle never ended').startswith('auto-')
    assert unstick('battle never ended', streak=1) == LEAGUE_CHECKPOINT
    assert unstick(CANNOT_END, in_league=False).startswith('auto-')
    assert unstick(CANNOT_END, entry=False).startswith('auto-')


def test_arriving_at_the_league_pokemon_center_keeps_the_entry_save(data):
    written = []
    emu = SimpleNamespace(data=data, _state_bytes=lambda: b'state', _manifest=lambda: {},
                          store=SimpleNamespace(get=lambda key: None,
                                                write_checkpoint=lambda state, manifest, name: written.append(name)))
    entry = data.map_ids['INDIGO_PLATEAU_POKECENTER_1F']
    outside, lobby = SimpleNamespace(map=data.map_ids['ROUTE_23']), SimpleNamespace(map=entry)
    Emulator._note_league_entry(emu, outside, lobby)
    assert written == [LEAGUE_CHECKPOINT]
    Emulator._note_league_entry(emu, lobby, lobby)
    Emulator._note_league_entry(emu, None, lobby)
    Emulator._note_league_entry(emu, lobby, outside)
    assert written == [LEAGUE_CHECKPOINT]


def test_a_postgame_league_run_waits_for_a_team_with_attacks_for_every_opponent(data, monkeypatch):
    monkeypatch.setattr(collection, 'clock_wait', lambda *args: None)
    carrier = mon(73, 39, 123, (SURF, 0, 0, 0), (15, 0, 0, 0))
    run = SimpleNamespace(data=data, completed={'champion': 1})
    # Hydro Pump and Waterfall give 20 attacks against 26 opponents, and the level 39 carrier is too weak to count.
    weak = lance((vaporeon(), carrier), in_battle=0)
    assert not collection.league_ready(run, weak) and not collection.postgame_league(run, weak, None, 'day')
    strong = lance((vaporeon(), mon(73, 50, 150, (SURF, 0, 0, 0), (15, 0, 0, 0))), in_battle=0)
    assert collection.league_ready(run, strong) and collection.postgame_league(run, strong, None, 'day')


def test_a_postgame_league_run_lost_at_lance_waits_for_the_team_to_grow(monkeypatch):
    # A live Crystal run took one level 71 Poliwhirl and its trainees to Lance every twenty minutes
    # and blacked out each time, since one Pokémon with enough attacks passed the readiness check.
    monkeypatch.setattr(collection, 'league_funding', lambda policy, snapshot, Goal, again=False: 'challenge')
    league = {'WILLS_ROOM'}
    run = SimpleNamespace(data=DATA, completed={'champion': 1}, collection={'league_loop': 216},
                          in_league=lambda snapshot: snapshot.where in league)
    party = (mon(73, 71, 200, (SURF, 0, 0, 0), (15, 0, 0, 0)), mon(73, 71, 200, (SURF, 0, 0, 0), (15, 0, 0, 0)))

    def at(where, party=party, count=215):
        return SimpleNamespace(party=party, where=where, hall_of_fame_count=count)

    assert collection.league_ready(run, at('INDIGO_PLATEAU_POKECENTER_1F'))
    assert collection.league_loop(run, at('INDIGO_PLATEAU_POKECENTER_1F'), None) == 'challenge'
    assert collection.league_loop(run, at('WILLS_ROOM'), None) == 'challenge'
    # Blacking out leaves the League without a Hall of Fame entry, which ends the run.
    assert collection.league_loop(run, at('INDIGO_PLATEAU_POKECENTER_1F'), None) is None
    assert 'league_loop' not in run.collection and run.collection['league_lost'] == 142
    assert not collection.league_ready(run, at('ROUTE_29'))
    grown = party + (mon(73, 45, 150, (SURF, 0, 0, 0), (15, 0, 0, 0)),)
    assert collection.league_ready(run, at('ROUTE_29', grown))
    # A run that reaches the Hall of Fame clears the memory of the loss.
    run.collection.update(league_loop=216, league_entered=True)
    assert collection.league_loop(run, at('HALL_OF_FAME', grown, 216), None) is None
    assert 'league_lost' not in run.collection and collection.league_ready(run, at('ROUTE_29'))


def test_a_team_at_level_100_that_lost_the_league_may_try_again():
    # A full team cannot gain 10 more levels, so the wait after a loss must not stop its League runs for good.
    run = SimpleNamespace(data=DATA, completed={'champion': 1}, collection={'league_lost': 600},
                          in_league=lambda snapshot: False)
    party = tuple(mon(73, 100, 300, (SURF, 0, 0, 0), (15, 0, 0, 0)) for _ in range(6))
    assert collection.league_ready(run, SimpleNamespace(party=party, where='ROUTE_29', hall_of_fame_count=215))
