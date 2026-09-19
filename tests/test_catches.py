from types import SimpleNamespace

import pytest

from pokesim.catches import ADDRESS, BANK, KEY, SIGNATURE, SUPPORTED, CatchTracker, status
from pokesim.store import Store


@pytest.fixture
def tracking(tmp_path):
    store = Store(tmp_path)
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    try:
        yield store, tracker
    finally:
        store.close()


def capture(species=84, battle=1, kind=0, sequence=0):
    memory = bytearray(65536)
    memory[0xd11c] = species
    memory[0xd057] = battle
    memory[0xd05a] = kind
    memory[0xda44] = sequence
    return SimpleNamespace(memory=memory)


def test_duplicate_species_and_pc_catches_count_without_dex_changes(tracking):
    store, tracker = tracking
    tracker.completed(capture(sequence=1))
    boxed = capture(sequence=2)
    boxed.memory[0xd163] = 6
    boxed.memory[0xda80] = 12
    tracker.completed(boxed)
    assert status(store)['counts'] == {'25': 2}
    assert status(store)['total'] == 2


@pytest.mark.parametrize('species,battle,kind', [
    (0, 1, 0), (255, 1, 0), (84, 0, 0), (84, 2, 0), (84, 1, 1),
])
def test_failure_gifts_trades_and_tutorial_do_not_count(tracking, species, battle, kind):
    store, tracker = tracking
    tracker.completed(capture(species, battle, kind))
    assert status(store)['total'] == 0


def test_safari_capture_counts(tracking):
    store, tracker = tracking
    tracker.completed(capture(kind=2))
    assert status(store)['total'] == 1


def test_reloaded_capture_receipt_is_idempotent_and_survives_reopen(tmp_path):
    store = Store(tmp_path)
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    tracker.completed(capture())
    started = status(store)['started_at']
    store.close()
    store = Store(tmp_path)
    try:
        tracker = CatchTracker(store, sorted(SUPPORTED)[0], fresh=True)
        tracker.completed(capture())
        assert status(store)['total'] == 1
        assert status(store)['started_at'] == started
        assert not status(store)['complete_history']
        assert store.db.execute('SELECT COUNT(*) FROM capture_receipts').fetchone()[0] == 1
    finally:
        store.close()


def test_new_run_has_complete_history_but_existing_run_does_not(tmp_path):
    store = Store(tmp_path)
    try:
        CatchTracker(store, sorted(SUPPORTED)[0], fresh=True)
        assert status(store)['complete_history']
    finally:
        store.close()


def test_counts_survive_event_pruning_and_checkpoint_memory_changes(tracking):
    store, tracker = tracking
    tracker.completed(capture())
    store.prune_events(0)
    store.set('run_memory', {})
    store.set('policy_state', {})
    assert status(store)['counts'] == {'25': 1}


def test_restart_explicitly_starts_a_fresh_count(tracking):
    store, tracker = tracking
    tracker.completed(capture())
    tracker.reset()
    assert status(store)['total'] == 0
    assert status(store)['complete_history']
    tracker.completed(capture())
    assert status(store)['total'] == 1


def test_unknown_rom_does_not_install_an_unverified_hook(tmp_path):
    store = Store(tmp_path)
    try:
        tracker = CatchTracker(store, 'unknown')
        tracker.attach(SimpleNamespace())
        assert not status(store)['available']
    finally:
        store.close()


def test_signature_mismatch_fails_before_attaching(tracking):
    _, tracker = tracking
    class Memory:
        def __getitem__(self, key):
            return bytes(len(SIGNATURE))
    with pytest.raises(ValueError, match='signature'):
        tracker.attach(SimpleNamespace(memory=Memory()))


def test_totals_are_atomic_with_receipts(tracking):
    store, tracker = tracking
    original = store.db
    class FailingDatabase:
        def __enter__(self):
            return original.__enter__()
        def __exit__(self, *args):
            return original.__exit__(*args)
        def execute(self, statement, parameters=()):
            if statement.startswith('UPDATE kv'):
                raise RuntimeError('test failure')
            return original.execute(statement, parameters)
    store.db = FailingDatabase()
    try:
        with pytest.raises(RuntimeError, match='test failure'):
            tracker.completed(capture())
        assert original.execute('SELECT COUNT(*) FROM capture_receipts').fetchone()[0] == 0
        assert status(store)['total'] == 0
    finally:
        store.db = original
