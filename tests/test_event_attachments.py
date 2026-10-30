"""Routine journal entries keep their screenshot and save only for the newest few, milestones forever."""
import os
import time

import pytest

from pokesim import config
from pokesim.events import Event
from pokesim.store import Store
from test_events import snap

MANIFEST = {'policy_state': {}, 'run_memory': {}, 'generation': 2}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    yield store
    store.close()


def routine(store, title='Arrived at Route 29'):
    eid = store.add_event(Event('map', title, priority=2), snap(), b'png', b'state')
    store.write_checkpoint(b'state', MANIFEST, name=f'event-{eid}.state', compress=True)
    return eid


def files(store, eid):
    return [store.shots / f'{eid}.png', store.states / f'event-{eid}.state', store.states / f'event-{eid}.json']


def kept(store, eid):
    row = store.event(eid)
    return row['shot'] is not None and row['state'] is not None and all(path.exists() for path in files(store, eid))


def test_the_default_keeps_five_hundred():
    assert config.EVENT_ATTACHMENT_KEEP == 500


def test_routine_entries_past_the_cap_lose_their_attachments_oldest_first(store):
    ids = [routine(store) for _ in range(5)]
    assert store.prune_attachments(2) == 3
    for eid in ids[:3]:
        row = store.event(eid)
        assert row['title'] == 'Arrived at Route 29', 'the journal text is kept forever'
        assert row['shot'] is None and row['state'] is None
        assert not any(path.exists() for path in files(store, eid)), 'the sidecar goes with its save'
    assert all(kept(store, eid) for eid in ids[3:])
    assert store.prune_attachments(2) == 0


def test_the_cap_keeps_the_newest_as_entries_arrive(store):
    first = routine(store)
    second = routine(store)
    assert store.prune_attachments(2) == 0
    third = routine(store)
    assert store.prune_attachments(2) == 1
    assert not kept(store, first) and kept(store, second) and kept(store, third)


def test_zero_keeps_every_attachment(store):
    ids = [routine(store) for _ in range(4)]
    assert store.prune_attachments(0) == 0
    assert all(kept(store, eid) for eid in ids)


def test_milestones_keep_their_attachments_and_do_not_count_toward_the_cap(store):
    badge = store.add_event(Event('badge', 'Earned the Zephyr Badge', priority=5), snap(), b'png', b'state')
    store.write_checkpoint(b'state', MANIFEST, name=f'event-{badge}.state', compress=True)
    catch = store.add_event(Event('catch', 'Caught Sentret', priority=4), snap(), b'png', None)
    ids = [routine(store) for _ in range(3)]
    assert store.prune_attachments(1) == 2
    assert kept(store, badge)
    assert store.event(catch)['shot'] == f'{catch}.png' and (store.shots / f'{catch}.png').exists()
    assert not kept(store, ids[0]) and not kept(store, ids[1]) and kept(store, ids[2])


def test_entries_with_only_a_screenshot_count_as_routine(store):
    faints = [store.add_event(Event('faint', 'Pidgey fainted', priority=1), snap(), b'png', None) for _ in range(3)]
    assert store.prune_attachments(1) == 2
    assert [store.event(eid)['shot'] for eid in faints] == [None, None, f'{faints[2]}.png']


def test_finished_custom_reward_saves_are_removed_and_the_pending_one_stays(store):
    from pokesim.runtime.reward_delivery import PENDING
    from pokesim.store import PENDING_REWARD
    assert PENDING_REWARD == PENDING
    root = store.dir / 'custom-rewards'
    for name in ('done', 'pending', 'staging'):
        (root / name).mkdir(parents=True)
        (root / name / 'result.state').write_bytes(b'state')
    old = time.time() - 7200
    for name in ('done', 'pending'):
        os.utime(root / name, (old, old))
    store.set('custom-reward-pending-v1', {'id': 'pending', 'phase': 'committed', 'decision': 'COMMIT'})
    assert store.prune_reward_results() == 1
    assert sorted(path.name for path in root.iterdir()) == ['pending', 'staging']
    store.set('custom-reward-pending-v1', {'id': 'pending', 'phase': 'complete', 'decision': 'COMMIT'})
    assert store.prune_reward_results() == 1
    assert [path.name for path in root.iterdir()] == ['staging']
