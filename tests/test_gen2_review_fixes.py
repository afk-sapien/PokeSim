"""Pre-beta review fixes: a restarted run watches itself again, and broken saves never end a run."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.stalls import StallWatch
from pokesim.store import Store


@pytest.fixture
def gen2_emu(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'Policy', lambda *args, **kwargs: SimpleNamespace(trade_preferences=None))
    emu = module.Emulator.__new__(module.Emulator)
    emu.store = Store(tmp_path)
    emu.data = None
    emu.pb = Mock()
    emu._boot = Mock(return_value=Mock())
    emu._sync_clock = Mock()
    emu._autosave = Mock()
    emu.tracker, emu.steps = Mock(), Mock()
    emu.statistics = SimpleNamespace(previous=None, records=Mock())
    emu.policy = Mock()
    emu.paused = emu.manual_mode = False
    yield emu
    emu.store.close()


def test_restart_clears_the_old_runs_watch_and_bests(gen2_emu):
    """The new run starts at frame 0, so the old frames and bests kept guards off and the run stalled."""
    from pokesim.gen2.emulator import STALL_RELOADS
    emu = gen2_emu
    emu.frame = 500000
    emu.last_reload_frame = emu._reward_check_frame = emu._guard_frame = 499000
    emu.best_progress = (8, 900, 120, 40, 400000, 3)
    emu.best_experience = {(1, (), 7): 400000}
    emu.best_egg_cycles = {'egg': 3}
    emu.unstick_streak, emu.reloads_exhausted = STALL_RELOADS + 5, True
    emu.stall = StallWatch()
    emu.stall.progress(400000, 0.0)
    emu.stall.alerted = 1.0
    emu._handle_command('restart', None)
    assert emu.frame == 0 and emu.last_reload_frame == 0
    assert emu._reward_check_frame == 0 and emu._guard_frame == 0
    assert emu.best_progress == (0,) * 6 and emu.best_experience == {} and emu.best_egg_cycles == {}
    assert emu.unstick_streak == 0 and not emu.reloads_exhausted
    assert emu.stall.frame is None and emu.stall.alerted is None


@pytest.mark.parametrize('error', [ValueError('refused'), OSError('unreadable'), EOFError('truncated')])
def test_a_broken_rewind_never_ends_the_run(gen2_emu, error):
    emu = gen2_emu
    (emu.store.states / 'event-1.state').write_bytes(b'x')
    emu._load_state_file = Mock(side_effect=error)
    assert emu._handle_command('load_state', 'event-1.state') is True


def test_a_truncated_autosave_falls_back_to_an_older_one(gen2_emu, monkeypatch):
    emu = gen2_emu
    older, newer = emu.store.states / 'auto-1.state', emu.store.states / 'auto-2.state'
    loaded = []

    def load(path):
        if path == newer:
            raise EOFError('truncated')
        loaded.append(path)
    emu._load_state_file = load
    emu.store.autosaves = lambda: [older, newer]
    monkeypatch.setattr('pokesim.rewards.initialize', lambda *args: None)
    emu.snapshot = None
    emu._clear_stale_hold = Mock(side_effect=StopIteration)
    with pytest.raises(StopIteration):
        emu.start()
    assert loaded == [older]


def contest_case(monkeypatch, day=2, flags=0, decisions=100, started=0):
    from pokesim.gen2 import contest
    values = {'wCurDay': day, 'wDailyFlags1': flags, 'wStatusFlags2': 0}
    monkeypatch.setattr(contest, 'Memory', lambda memory, data: SimpleNamespace(byte=lambda name: values.get(name, 0)))
    data = SimpleNamespace(maps={1: {'constant': 'ROUTE_35'}})
    policy = SimpleNamespace(memory=None, data=data, decisions=decisions,
                             collection={'contest': {'entered': False, 'started': started}})
    snapshot = SimpleNamespace(map=1, x=5, y=5)
    return contest, policy, snapshot


def goal(*args, **kwargs):
    return SimpleNamespace(key=args[0])


def test_contest_entry_continues_on_a_contest_day(monkeypatch):
    contest, policy, snapshot = contest_case(monkeypatch)
    assert contest.journey(policy, snapshot, goal).key == 'contest_enter'


@pytest.mark.parametrize('change', [{'day': 3}, {'flags': 2}])
def test_contest_entry_is_dropped_once_the_contest_is_closed(monkeypatch, change):
    """Midnight passing on the walk, or today's contest already run, once sent the run to the gate forever."""
    contest, policy, snapshot = contest_case(monkeypatch, **change)
    assert contest.journey(policy, snapshot, goal) is None
    assert 'contest' not in policy.collection


def test_contest_entry_that_never_reaches_the_gate_stands_down(monkeypatch):
    from pokesim.gen2.standdown import standing_down
    contest, policy, snapshot = contest_case(monkeypatch, decisions=6000)
    assert contest.journey(policy, snapshot, goal) is None
    assert 'contest' not in policy.collection and standing_down(policy, contest.CONTEST_KEY)


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    import os
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def rock_case(data, party, items=()):
    flags = {'EVENT_GOT_MASTER_BALL_FROM_ELM', 'EVENT_GOT_TM08_ROCK_SMASH'}
    policy = SimpleNamespace(data=data, collection={}, returned=set(), decisions=1000,
                             nav=SimpleNamespace(regions=SimpleNamespace(cleared_rocks={})),
                             person=lambda snapshot, key, *args: SimpleNamespace(key=key))
    # Celebi is registered, so Crystal's GS Ball errand comes after the rock.
    snapshot = SimpleNamespace(owned={251}, can_catch=True, items=tuple(items), event=lambda name: name in flags,
                               map=data.map_ids['NEW_BARK_TOWN'], party=party, stored=[], roamers=())
    return policy, snapshot


def party_mon(species, moves=(33, 0, 0, 0)):
    return SimpleNamespace(species=species, moves=moves, egg=False)


def test_burned_tower_rock_needs_someone_who_can_smash_it(real_data):
    """With TM08 used up and no one knowing Rock Smash, the run once waited at the rock forever."""
    from pokesim.gen2 import quests
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.standdown import standing_down
    tm = (real_data.items['TM_ROCK_SMASH'], 1)
    policy, snapshot = rock_case(real_data, [party_mon(74)], [tm])
    if real_data.game == 'crystal':
        # Crystal wakes the beasts during the story, so there is no rock to clear.
        assert quests.legends(policy, snapshot, Goal).key == 'pewter_wing'
        assert not standing_down(policy, quests.RELEASE_ROCK_KEY)
        return
    assert quests.legends(policy, snapshot, Goal).key == 'collection_release_rock'
    policy, snapshot = rock_case(real_data, [party_mon(74, (249, 0, 0, 0))])
    assert quests.legends(policy, snapshot, Goal).key == 'collection_release_rock'
    for party, items in [([party_mon(74)], ()), ([party_mon(129)], [tm])]:
        policy, snapshot = rock_case(real_data, party, items)
        assert quests.legends(policy, snapshot, Goal).key == 'pewter_wing'
        assert standing_down(policy, quests.RELEASE_ROCK_KEY)


def test_arriving_at_the_rock_without_rock_smash_stands_down(real_data):
    from pokesim.gen2 import quests
    from pokesim.gen2.standdown import standing_down
    policy, snapshot = rock_case(real_data, [party_mon(74)])
    policy.goal, policy.menu = SimpleNamespace(key='collection_release_rock'), None
    assert quests.arrive(policy, snapshot) == 'b'
    assert policy.menu is None and standing_down(policy, quests.RELEASE_ROCK_KEY)


class Zeros:
    """Work RAM that reads as all zeros."""

    def __getitem__(self, key):
        window = key[1] if isinstance(key, tuple) else key
        return [0] * (window.stop - window.start)


ZEROS = Zeros()


class Onward(Exception):
    """Raised once the policy walks past the teaching checks."""


@pytest.fixture
def teaching_policy(real_data, monkeypatch):
    from pokesim.gen2 import contest, ruins, tower
    from pokesim.gen2 import policy as module
    from pokesim.gen2.policy import Goal, Policy
    monkeypatch.setattr(module, 'update_world', lambda *args: None)
    for part in (ruins, contest, tower):
        monkeypatch.setattr(part, 'control', lambda *args: None)
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.naming.step = lambda snapshot, mem: None
    policy.journey = lambda snapshot, mem: Goal('explore', 'Explore', 'NEW_BARK_TOWN', 1, 1)
    policy.release_goal = lambda snapshot, mem: None
    policy.level_lead = lambda snapshot: None
    policy.nav.observe = lambda snapshot: None
    # Zeroed RAM has no map width, which reads as a cartridge back at its opening.
    policy.unloaded = lambda snapshot, mem: False

    def onward(snapshot):
        raise Onward
    policy.in_league = onward
    return policy


def teaching_snapshot(data, lead, *, events=(), items=(), badges=0):
    return SimpleNamespace(started=True, valid=True, in_battle=0, hall_of_fame_count=0, map=data.map_ids['NEW_BARK_TOWN'],
                           tiles=(' ' * 20,) * 18, text='', party=(lead,), event=lambda name: name in events,
                           items=tuple(items), badges=badges, frame=1000, box_counts=(0,) * 14)


def test_a_refused_hm_lesson_is_not_asked_for_again_at_once(teaching_policy, real_data):
    from pokesim.gen2.menus import Teach
    policy = teaching_policy
    lead = SimpleNamespace(species=155, egg=False, moves=(33, 43, 0, 0))
    snapshot = teaching_snapshot(real_data, lead, events={'EVENT_GOT_HM01_CUT'})
    policy.step(snapshot, ZEROS)
    assert policy.menu == Teach(15, 0)
    policy.menu = None
    policy.blocked[policy.task_key(Teach(15, 0))] = snapshot.frame + policy.RETRY_FRAMES
    with pytest.raises(Onward):
        policy.step(snapshot, ZEROS)
    assert policy.menu is None


def test_a_refused_iron_tail_lesson_is_not_asked_for_again_at_once(teaching_policy, real_data):
    from pokesim.gen2.menus import Teach
    policy = teaching_policy
    lead = SimpleNamespace(species=25, egg=False, moves=(33, 0, 0, 0))
    snapshot = teaching_snapshot(real_data, lead, items=[(real_data.items['TM23'], 1)], badges=128)
    policy.step(snapshot, ZEROS)
    assert policy.menu == Teach(231, 0)
    policy.menu = None
    policy.blocked[policy.task_key(Teach(231, 0))] = snapshot.frame + policy.RETRY_FRAMES
    with pytest.raises(Onward):
        policy.step(snapshot, ZEROS)
    assert policy.menu is None


def test_a_stone_gone_before_the_evolution_drops_the_project(real_data):
    """The evolution step read the stone's count with a lookup that raised once the stone was gone."""
    from pokesim.gen2.menus import Remedy
    from pokesim.gen2.training import arrive, identity, journey
    from pokesim.gen2.policy import Goal
    gloom = SimpleNamespace(species=44, name='Gloom', level=40, experience=100000, egg=False,
                            box=None, trainer_id=1, dvs=(5,) * 5, held_item=0)
    stone = (real_data.items['SUN_STONE'], 1)
    snapshot = SimpleNamespace(party=(gloom,), stored=(), owned=set(range(1, 252)) - {182}, items=(stone,),
                               map=real_data.map_ids['GOLDENROD_CITY'], x=1, y=1)
    policy = SimpleNamespace(data=real_data, collection={}, menu=None)
    policy.goal = journey(policy, snapshot, SimpleNamespace(byte=lambda name: 1), Goal)
    assert policy.goal.key == 'collection_evolve_item' and policy.collection['training']['identity'] == identity(gloom)
    assert arrive(policy, snapshot) == 'wait' and isinstance(policy.menu, Remedy)
    policy.menu, snapshot.items = None, ()
    assert arrive(policy, snapshot) is None
    assert policy.menu is None and policy.collection['training'] is None


def test_npc_trade_waits_while_the_party_and_every_box_are_full(monkeypatch):
    """With nowhere to deposit a party member, fetching the boxed partner pressed B at the PC forever."""
    from pokesim.gen2 import npc_trades
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: 0)
    data = SimpleNamespace(symbols={'wTradeFlags': (0, 0)}, game='gold',
                           species={69: {'name': 'Bellsprout'}, 95: {'name': 'Onix'}})
    storage = SimpleNamespace(map_name='VIOLET_POKECENTER_1F', x=1, y=1, face='up')
    policy = SimpleNamespace(data=data, collection={}, demand={}, decisions=1, storage_goal=lambda snapshot: storage,
                             person=lambda snapshot, key, *args: SimpleNamespace(key=key))
    party = [SimpleNamespace(species=155, level=40, box=None, position=None, held_item=0, moves=[33], gender='Male', egg=False)
             for _ in range(6)]
    boxed = SimpleNamespace(species=69, level=5, box=0, position=0, held_item=0, moves=[33], gender='Male', egg=False)
    snapshot = SimpleNamespace(party=party, stored=[boxed], owned=set(), box_counts=(20,) * 14)
    goal = lambda key, *args: SimpleNamespace(key=key)
    mem = SimpleNamespace(memory=object())
    assert npc_trades.journey(policy, snapshot, mem, goal) is None
    snapshot.box_counts = (20,) * 13 + (19,)
    assert npc_trades.journey(policy, snapshot, mem, goal).key == 'collection_npc_trade_pc'
