"""Validate and copy a resolved legacy trading pair as one stopped import group."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from ..checkpoints import CheckpointStore
from ..platform_io import lock_file, sync_directory
from ..runtime.simulation import AdventureLock
from .registry import digest, identifier, validate_id

PEERS = ('red', 'blue')


@contextmanager
def _database(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('A retained legacy peer database is missing')
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        yield db
    except sqlite3.DatabaseError as error:
        raise ValueError('A legacy peer database could not be validated') from error
    finally:
        if db is not None:
            db.close()


def _history(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {}
    for table in ('completed_trades', 'completed_events'):
        result[table] = {row[0] for row in db.execute(f'SELECT id FROM {table}')} if table in tables else set()
    return result


def _read_source(source):
    with _database(source / 'pokesim.sqlite') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Legacy source database failed integrity validation')
        values = {key: json.loads(value) for key, value in db.execute('SELECT k,v FROM kv')}
        if values.get('trade_hold'):
            raise ValueError('Resolve every legacy participant hold before import')
        preparation = values.get('interaction_preparation') or {}
        if preparation.get('phase') in {'travelling', 'storage', 'rendezvous', 'ready'}:
            raise ValueError('Resolve managed preparation before legacy import')
        history = _history(db)
    checkpoints = CheckpointStore(source / 'states')
    latest = checkpoints.latest_state()
    if latest is None:
        raise ValueError('Each legacy peer needs a verified checkpoint')
    metadata = checkpoints.checkpoint_metadata(latest)
    if not metadata or metadata.get('trade_id') != values.get('trade_barrier'):
        raise ValueError('Latest checkpoint does not match its legacy trade barrier')
    return values, history, latest, metadata


def validate_pair(sources, roms, coordinator_root):
    """Require retained coordinator evidence and both peers' exact completion lineage."""
    coordinator = Path(coordinator_root).resolve()
    if set(sources) != set(PEERS) or set(roms) != set(PEERS):
        raise ValueError('Supply explicit red and blue source directories and ROM files')
    sources = {key: Path(value).resolve() for key, value in sources.items()}
    roms = {key: Path(value).resolve() for key, value in roms.items()}
    if (sources['red'] == sources['blue'] or sources['red'] in sources['blue'].parents
            or sources['blue'] in sources['red'].parents):
        raise ValueError('Legacy peer directories must be distinct and nonoverlapping')
    if (coordinator / 'active.json').exists():
        raise ValueError('Resolve the active legacy coordinator transaction before import')
    policy = json.loads((coordinator / 'policy.json').read_text())
    if set(policy.get('peers', {})) != set(PEERS):
        raise ValueError('Legacy coordinator does not identify this two-peer protocol')
    status = json.loads((coordinator / 'public' / 'status.json').read_text())
    records = {name: _read_source(sources[name]) for name in PEERS}
    barriers = {record[0].get('trade_barrier') for record in records.values()}
    if len(barriers) != 1:
        raise ValueError('Legacy peers have different latest trade barriers')
    transaction = next(iter(barriers))
    if not isinstance(transaction, str) or not transaction.isdigit():
        raise ValueError('A retained legacy transaction is required to prove pair lineage')
    completed = [row for row in status.get('history', []) + status.get('events', [])
                 if row.get('id') == transaction]
    if len(completed) != 1:
        raise ValueError('Coordinator history does not prove the latest operation completed')
    work = coordinator / 'transactions' / transaction
    result = json.loads((work / 'result.json').read_text())
    if (result.get('status') != 'staged' or result.get('id') != transaction
            or set(result.get('states', {})) != set(PEERS)
            or set(result.get('hashes', {})) != set(PEERS)):
        raise ValueError('Coordinator result is incomplete or names different participants')
    kind = result.get('kind', 'trade')
    if kind not in {'trade', 'mew_event', 'league_reward'}:
        raise ValueError('Unsupported legacy operation kind')
    marker_table = 'completed_trades' if kind == 'trade' else 'completed_events'
    marker = 'trade:' + transaction if kind == 'trade' else transaction
    evidence = {'transaction_id': transaction, 'kind': kind, 'peers': {},
                'coordinator_result_sha256': hashlib.sha256((work / 'result.json').read_bytes()).hexdigest(),
                'completed_status': completed[0]}
    for name in PEERS:
        values, history, latest, metadata = records[name]
        original = work / 'after' / name / Path(result['states'][name]).name
        expected = result['hashes'][name]
        if hashlib.sha256(original.read_bytes()).hexdigest() != expected:
            raise ValueError('Retained legacy output checksum failed')
        output_metadata = CheckpointStore(original.parent).checkpoint_metadata(original)
        if not output_metadata or output_metadata.get('trade_id') != transaction:
            raise ValueError('Retained legacy output has incompatible provenance')
        rom_sha1 = hashlib.sha1(roms[name].read_bytes()).hexdigest()
        if metadata.get('rom_sha1') != rom_sha1 or output_metadata.get('rom_sha1') != rom_sha1:
            raise ValueError('Legacy peer ROM does not match the retained lineage')
        if (metadata.get('pyboy_version') != output_metadata.get('pyboy_version')
                or metadata.get('policy') != output_metadata.get('policy')):
            raise ValueError('Legacy checkpoint runtime changed without recorded migration')
        with _database(work / 'before' / name / 'pokesim.sqlite') as db:
            previous = _history(db)
        previous[marker_table].add(marker)
        if history != previous:
            raise ValueError('Legacy completion history differs from the retained peer lineage')
        evidence['peers'][name] = {'checkpoint': latest.name, 'checkpoint_sha256': metadata['sha256'],
            'committed_checkpoint_sha256': expected, 'rom_sha1': rom_sha1,
            'policy': metadata.get('policy'),
            'completed_trades': sorted(history['completed_trades']),
            'completed_events': sorted(history['completed_events'])}
    return evidence


def _copy(source, destination):
    total = 0
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Legacy import does not follow symbolic links')
        if path.is_file():
            total += path.stat().st_size
        elif not path.is_dir():
            raise ValueError('Legacy import only accepts regular files and directories')
        if total > 2 * 1024**3:
            raise ValueError('Legacy adventure exceeds the 2 GiB import limit')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('runtime.lock', 'desktop.lock'))
    with _database(destination / 'pokesim.sqlite') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Copied legacy database failed integrity validation')
    checkpoints = CheckpointStore(destination / 'states')
    for checkpoint in checkpoints.autosaves():
        checkpoints.checkpoint_metadata(checkpoint)


def import_pair(manager, *, sources, roms, coordinator_root, stopped=False, names=None, request_id=None):
    """Register both stopped copies together after validating the resolved old coordinator.

    Existing histories, rewind barriers, campaign rewards, and checkpoint bytes are
    preserved. Missing peer evidence never clears the single-import trading block.
    """
    if not stopped:
        raise ValueError('Confirm both legacy services and their coordinator are stopped before import')
    if set(sources) != set(PEERS) or set(roms) != set(PEERS):
        raise ValueError('Supply explicit red and blue source directories and ROM files')
    sources = {name: Path(path).resolve() for name, path in sources.items()}
    coordinator = Path(coordinator_root).resolve()
    request_id = validate_id(request_id or identifier())
    names = {name: str((names or {}).get(name, 'Imported ' + name.title())).strip() for name in PEERS}
    if any(not value or len(value) > 120 for value in names.values()):
        raise ValueError('Imported adventure names must contain 1 to 120 characters')
    if any(manager.root.resolve() == source or manager.root.resolve() in source.parents
           or source in manager.root.resolve().parents for source in sources.values()):
        raise ValueError('Use the legacy source directories, not existing managed adventures')
    if not (coordinator / 'policy.json').is_file():
        raise ValueError('A retained legacy coordinator directory is required')
    with manager.maintenance, ExitStack() as stack:
        if manager.suspended:
            raise ValueError('Another maintenance operation is running')
        manager.suspended = True
        try:
            lock = stack.enter_context((coordinator / 'lock').open('a+b'))
            lock_file(lock)
            for source in sorted(sources.values()):
                stack.enter_context(AdventureLock(source))
            evidence = validate_pair(sources, roms, coordinator)
            fingerprint = digest({'sources': {key: str(value) for key, value in sources.items()},
                'names': names, 'evidence': evidence})
            registry = manager.registry
            with registry.lock:
                previous = registry.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['kind'] != 'import_pair' or previous['digest'] != fingerprint:
                    raise ValueError('This import request ID already names different sources')
                return [registry.adventure(aid) for aid in json.loads(previous['result'])['ids']]
            settings_by_peer = {name: manager.validate_adventure_settings(
                {'policy': evidence['peers'][name]['policy']}) for name in PEERS}
            assets = {name: manager.assets.install_rom(Path(roms[name]).read_bytes()) for name in PEERS}
            if any(assets[name]['version'] != name for name in PEERS):
                raise ValueError('The explicit legacy peer mapping does not match the ROM editions')
            ids = {name: identifier() for name in PEERS}
            adventures = []
            with tempfile.TemporaryDirectory(prefix='.legacy-import-', dir=manager.root) as temporary:
                stage = Path(temporary)
                for name in PEERS:
                    settings = settings_by_peer[name]
                    _copy(sources[name], stage / name)
                    provenance = {'imported_from': sources[name].name, 'legacy_group_id': request_id,
                        'legacy_peer': name, 'legacy_peers': ids, 'legacy_trade_barrier': evidence['transaction_id'],
                        'trading_blocked': False, 'legacy_evidence_digest': digest(evidence)}
                    adventure = {'id': ids[name], 'campaign_id': identifier(), 'name': names[name],
                        'rom_id': assets[name]['id'], 'version': assets[name]['version'], 'settings': settings,
                        'desired_state': 'stopped', 'state': 'stopped', 'generation': None, 'archived': False,
                        'error': None, 'summary': {}, 'provenance': provenance, 'created_at': time.time(),
                        'url': f'/games/{ids[name]}/'}
                    CheckpointStore.atomic_write(stage / name / 'adventure.json', json.dumps(adventure, indent=2).encode())
                    adventures.append(adventure)
                copied_evidence = validate_pair({name: stage / name for name in PEERS}, roms, coordinator)
                if copied_evidence != evidence:
                    raise ValueError('Legacy source evidence changed while copying')
                # Source game state remains unchanged. Registry visibility is a
                # single database commit after both complete directories are ready.
                published = []
                try:
                    for name in PEERS:
                        target = manager.root / 'adventures' / ids[name]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        (stage / name).rename(target)
                        published.append(target)
                    evidence_root = manager.root / 'legacy_imports' / request_id
                    evidence_root.mkdir(parents=True, exist_ok=False)
                    CheckpointStore.atomic_write(evidence_root / 'evidence.json', json.dumps(evidence, indent=2).encode())
                    sync_directory(manager.root / 'adventures')
                    with registry.lock, registry.db:
                        for item in adventures:
                            registry.db.execute('''INSERT INTO adventures
                                (id,campaign_id,name,rom_id,version,settings,desired_state,state,generation,
                                 archived,error,summary,provenance,created_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (item['id'], item['campaign_id'], item['name'], item['rom_id'], item['version'],
                                 json.dumps(item['settings']), 'stopped', 'stopped', None, 0, None, '{}',
                                 json.dumps(item['provenance']), item['created_at']))
                        registry.db.execute('INSERT INTO operations VALUES (?,?,?,?)',
                            (request_id, 'import_pair', fingerprint, json.dumps({'ids': list(ids.values())})))
                except BaseException:
                    with registry.lock:
                        registered = registry.db.execute('SELECT 1 FROM operations WHERE id=?', (request_id,)).fetchone()
                    if not registered:
                        for path in published:
                            shutil.rmtree(path)
                        shutil.rmtree(manager.root / 'legacy_imports' / request_id, ignore_errors=True)
                    raise
            return [registry.adventure(ids[name]) for name in PEERS]
        finally:
            manager.suspended = False
