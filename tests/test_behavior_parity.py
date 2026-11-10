"""Gen I and Gen II face the same scripted situation and must do the same thing.

test_generation_parity.py checks that both generations fill the same keys. These tests check what
the planner does. Each case runs Red, Blue or Yellow beside Gold, Silver or Crystal, through the
fast unit fakes the generation tests already use, and compares the outcome. A case that differs on
main is a strict xfail that names the goal system v2 PR fixing it (docs/design/goal-system.md,
section 13), so the fix shows up as an unexpected pass.
"""
import os
import sqlite3
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim import rewards
from pokesim.policies.collection import Collection
from pokesim.store import Store
from pokesim.strategy_data import MAPS
from test_collection import sid, state
from test_level100_priority import individual, postgame
from test_strategy import mon

PAIRS = [('red', 'gold'), ('blue', 'silver'), ('yellow', 'crystal')]
GEN1_ROMS = {'red': 'ea9bcae617fdf159b045185467ae58b2e4a48b9a', 'blue': 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2',
             'yellow': 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'}
PR6 = 'goal system v2 PR 6: runtime/supervision.py with one ladder'


def even(value):
    """DVs whose HP DV is 0, so a higher ``value`` is a rarer copy in both generations."""
    return (0,) + (value,) * 4


def progress_rows(store, kind):
    """The progress_events rows of ``kind``."""
    return store.db.execute('SELECT species FROM progress_events WHERE kind=?', (kind,)).fetchall()


@pytest.fixture(params=['gold', 'silver', 'crystal'])
def gen2_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


# 1. A full box with a gift due.

def gen1_gift(version, boxes):
    # One reserve may be deposited, so only the boxes decide whether there is room.
    party = (mon(level=100),) + tuple(mon(level=55, moves=(move, 0, 0, 0)) for move in (15, 19, 57, 70)) + (mon(level=30),)
    s = state(party=party, map=MAPS['CERULEAN_CITY'], box_counts=boxes, active_box=0,
              boxed_pokemon=((1, 5),) * boxes[0])
    c = Collection()
    c.version = version
    goal = c.goal(s, {'method': 'gift', 'species': sid(106), 'map': MAPS['FIGHTING_DOJO']})
    return goal is not None


def gen2_gift(game, boxes):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.quests import gifts
    storage = Goal('storage', 'PC', 'CHERRYGROVE_POKECENTER_1F', 9, 2, 'up')
    people = []
    run = SimpleNamespace(storage_goal=lambda snap: storage, data=SimpleNamespace(game=game), people=people,
                          person=lambda snap, key, *rest: people.append(key) or Goal(key, key, 'X', 0, 0))
    view = SimpleNamespace(party=[SimpleNamespace(egg=False)] * 6, box_counts=boxes, active_box=0,
                           event=lambda flag: flag == 'EVENT_GOT_MASTER_BALL_FROM_ELM')
    return gifts(run, view, Goal) is not None


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_an_in_game_gift_with_a_full_party_waits_for_a_full_pc_and_makes_room_otherwise(gen1, gen2):
    full1, full2 = (20,) * 12, (20,) * 14
    room1, room2 = (20, 19) + full1[2:], (20, 19) + full2[2:]
    assert (gen1_gift(gen1, full1), gen2_gift(gen2, full2)) == (False, False)
    assert (gen1_gift(gen1, room1), gen2_gift(gen2, room2)) == (True, True)


def test_a_league_reward_with_every_box_full_is_declined_and_stays_owed(tmp_path, monkeypatch):
    from pokesim import config, ram
    from pokesim.gen2 import rewards as gen2_rewards
    from pokesim.runtime.reward_delivery import PENDING, deliver
    from test_events import snap
    outcomes = []
    for generation in (1, 2):
        store = Store(tmp_path / str(generation))
        try:
            rewards.earn(store, 1)
            if generation == 1:
                monkeypatch.setattr(ram, 'read_snapshot', lambda *_: snap(box_counts=(20,) * 12))
                emu = SimpleNamespace(store=store, paused=False, manual_mode=False,
                                      pb=SimpleNamespace(memory=None), frame=100)
                result = deliver(emu, league_rewards=True)
            else:
                before = SimpleNamespace(valid=True, started=True, in_battle=False, tiles=[''] * 18,
                                         box_counts=(20,) * 14, hall_of_fame_count=1, owned=frozenset())
                monkeypatch.setattr(config, 'LEAGUE_REWARDS', True, raising=False)
                monkeypatch.setattr(config, 'MEW_EVENT', False, raising=False)
                monkeypatch.setattr(gen2_rewards, 'read_snapshot', lambda *_: before)
                monkeypatch.setattr(gen2_rewards, 'Memory', lambda *_: SimpleNamespace(byte=lambda _: 0))
                emu = SimpleNamespace(store=store, paused=False, manual_mode=False, preparation=None,
                                      policy=SimpleNamespace(menu=None), pb=SimpleNamespace(memory='live'),
                                      data=None, frame=100)
                result = gen2_rewards.deliver(emu)
            ledger = rewards.ledger(store.db)
            outcomes.append((result, ledger['earned'], ledger['delivered'], store.get(PENDING), store.events()))
        finally:
            store.close()
    assert outcomes[0] == outcomes[1] == (None, 1, 0, None, [])


# 2. A stall with no progress.

def save():
    return SimpleNamespace(name='auto-1.state', stat=lambda: SimpleNamespace(st_mtime=0))


def step(title):
    return 'give up' if title.startswith('Gave up') else 'report' if title.startswith('Stuck?') else title


def gen1_ladder():
    from pokesim.emulator import Emulator
    steps = []
    policy = SimpleNamespace(collection=SimpleNamespace(project={'method': 'grass'}, abandon=lambda reason: True),
                             goal=SimpleNamespace(title='Catch a better Pidgey'), on_restore=lambda: None)
    emu = SimpleNamespace(policy=policy, unstick_streak=0, reloads=0, input_epoch=0, loop_guard=None,
                          snapshot=SimpleNamespace(started=True, map_name='Route 1', map=12, in_battle=0, valid=True),
                          store=SimpleNamespace(autosaves=lambda: [save()], state_path=lambda key: None),
                          _restore_first_valid=lambda candidates: steps.append('reload'), _tick=lambda frames: None,
                          _handle_events=lambda events, snap: steps.extend(step(e.title) for e in events))
    for _ in range(20):
        Emulator._unstick(emu, time.time(), 'no progress')
        if 'give up' in steps:
            break
    return steps


def gen2_ladder():
    from pokesim.gen2.emulator import Emulator
    from pokesim.gen2.policy import Goal
    steps = []
    policy = SimpleNamespace(collection={}, decisions=100, menu=None, completed={}, pin=None, recoveries=0,
                             ladder_rung='quality', goal=Goal('collection_quality', 'Catch a better Pidgey', 'X', 0, 0),
                             in_league=lambda snap: False, on_restore=lambda: None)
    emu = SimpleNamespace(policy=policy, unstick_streak=0, reloads=0, loop_guard=None, frame=10 ** 6,
                          snapshot=SimpleNamespace(started=True, valid=True, map_name='Route 1', in_battle=0,
                                                   hall_of_fame_count=0),
                          store=SimpleNamespace(autosaves=lambda: [save()], checkpoint_metadata=lambda path: {'frame': 0},
                                                get=lambda key: None, state_path=lambda key: None),
                          _behind_barrier=lambda metadata: False, _reset_watch=lambda: None, _tick=lambda frames: None,
                          _load_state_file=lambda path: steps.append('reload'),
                          _event=lambda event, snap: steps.append(step(event.title)))
    for _ in range(20):
        Emulator._unstick(emu, emu.frame, 'no progress')
        if 'give up' in steps:
            break
    return steps


def test_both_stall_ladders_reload_twelve_times_then_give_up():
    for steps in (gen1_ladder(), gen2_ladder()):
        assert steps.count('reload') == 12 and steps[-1] == 'give up'


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason=f'{PR6}. Only Gen II reports the stall after its second reload')
def test_both_stall_ladders_climb_the_same_rungs_in_the_same_order():
    assert gen1_ladder() == gen2_ladder()


# 3. A marathon checkpoint.

def gen1_checkpoint():
    from test_marathon import checkpoint, race
    c = race()
    c.observe(checkpoint(0, 0))
    assert [event.title for event in c.take_activity_events()] == ['The Kanto Marathon is on!']
    c.observe(checkpoint(1, 60))
    return c.project['checkpoint'] - 1, c.take_activity_events()


def gen2_checkpoint(data, monkeypatch):
    from pokesim.gen2 import marathon, postgame
    from test_gen2_marathon import at, run_course, runner_policy, start
    points = marathon.course(data).points
    policy = runner_policy(data)
    start(policy, at(points[0], 1000), monkeypatch)
    frame = run_course(policy, points[:1], 1000)
    assert [event['title'] for event in marathon.take_events(policy)] == ['The Johto Marathon is on!']
    run_course(policy, points[1:2], frame)
    return postgame.state(policy)['activity']['gains']['checkpoints'], marathon.take_events(policy)


def test_both_marathons_count_the_first_checkpoint(gen2_data, monkeypatch):
    assert gen1_checkpoint()[0] == gen2_checkpoint(gen2_data, monkeypatch)[0] == 1


def test_both_marathons_write_a_progress_row_for_a_checkpoint(gen2_data, monkeypatch):
    _, first = gen1_checkpoint()
    _, second = gen2_checkpoint(gen2_data, monkeypatch)
    assert len(first) == len(second) == 1


# 4. A duplicate catch.

def gen1_catches(tmp_path, version):
    from pokesim.catches import CatchTracker
    store = Store(tmp_path / 'gen1')
    tracker = CatchTracker(store, GEN1_ROMS[version], fresh=True)
    for trainer in (1, 2):
        memory = bytearray(0x10000)
        memory[0xd11c] = sid(16)
        memory[0xd057] = 1
        memory[0xd359:0xd35b] = trainer.to_bytes(2, 'big')
        tracker.completed(SimpleNamespace(memory=memory))
    return store


def gen2_catches(tmp_path, game):
    from pokesim.gen2 import activity
    from pokesim.gen2.tracking import Tracker
    from test_gen2_activity import Emulator, fake_data
    store, data = Store(tmp_path / 'gen2'), replace_game(fake_data(), game)
    activity.start(store, fresh=True)
    tracker = Tracker(store, data, fresh=True)
    for dvs in (0x11, 0x22):
        pb = Emulator()
        for name, value in (('wWildMon', 16), ('wBattleMode', 1), ('wBattleType', 0), ('wEnemyMonDVs', dvs)):
            pb.memory.put(name, value)
        tracker.captured(pb)
    return store


def replace_game(data, game):
    data.game = game
    return data


def receipts(store):
    return [dex for (dex,) in store.db.execute('SELECT dex FROM capture_receipts ORDER BY dex')]


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_record_a_receipt_for_a_duplicate_catch(tmp_path, gen1, gen2):
    first, second = gen1_catches(tmp_path, gen1), gen2_catches(tmp_path, gen2)
    try:
        assert receipts(first) == receipts(second) == [16, 16]
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_write_a_catch_row_for_a_duplicate_catch(tmp_path, gen1, gen2):
    first, second = gen1_catches(tmp_path, gen1), gen2_catches(tmp_path, gen2)
    try:
        assert len(progress_rows(first, 'catch')) == len(progress_rows(second, 'catch')) == 2
    finally:
        first.close()
        second.close()


# 5. A hunt with a threshold.

FOUND = (12, 6, 3)  # a rarer copy, an equal one and a worse one than the held Pidgey with even(6)


def gen1_hunt(version):
    c = Collection()
    c.version = version
    c.project = {'species': sid(16), 'method': 'grass', 'repeat': True, 'dv_hunt': True, 'map': 51}
    held = replace(individual(20, 2, 16), dvs=even(6))
    s = postgame(party=(individual(100, 1), held), in_battle=1)
    return [c.repeat_target(sid(16), 51, s, even(value)) == sid(16) for value in FOUND]


def gen2_hunt(game, monkeypatch):
    from pokesim.gen2.postgame import hunt_catch
    from test_gen2_release import mon as stored, snapshot
    monkeypatch.setattr('pokecore.gen2.breeding.breeding_stock', lambda data, species: set())
    policy = SimpleNamespace(data=SimpleNamespace(species={16: {'name': 'Pidgey'}}, game=game), demand={},
                             collection={'postgame': {'activity': {'kind': 'quality', 'species': 16}}},
                             trade_preferences=lambda: {})
    view = snapshot([stored(16, dvs=even(6))], boxes=(10,) * 14)
    return [bool(hunt_catch(policy, view, 16, bytes([value << 4 | value] * 2))) for value in FOUND]


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_hunts_catch_only_a_copy_rarer_than_the_one_held(gen1, gen2, monkeypatch):
    assert gen1_hunt(gen1) == gen2_hunt(gen2, monkeypatch) == [True, False, False]


# 6. A help request polled many times, then a loop and a second stall.

def test_both_write_one_help_row_per_request(tmp_path):
    from test_stall_truth import gen1_game, gen1_help, gen2_game, gen2_help, help_story
    gen1 = help_story(tmp_path / 'gen1', gen1_game, gen1_help)
    assert [row['request'] for row in gen1] == ['stall', 'loop', 'stall']
    assert help_story(tmp_path / 'gen2', gen2_game, gen2_help) == gen1
