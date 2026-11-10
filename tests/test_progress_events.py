"""Shadow-mode progress rows in both generations (docs/design/goal-system.md, section 4)."""
from types import SimpleNamespace

import pytest

from pokesim import progress_events
from pokesim.events import Event
from pokesim.store import Store
from test_behavior_parity import PAIRS, gen1_catches, gen1_checkpoint, gen2_catches, gen2_checkpoint
from test_behavior_parity import gen2_data as gen2_data  # noqa: F401 (a fixture)
from test_collection import sid

SNAPSHOT = SimpleNamespace(map_name='Route 1', playtime=(0, 0, 0), valid=False, started=False)


def rows(store, *kinds):
    marks = ','.join('?' * len(kinds))
    return store.db.execute(f'SELECT kind, frame, goal, tier, species, identity, score, net FROM progress_events '
                            f'WHERE kind IN ({marks}) ORDER BY id', kinds).fetchall()


def test_both_marathons_write_a_net_row_for_a_checkpoint(tmp_path, gen2_data, monkeypatch):  # noqa: F811
    for name, (_, queue) in (('gen1', gen1_checkpoint()), ('gen2', gen2_checkpoint(gen2_data, monkeypatch))):
        store = Store(tmp_path / name)
        store.clock = lambda: 600
        try:
            assert progress_events.drain(store, queue) == []
            [(kind, frame, goal, tier, _, _, score, net)] = rows(store, 'checkpoint')
            assert (kind, frame, tier, score, net) == ('checkpoint', 600, 'RACE', 1, 1) and goal
        finally:
            store.close()


def test_a_drain_keeps_the_journal_entries():
    entry = {'type': 'activity', 'title': 'The Kanto Marathon is on!'}
    store = SimpleNamespace(clock=None)
    assert progress_events.drain(store, [entry]) == [entry]


def test_a_checkpoint_row_comes_only_past_the_starting_line():
    assert progress_events.checkpoints(0, 1, 'race') == []
    assert [row['score'] for row in progress_events.checkpoints(1, 3, 'race')] == [1, 2]


@pytest.mark.parametrize(('gen1', 'gen2'), PAIRS)
def test_both_write_two_catch_rows_with_no_net_for_a_duplicate_catch(tmp_path, gen1, gen2):
    first, second = gen1_catches(tmp_path, gen1), gen2_catches(tmp_path, gen2)
    try:
        for store in (first, second):
            catches = rows(store, 'catch')
            assert [(kind, species, net) for kind, _, _, _, species, _, _, net in catches] == [('catch', 16, 0)] * 2
            # Two copies of one species keep apart by their trainer id or DVs.
            assert len({row[5] for row in catches}) == 2
    finally:
        first.close()
        second.close()


def test_both_count_a_catch_and_a_gift_as_no_net_progress(tmp_path):
    from pokesim import catches
    from pokesim.gen2 import tracking
    first, second = gen1_catches(tmp_path, 'red'), gen2_catches(tmp_path, 'gold')
    try:
        with first.lock, first.db:
            catches.record_gift(first.db, 7, sid(16))
        with second.lock, second.db:
            tracking.record_gift(second.db, 7, 16)
        for store in (first, second):
            found = rows(store, 'catch', 'receive')
            assert [row[0] for row in found].count('receive') == 1
            assert sum(row[-1] for row in found) == 0
    finally:
        first.close()
        second.close()


def test_a_journal_release_and_trade_write_their_rows(tmp_path):
    store = Store(tmp_path)
    store.clock = lambda: 42
    try:
        store.add_event(Event('release', 'Released Pidgey', species=16), SNAPSHOT, None, None)
        store.add_event(Event('trade', 'Traded Pidgey for Abra'), SNAPSHOT, None, None)
        store.add_event(Event('badge', 'Boulder Badge'), SNAPSHOT, None, None)
        assert [(kind, frame, species, net) for kind, frame, _, _, species, _, _, net in
                rows(store, 'release', 'receive', 'badge')] == [('release', 42, 16, 0), ('receive', 42, None, 0)]
    finally:
        store.close()


def test_a_goal_row_comes_when_the_running_goal_changes(tmp_path):
    store = Store(tmp_path)
    try:
        watch = progress_events.GoalWatch()
        for key, tier in (('race', 'RACE'), ('race', 'RACE'), ('hunt:16', ''), (None, '')):
            watch.observe(store, key, tier)
        assert [(goal, tier) for _, _, goal, tier, *_ in rows(store, 'goal')] == [('race', 'RACE'), ('hunt:16', '')]
    finally:
        store.close()


def test_a_gen2_goal_key_names_the_activity_hunt_or_training():
    from pokesim.gen2.standdown import goal_key, hunt_key
    policy = SimpleNamespace(collection={'target': None})
    assert goal_key(policy) == (None, '')
    policy.collection['target'] = {'species': 16}
    assert goal_key(policy) == (hunt_key(16), '')
    policy.collection['postgame'] = {'activity': {'kind': 'marathon'}}
    assert goal_key(policy) == ('marathon', 'RACE')


def test_both_forget_the_rows_on_a_new_game(tmp_path):
    from pokesim.catches import CatchTracker
    from pokesim.gen2.tracking import Tracker
    from test_gen2_activity import fake_data
    first, second = gen1_catches(tmp_path, 'red'), gen2_catches(tmp_path, 'gold')
    try:
        CatchTracker(first, 'unused').reset()
        Tracker(second, fake_data(), fresh=False).reset()
        for store in (first, second):
            assert store.db.execute('SELECT COUNT(*) FROM progress_events').fetchone()[0] == 0
    finally:
        first.close()
        second.close()
