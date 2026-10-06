"""Action receipts count confirmed actions once without inventing old history."""
from contextlib import closing
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.activity_ledger import ActivityLedger, KEY, status
from pokesim.catches import CatchTracker, SUPPORTED, record_gift
from pokesim.store import Store


@pytest.fixture
def ledger(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = ActivityLedger(store, sorted(SUPPORTED)[0])
        store.set(KEY, {'started_at': 123, 'available': True})
        yield tracker


def action(tracker, kind, *, sequence=1, species=84, battle=1, item=20, quantity=1, tutorial=False, link=False, transformed=False, hp=0):
    memory = bytearray(65536)
    memory[0xcfd8] = species
    memory[0xd057] = battle
    memory[0xd05a] = int(tutorial)
    memory[0xd12b] = int(link)
    memory[0xd069] = 8 if transformed else 0
    memory[0xcf91] = item
    memory[0xcf96] = quantity
    memory[0xd31d] = 1
    memory[0xd31e] = item
    memory[0xd31f] = 50
    memory[0xda44] = sequence
    memory[0xcfe6:0xcfe8] = hp.to_bytes(2, 'big')
    memory[0xffdb] = item
    tracker.completed((kind, SimpleNamespace(memory=memory)))


def row(store, table, subject):
    return next(row for row in status(store)[table] if row['id'] == subject)


def test_encounters_defeats_transform_and_replays(ledger):
    for _ in range(2):
        action(ledger, 'wild')
        action(ledger, 'defeated')
    action(ledger, 'wild', sequence=2)
    action(ledger, 'trainer', battle=2, sequence=3)
    action(ledger, 'trainer', battle=2, transformed=True, sequence=4)
    action(ledger, 'defeated', hp=5, sequence=5)
    action(ledger, 'defeated', transformed=True, sequence=6)
    assert row(ledger.store, 'pokemon', 25) == {
        'id': 25, 'name': 'Pikachu', 'wild': 2, 'trainer': 1, 'defeated': 2,
        'caught': None, 'gift': 0, 'traded_in': 0, 'traded_out': 0, 'held': None}
    for kind in ('wild', 'defeated', 'used', 'bought'):
        action(ledger, kind, tutorial=True)
        action(ledger, kind, link=True)
    assert row(ledger.store, 'pokemon', 25)['wild'] == 2
    assert row(ledger.store, 'items', 20)['used'] == 0


def test_purchase_quantities_and_successful_consumption(ledger):
    action(ledger, 'bought', item=4, quantity=50)
    action(ledger, 'bought', item=4, quantity=50)
    action(ledger, 'ball', item=4, sequence=2)
    action(ledger, 'safari', item=4, sequence=3)
    action(ledger, 'used', item=20, battle=0, sequence=4)
    action(ledger, 'used', item=201, battle=0, sequence=5)
    action(ledger, 'used', item=6, battle=0, sequence=6)
    action(ledger, 'bought', item=4, quantity=0, sequence=7)
    action(ledger, 'vending', item=60, quantity=99, sequence=8)
    assert row(ledger.store, 'items', 4)['bought'] == 50
    assert row(ledger.store, 'items', 4)['used'] == 1
    assert row(ledger.store, 'items', 8)['used'] == 1
    assert row(ledger.store, 'items', 20)['used'] == 1
    assert row(ledger.store, 'items', 201)['used'] == 1
    assert row(ledger.store, 'items', 6)['used'] is None
    assert row(ledger.store, 'items', 60)['bought'] == 1


def test_catches_gifts_and_held_counts_have_separate_meanings(ledger):
    store = ledger.store
    tracker = CatchTracker(store, sorted(SUPPORTED)[0])
    tracker.record('capture-a', 25)
    tracker.record('capture-a', 25)
    with store.db:
        record_gift(store.db, 45, 84)
    data = status(store, {'party': [{'species': 84}],
                          'storage': {'pokemon': [{'species': 84}, {'species': 153}]},
                          'items': [{'id': 20, 'qty': 7}]})
    pikachu = next(row for row in data['pokemon'] if row['id'] == 25)
    assert (pikachu['caught'], pikachu['gift'], pikachu['held']) == (1, 1, 2)
    assert next(row for row in data['items'] if row['id'] == 20)['bag'] == 7
    assert len(data['pokemon']) == 151
    assert all(row['id'] not in (0, 7, 9, 21, 44, 84) for row in data['items'])


def test_old_catch_receipts_backfill_once_without_guessing_encounters(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = CatchTracker(store, sorted(SUPPORTED)[0])
        tracker.record('old-catch', 25)
        with store.db:
            record_gift(store.db, 1, 84)
            store.db.execute('DELETE FROM activity_counts')
            store.db.execute('DELETE FROM kv WHERE k=?', (KEY,))
    for _ in range(2):
        with closing(Store(tmp_path)) as store:
            mon = row(store, 'pokemon', 25)
            assert (mon['caught'], mon['gift']) == (1, 1)
            assert mon['wild'] is None
            assert row(store, 'items', 4)['bought'] is None


def test_receipts_survive_reopen_and_journal_pruning(tmp_path):
    with closing(Store(tmp_path)) as store:
        tracker = ActivityLedger(store, sorted(SUPPORTED)[0])
        store.set(KEY, {'started_at': 123, 'available': True})
        action(tracker, 'wild')
        store.prune_events(0)
    with closing(Store(tmp_path)) as store:
        tracker = ActivityLedger(store, sorted(SUPPORTED)[0])
        action(tracker, 'wild')
        assert row(store, 'pokemon', 25)['wild'] == 1
        action(tracker, 'wild', sequence=2)
        assert row(store, 'pokemon', 25)['wild'] == 2


def test_unsupported_cartridge_does_not_install_hooks(ledger):
    ActivityLedger(ledger.store, 'unknown').attach(SimpleNamespace())
    assert not status(ledger.store)['available']


def test_signature_mismatch_attaches_nothing(ledger):
    class Memory:
        def __getitem__(self, _):
            return bytes(0x4000)
    with pytest.raises(ValueError, match='signature mismatch'):
        ledger.attach(SimpleNamespace(memory=Memory()))


def test_verified_rom_hooks_coexist_without_changing_ram(tmp_path):
    rom = Path('roms/pokered.gb')
    if not rom.is_file():
        pytest.skip('Private ROM unavailable')
    from pyboy import PyBoy
    from pokesim.shiny import ShinyTracker
    from pokesim.legendary_returns import StepTracker
    import hashlib
    sha = hashlib.sha1(rom.read_bytes()).hexdigest()
    with closing(Store(tmp_path)) as store:
        pb = PyBoy(str(rom), window='null', ram_file=io.BytesIO(bytes(32768)))
        try:
            before = bytes(pb.memory[0xc000:0xe000])
            ActivityLedger(store, sha).attach(pb)
            ShinyTracker(store, sha).attach(pb)
            CatchTracker(store, sha).attach(pb)
            StepTracker(store, sha).attach(pb)
            assert bytes(pb.memory[0xc000:0xe000]) == before
            assert status(store)['available']
            assert status(store)['started_at'] is not None
            pb.tick(120, False)
        finally:
            pb.stop(save=False)


def test_failed_count_write_rolls_back_receipt(ledger, monkeypatch):
    from pokesim import activity_ledger
    def fail(*args):
        raise RuntimeError('Simulated failed write')
    monkeypatch.setattr(activity_ledger, 'increment', fail)
    with pytest.raises(RuntimeError, match='failed write'):
        action(ledger, 'wild')
    assert ledger.store.db.execute('SELECT COUNT(*) FROM activity_receipts').fetchone()[0] == 0
    assert row(ledger.store, 'pokemon', 25)['wild'] == 0


def test_successful_capture_uses_bag_slot_not_overwritten_species(ledger):
    memory = bytearray(65536)
    memory[0xd057] = 1
    memory[0xcf91] = 34
    memory[0xcf92] = 1
    memory[0xd31d] = 2
    memory[0xd31e:0xd322] = bytes((20, 5, 4, 10))
    ledger.completed(('ball', SimpleNamespace(memory=memory)))
    assert row(ledger.store, 'items', 4)['used'] == 1
    assert row(ledger.store, 'items', 34)['used'] == 0
