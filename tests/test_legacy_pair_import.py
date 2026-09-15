"""Resolved legacy peer evidence must agree before either import becomes visible."""
from hashlib import sha1, sha256
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from pokesim.app.legacy_import import import_pair, validate_pair
from pokesim.app.registry import Registry
from pokesim.checkpoints import CheckpointStore
from pokesim.store import Store


@pytest.fixture
def legacy(tmp_path):
    coordinator = tmp_path / 'legacy-coordinator'
    coordinator.mkdir()
    (coordinator / 'public').mkdir()
    (coordinator / 'policy.json').write_text(json.dumps({'peers': {'red': {}, 'blue': {}}}))
    (coordinator / 'public' / 'status.json').write_text(json.dumps({'history': [{'id': '12345'}]}))
    work = coordinator / 'transactions' / '12345'
    sources, roms, states, hashes = {}, {}, {}, {}
    for name in ('red', 'blue'):
        rom = tmp_path / f'{name}.gb'
        rom.write_bytes(name.encode())
        roms[name] = rom
        source = tmp_path / f'legacy-{name}'
        store = Store(source)
        store.set('trade_barrier', '12345')
        with store.lock, store.db:
            store.db.execute('CREATE TABLE completed_trades (id TEXT PRIMARY KEY)')
            store.db.execute('INSERT INTO completed_trades VALUES (?)', ('trade:12345',))
        store.close()
        before = Store(work / 'before' / name)
        before.close()
        metadata = {'rom_sha1': sha1(rom.read_bytes()).hexdigest(), 'pyboy_version': '2.7.0',
                    'policy': 'strategic', 'policy_state': {}, 'run_memory': {}, 'trade_id': '12345'}
        path = CheckpointStore(work / 'after' / name).write_checkpoint(b'committed-' + name.encode(), metadata)
        states[name], hashes[name] = str(path), sha256(path.read_bytes()).hexdigest()
        CheckpointStore(source / 'states').write_checkpoint(b'progressed-' + name.encode(), metadata)
        sources[name] = source
    (work / 'result.json').write_text(json.dumps({'id': '12345', 'status': 'staged', 'states': states, 'hashes': hashes}))
    registry = Registry(tmp_path / 'application')
    class Assets:
        def install_rom(self, raw):
            return registry.add_rom(sha256(raw).hexdigest(), sha1(raw).hexdigest(), raw.decode())
    manager = SimpleNamespace(root=registry.root, registry=registry, assets=Assets(),
        maintenance=threading.RLock(), suspended=False, validate_adventure_settings=lambda value: value)
    yield manager, sources, roms, coordinator
    registry.db.close()


def test_pair_registration_preserves_history_and_unblocks_both(legacy):
    manager, sources, roms, coordinator = legacy
    imported = import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True,
                           request_id='a' * 32)
    assert len(imported) == 2
    assert all(row['state'] == 'stopped' and not row['provenance']['trading_blocked'] for row in imported)
    assert len({row['provenance']['legacy_group_id'] for row in imported}) == 1
    for row in imported:
        with sqlite3.connect(manager.root / 'adventures' / row['id'] / 'pokesim.sqlite') as db:
            assert db.execute('SELECT id FROM completed_trades').fetchall() == [('trade:12345',)]
        peer = row['version']
        source_state = CheckpointStore(sources[peer] / 'states').latest_state()
        copied_state = manager.root / 'adventures' / row['id'] / 'states' / source_state.name
        assert copied_state.read_bytes() == source_state.read_bytes()
    assert imported == import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator,
                                   stopped=True, request_id='a' * 32)
    assert len(manager.registry.adventures()) == 2


def test_stopped_confirmation_required(legacy):
    manager, sources, roms, coordinator = legacy
    with pytest.raises(ValueError, match='stopped'):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator)
    assert manager.registry.adventures() == []


@pytest.mark.parametrize('fault', ['active', 'hold', 'barrier', 'lineage', 'status', 'hash', 'rom'])
def test_incomplete_legacy_evidence_never_imports_either_peer(legacy, fault):
    manager, sources, roms, coordinator = legacy
    if fault == 'active':
        (coordinator / 'active.json').write_text('{}')
    elif fault in {'hold', 'barrier'}:
        store = Store(sources['red'])
        store.set('trade_hold' if fault == 'hold' else 'trade_barrier', {'id': '12345'} if fault == 'hold' else 'other')
        store.close()
    elif fault == 'lineage':
        with sqlite3.connect(sources['red'] / 'pokesim.sqlite') as db:
            db.execute('INSERT INTO completed_trades VALUES (?)', ('trade:unknown',))
    elif fault == 'status':
        (coordinator / 'public' / 'status.json').write_text('{"history": []}')
    elif fault == 'hash':
        path = next((coordinator / 'transactions' / '12345' / 'after' / 'red').glob('*.state'))
        path.write_bytes(b'corrupted')
    else:
        roms['red'].write_bytes(b'wrong-rom')
    with pytest.raises(ValueError):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
    assert manager.registry.adventures() == []
    assert not manager.suspended


def test_copy_failure_cannot_register_half_a_pair(legacy, monkeypatch):
    manager, sources, roms, coordinator = legacy
    import pokesim.app.legacy_import as importer
    copy = importer._copy
    count = 0
    def fail_second(source, destination):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError('Injected copy failure')
        copy(source, destination)
    monkeypatch.setattr(importer, '_copy', fail_second)
    with pytest.raises(OSError, match='copy failure'):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
    assert manager.registry.adventures() == []


def test_peer_lineage_cannot_be_inferred_without_before_database(legacy):
    manager, sources, roms, coordinator = legacy
    (coordinator / 'transactions' / '12345' / 'before' / 'blue' / 'pokesim.sqlite').unlink()
    with pytest.raises(ValueError, match='missing'):
        validate_pair(sources, roms, coordinator)


def test_request_id_cannot_be_reused_with_changed_names(legacy):
    manager, sources, roms, coordinator = legacy
    import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True,
                request_id='a' * 32)
    with pytest.raises(ValueError, match='different sources'):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True,
                    request_id='a' * 32, names={'red': 'Changed'})


def test_database_failure_rolls_back_both_import_rows(legacy):
    manager, sources, roms, coordinator = legacy
    connection = manager.registry.db
    class FailSecondAdventure:
        calls = 0
        def __getattr__(self, name):
            return getattr(connection, name)
        def __enter__(self):
            connection.__enter__()
            return self
        def __exit__(self, *args):
            return connection.__exit__(*args)
        def execute(self, sql, *args):
            if sql.startswith('INSERT INTO adventures'):
                self.calls += 1
                if self.calls == 2:
                    raise sqlite3.OperationalError('Injected registry failure')
            return connection.execute(sql, *args)
    manager.registry.db = FailSecondAdventure()
    with pytest.raises(sqlite3.OperationalError, match='registry failure'):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
    assert manager.registry.adventures() == []
    assert list((manager.root / 'adventures').iterdir()) == []


@pytest.mark.parametrize('kind', ['mew_event', 'league_reward'])
def test_reward_barrier_lineage_is_preserved(legacy, kind):
    manager, sources, roms, coordinator = legacy
    result_path = coordinator / 'transactions' / '12345' / 'result.json'
    result = json.loads(result_path.read_text())
    result['kind'] = kind
    result_path.write_text(json.dumps(result))
    (coordinator / 'public' / 'status.json').write_text(json.dumps({'history': [], 'events': [{'id': '12345'}]}))
    for source in sources.values():
        store = Store(source)
        with store.lock, store.db:
            store.db.execute('DELETE FROM completed_trades')
            store.db.execute('CREATE TABLE completed_events (id TEXT PRIMARY KEY)')
            store.db.execute('INSERT INTO completed_events VALUES (?)', ('12345',))
        store.set('league_rewards', {'earned': 3, 'delivered': 2})
        store.close()
    rows = import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
    for row in rows:
        store = Store(manager.root / 'adventures' / row['id'])
        assert store.get('league_rewards') == {'earned': 3, 'delivered': 2}
        assert not row['provenance']['trading_blocked']
        store.close()


def test_running_coordinator_lock_blocks_import(legacy):
    from pokesim.platform_io import lock_file
    manager, sources, roms, coordinator = legacy
    with (coordinator / 'lock').open('a+b') as stream:
        lock_file(stream)
        with pytest.raises(BlockingIOError):
            import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
    assert manager.registry.adventures() == []
    assert not manager.suspended


def test_destination_inside_source_is_rejected_before_copy(legacy):
    manager, sources, roms, coordinator = legacy
    manager.root = sources['red'] / 'nested-application'
    with pytest.raises(ValueError, match='legacy source'):
        import_pair(manager, sources=sources, roms=roms, coordinator_root=coordinator, stopped=True)
