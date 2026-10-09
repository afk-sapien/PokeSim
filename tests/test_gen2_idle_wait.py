"""A Gen II run waiting on the cartridge clock keeps busy, and filler work cannot repeat a failure forever."""
import os
from types import SimpleNamespace

import pytest


@pytest.fixture(scope='module')
def gold():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'gold')


def guard(*, waiting, still=False, stuck_frame=None):
    from pokesim.gen2.emulator import Emulator
    reloads, recoveries = [], []
    frame = 10 ** 6
    policy = SimpleNamespace(recoveries=0, take_failure=lambda: None, idle=lambda snapshot: still,
                             waiting=lambda snapshot: waiting, recover=lambda level: recoveries.append(level))
    emu = SimpleNamespace(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                          snapshot=SimpleNamespace(valid=True, started=True), frame=frame, last_reload_frame=0,
                          policy=policy, failure_streak=0, invalid_frame=None, battle_frame=None,
                          stuck_frame=frame if stuck_frame is None else stuck_frame, screen_frame=frame,
                          progress_frame=0, stuck_ts=0.0, stall=SimpleNamespace(frame=5), waiting=False)
    emu._unstick = lambda since, why: reloads.append((since, why))
    emu._check_stall = lambda: None
    Emulator._check_guards(emu)
    return emu, reloads, recoveries


def test_a_moving_clock_patrol_is_not_reloaded_for_lack_of_progress():
    emu, reloads, recoveries = guard(waiting=True)
    assert not reloads and not recoveries and emu.waiting
    assert emu.progress_frame == emu.frame and emu.stall.frame is None


def test_a_clock_patrol_that_stops_moving_is_still_stuck():
    emu, reloads, _ = guard(waiting=True, stuck_frame=0)
    assert reloads == [(0, 'stuck')]


def test_without_a_patrol_lack_of_progress_still_reloads():
    emu, reloads, _ = guard(waiting=False)
    assert reloads == [(0, 'no progress')] and not emu.waiting


def test_patrol_labels_say_the_run_keeps_training():
    from pokesim.gen2.collection import patrol_label
    assert (patrol_label('Waiting for Tuesday, Thursday or Saturday: the Bug-Catching Contest')
            == 'Train in the grass while waiting for Tuesday, Thursday or Saturday: the Bug-Catching Contest')
    assert (patrol_label('Explore while waiting for new collection opportunities')
            == 'Train in the grass while waiting for new collection opportunities')


def patrol_policy(gold, visits=None, reachable=lambda point: True):
    return SimpleNamespace(data=gold, memory=None,
                           nav=SimpleNamespace(visits=visits or {},
                                               local=lambda snapshot, targets, memory: [0] * 3 if reachable(targets[0]) else None))


def test_clock_patrol_walks_the_grass_instead_of_standing_still(gold, monkeypatch):
    from pokesim.gen2 import collection
    from pokesim.gen2.policy import Goal
    route = gold.map_ids['ROUTE_29']
    grass = [(10, 8, None), (11, 8, None), (13, 8, None), (40, 8, None)]
    monkeypatch.setattr(collection, 'encounter_points', lambda policy, snapshot, mid, method: grass)
    away = SimpleNamespace(map=gold.map_ids['NEW_BARK_TOWN'], x=3, y=3)
    goal = collection.patrol(patrol_policy(gold), away, Goal, 'Waiting for Friday: Lapras surfaces in Union Cave')
    assert (goal.key, goal.map_name, (goal.x, goal.y)) == ('collection_idle', 'ROUTE_29', collection.PATROL_HOME)
    assert goal.label == 'Train in the grass while waiting for Friday: Lapras surfaces in Union Cave'
    here = SimpleNamespace(map=route, x=11, y=8)
    goal = collection.patrol(patrol_policy(gold, {(route, 10, 8): 3}), here, Goal, 'Waiting for night')
    assert (goal.x, goal.y) == (13, 8)
    goal = collection.patrol(patrol_policy(gold, reachable=lambda point: point == (40, 8)), here, Goal, 'Waiting')
    assert (goal.x, goal.y) == (40, 8)


def test_the_patrol_counts_as_waiting_but_only_the_wait_tile_as_idle(gold):
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(gold, seed=1, starter='cyndaquil')
    route = gold.map_ids['ROUTE_29']
    policy.goal = Goal('collection_idle', 'Train in the grass while waiting for night', 'ROUTE_29', 20, 9)
    walking = SimpleNamespace(map=route, x=19, y=9, in_battle=0)
    assert policy.waiting(walking) and not policy.idle(walking)
    assert policy.waiting(SimpleNamespace(map=route, x=19, y=9, in_battle=1))
    assert policy.idle(SimpleNamespace(map=route, x=20, y=9, in_battle=0))
    assert not policy.waiting(SimpleNamespace(map=gold.map_ids['NEW_BARK_TOWN'], x=1, y=1, in_battle=0))
    policy.goal = Goal('collection_hunt', 'Hunting', 'ROUTE_29', 20, 9)
    assert not policy.waiting(walking)


def trainee(gold, species, level, *, box=None, position=0, held_item=0, trainer_id=1):
    from pokesim.gen2.training import experience_at
    return SimpleNamespace(species=species, level=level, egg=False, box=box, position=position, trainer_id=trainer_id,
                           dvs=(level % 16,) * 5, held_item=held_item, friendship=0, stat_exp=(0,) * 5, name='MON',
                           experience=experience_at(level, gold.species[species]['growth']))


def test_sealed_storage_trains_only_the_party_and_never_walks_to_the_pc(gold, monkeypatch):
    from pokesim.gen2 import training
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(gold, seed=1, starter='cyndaquil')
    policy.memory = None
    share = gold.items['EXP_SHARE']
    party = (trainee(gold, 154, 100),) + tuple(trainee(gold, 18, 50 + slot, position=slot) for slot in range(1, 6))
    stored = (trainee(gold, 61, 99, box=12, position=3, held_item=share),)
    snapshot = SimpleNamespace(party=party, stored=stored, items=(), owned={154, 18, 61, 62, 186}, box_counts=(20,) * 14,
                               map=gold.map_ids['ROUTE_29'], x=1, y=1)
    policy.collection.update(training=None, prerequisites=[])
    monkeypatch.setattr(training, 'projects', lambda *args, **kwargs: [])
    mem = SimpleNamespace(byte=lambda name: 1)
    policy.no_room = lambda snapshot: True
    # The Poliwhirl closest to level 100 is boxed, and the Exp. Share it holds cannot come out either.
    assert training.journey(policy, snapshot, mem, Goal, terminal=True) is None
    assert policy.collection['training']['identity'] != training.identity(stored[0])
    assert not policy.collection.get('stood_down')
    policy.collection['training'] = None
    policy.no_room = lambda snapshot: False
    goal = training.journey(policy, snapshot, mem, Goal, terminal=True)
    assert goal.key == 'collection_train_pc'


def test_a_losing_tower_cap_backs_off_and_other_caps_are_tried():
    from pokesim.gen2 import tower
    policy = SimpleNamespace(decisions=1000, collection={})
    tower.record_result(policy, 100, 0)
    assert tower.resting_caps(policy) == {100}
    first = policy.collection['tower_failed']['100']['until']
    tower.record_result(policy, 100, 3)
    assert policy.collection['tower_failed']['100']['until'] - 1000 == 2 * (first - 1000)
    policy.decisions = policy.collection['tower_failed']['100']['until']
    assert tower.resting_caps(policy) == set()
    tower.record_result(policy, 100, 7)
    assert '100' not in policy.collection['tower_failed']

    def mon(species, level, strength):
        return SimpleNamespace(species=species, level=level, stats=(strength,) * 6, egg=False)
    snapshot = SimpleNamespace(party=(mon(25, 100, 400), mon(26, 100, 420), mon(81, 100, 380)),
                               stored=(mon(16, 50, 150), mon(17, 50, 160), mon(18, 50, 170)))
    assert tower.select_team(snapshot)[0] == 100
    cap, team = tower.select_team(snapshot, {100})
    assert cap == 50 and {m.species for m in team} == {16, 17, 18}
    assert tower.select_team(snapshot, set(range(10, 101, 10))) is None


def test_a_finished_tower_challenge_records_its_shortfall(gold, monkeypatch):
    crystal = SimpleNamespace(**{**vars(gold), 'game': 'crystal'})
    from pokesim.gen2 import tower
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(gold, seed=1, starter='cyndaquil')
    policy.data = crystal
    policy.memory = None
    policy.collection['tower'] = {'entered': True, 'returning': False, 'cap': 100, 'original': []}
    values = {'sNrOfBeatenBattleTowerTrainers': 1, 'wBattleResult': 1}
    monkeypatch.setattr(tower, 'Memory', lambda *args: SimpleNamespace(byte=lambda name: values[name]))
    monkeypatch.setattr(tower, 'assemble', lambda *args: None)
    snapshot = SimpleNamespace(map=gold.map_ids['ROUTE_29'], party=(), frame=100)
    snapshot.map = next(mid for mid, entry in gold.maps.items() if entry['constant'] == 'ROUTE_29')
    crystal.maps = {**gold.maps, snapshot.map: {**gold.maps[snapshot.map], 'constant': 'BATTLE_TOWER_1F'}}
    assert tower.journey(policy, snapshot, Goal) is None
    assert policy.collection['tower_result'] == {'wins': 0, 'level': 100}
    assert tower.resting_caps(policy) == {100}
