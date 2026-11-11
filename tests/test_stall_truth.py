"""Stall bundles, help requests and restarts each leave a row the progress replay reads as ground truth."""
from contextlib import closing, nullcontext
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from pokesim import config, progress_events, stall_truth
from pokesim.app.manager import Manager
from pokesim.app.registry import identifier
from pokesim.play_clock import PlayClock
from pokesim.runtime.supervision import Supervisor
from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE, StallWatch
from pokesim.store import Store
from pokesim.web.app import create_app
from test_managed_supervisor import adventure, supervisor  # noqa: F401  (the fixture)

MANIFEST = {'policy_state': {}, 'run_memory': {}, 'frame': 5}
LOOP = 'It received and released Rattata 6 times without other progress'


def truth(store, kind=None):
    """The rows without the id and wall time, which differ between two runs of the same situation."""
    return [{k: v for k, v in row.items() if k not in ('id', 'ts')} for row in stall_truth.rows(store.db, kind)]


class LastScan:
    """The loop guard as the status sees it: the answer of the emulator thread's last scan."""

    def __init__(self, loop):
        self.loop = loop

    @property
    def reason(self):
        return self.loop[0]


def stalled_game(store, loop):
    """The parts of a stalled run that a help request reads, for both generations."""
    stall = StallWatch(game_minutes=120, real_minutes=0)
    stall.progress(0, 0)
    return dict(store=store, stall=stall, frame=130 * MINUTE, play_clock=PlayClock({'frames': 130 * MINUTE}),
                paused=False, manual_mode=False, loop_guard=LastScan(loop))


def gen1_help(game):
    from pokesim.emulator import Emulator
    # The same call the status makes.
    return stall_truth.observe_help(game, Emulator.help_request(game, {'action': 'exploring'}))


def gen2_help(game):
    from pokesim.gen2.emulator import Emulator
    return Emulator.status(game)['help_request']


def gen1_game(store, loop):
    return SimpleNamespace(**stalled_game(store, loop), snapshot=None, policy=SimpleNamespace(boxes_full=False))


def gen2_game(store, loop):
    now = time.time()
    policy = SimpleNamespace(mode='exploring', describe=lambda: '', details=dict, boxes_full=False)
    return SimpleNamespace(**stalled_game(store, loop), last_achievement=None, progress_frame=0, waiting=False,
                           supervisor=Supervisor(), last_reload=0, policy=policy, frozen=False, health=dict, speed=1,
                           snapshot=None, rom_note='', executed_frames=0, started_at=now,
                           stuck_frame=130 * MINUTE, history={'maps': set()}, reloads=0, invalid_frame=None,
                           legendary_recovery=SimpleNamespace(state_dict=dict))


def help_story(tmp_path, make, ask):
    """A stall asked about on every poll, then a loop, a recovery and a second stall."""
    store = Store(tmp_path)
    store.clock = lambda: 42
    loop = [None]
    game = make(store, loop)
    try:
        for _ in range(3):
            assert ask(game)['reason'] == 'The policy has stopped making game progress'
        loop[0] = LOOP
        assert ask(game)['reason'] == f'The run is caught in a loop. {LOOP}'
        assert ask(game)
        loop[0] = None
        game.stall.progress(game.play_clock.frames, 0)
        assert ask(game) is None
        game.play_clock.frames += 120 * MINUTE
        assert ask(game)
        return truth(store)
    finally:
        store.close()


def test_a_help_request_writes_one_row_when_it_starts_and_one_when_it_changes(tmp_path):
    rows = help_story(tmp_path, gen1_game, gen1_help)
    assert [(row['request'], row['frame'], row['source']) for row in rows] == [
        ('stall', 42, ''), ('loop', 42, ''), ('stall', 42, '')]
    assert rows[1]['reason'] == f'The run is caught in a loop. {LOOP}' and rows[0]['action'] == 'exploring'


def test_every_stall_bundle_keeps_its_row_after_the_folder_is_pruned(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.clock = lambda: 900
    stamps = iter(f'2026110{n}T000000Z' for n in range(1, 5))
    monkeypatch.setattr('pokesim.checkpoints.time.strftime', lambda *a: next(stamps))
    try:
        report = {'reason': 'walking to Route 3', 'quiet_game_minutes': 130, 'map': 'Pewter City',
                  'objective': {'id': 'badge-boulder', 'title': 'Beat Brock'}}
        for _ in range(3):
            store.write_stall_bundle(b'noticed', MANIFEST, report, None, None, keep=2)
        assert len(list(store.checkpoints.stalls.iterdir())) == 2
        rows = truth(store, 'bundle')
        assert [row['folder'] for row in rows] == [f'stall-2026110{n}T000000Z' for n in range(1, 4)]
        assert rows[0] == {'frame': 900, 'kind': 'bundle', 'source': '', 'folder': 'stall-20261101T000000Z',
                           'reason': 'walking to Route 3', 'stall': 'quiet', 'goal': 'badge-boulder',
                           'quiet_game_minutes': 130, 'map': 'Pewter City'}
    finally:
        store.close()


def test_a_new_game_keeps_the_rows_and_a_reopened_store_keeps_them_too(tmp_path):
    store = Store(tmp_path)
    try:
        stall_truth.write(store, 'help', request='stall')
        with store.lock, store.db:
            progress_events.record(store.db, 'catch', species=1)
        store.restart(1, {})
        assert store.db.execute('SELECT COUNT(*) FROM progress_events').fetchone()[0] == 0
    finally:
        store.close()
    reopened = Store(tmp_path)
    try:
        assert [row['request'] for row in truth(reopened)] == ['stall']
    finally:
        reopened.close()


def test_a_failed_write_never_reaches_the_caller(tmp_path, caplog):
    store = Store(tmp_path)
    try:
        store.db.execute('DROP TABLE kv')
        stall_truth.lifecycle(tmp_path, 'start', 'owner')
        stall_truth.write(SimpleNamespace(lock=nullcontext(), db=None), 'help')
        assert truth(store) == [] and 'progress replay' in caplog.text
    finally:
        store.close()


def test_a_new_game_and_a_rewind_from_the_page_are_owner_restarts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store = Store(tmp_path)
    store.clock = lambda: 7
    emu = Mock()
    try:
        state = store.write_checkpoint(b'state', MANIFEST).name
        with TestClient(create_app(emu, store)) as client:
            assert client.post('/api/control', json={'action': 'load_state', 'value': state}).status_code == 200
            assert client.post('/api/control', json={'action': 'restart'}).status_code == 200
            assert client.post('/api/control', json={'action': 'pause'}).status_code == 200
        assert [(row['source'], row['action'], row['frame']) for row in truth(store, 'restart')] == [
            ('owner', 'rewind', 7), ('owner', 'new_game', 7)]
        assert truth(store)[0]['state'] == state
    finally:
        store.close()


def library(supervisor):  # noqa: F811
    return SimpleNamespace(check_available=lambda: None, maintenance=nullcontext(), supervisor=supervisor,
                           registry=supervisor.registry, coordinator=SimpleNamespace(reserved=lambda aid: False),
                           leases=SimpleNamespace(stop_worker=supervisor.stop), root=supervisor.registry.root)


def offline_rows(folder):
    """Read the rows from the database file alone, as from a copy of the data folder."""
    with closing(sqlite3.connect(folder / 'pokesim.sqlite')) as db:
        return [{k: row[k] for k in ('frame', 'source', 'action')} for row in stall_truth.rows(db, 'restart')]


def test_library_start_and_stop_are_owner_restarts_and_a_crash_restart_is_not(supervisor):  # noqa: F811
    aid = adventure(supervisor)
    folder = supervisor.registry.root / 'adventures' / aid
    store = Store(folder)
    store.set('play_clock', {'frames': 3600, 'initialized': True})
    store.close()
    manager = library(supervisor)
    Manager.start_adventure(manager, aid)
    # A second press while it runs changes nothing.
    Manager.start_adventure(manager, aid)
    child = supervisor.children[aid]
    child.process.poll = lambda: 1
    waits = iter([False, True])
    original = supervisor.closed
    supervisor.closed = SimpleNamespace(wait=lambda seconds: next(waits), is_set=lambda: False)
    try:
        supervisor._monitor()
    finally:
        supervisor.closed = original
    # The monitor schedules the restart after a short wait, and a later pass starts it.
    assert aid not in supervisor.children
    supervisor.restarts[aid][1] = time.monotonic() - 1
    supervisor.run_restarts()
    assert supervisor.children[aid] is not child
    supervisor.registry.request_lifecycle(aid, 'stop', identifier())
    Manager.start_adventure(manager, aid)
    assert offline_rows(folder) == [{'frame': 3600, 'source': 'owner', 'action': 'start'},
                                    {'frame': 3600, 'source': 'supervisor', 'action': 'start'},
                                    {'frame': 3600, 'source': 'owner', 'action': 'stop'}]


def test_an_adventure_that_never_ran_gets_no_database(tmp_path):
    stall_truth.lifecycle(tmp_path / 'never', 'start', 'boot')
    assert not (tmp_path / 'never').exists()
