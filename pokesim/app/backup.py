"""Quiesced portable backups with checksummed, bounded restore."""
from __future__ import annotations

from contextlib import closing, contextmanager

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
import zipfile

from .registry import identifier

MAX_EXPANDED = 16 * 1024**3
RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + number for prefix in ('COM', 'LPT') for number in '123456789¹²³'
}


def file_checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def extract_archive(archive, destination, max_expanded=MAX_EXPANDED):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 100000:
            raise ValueError('Archive has too many files')
        for info in bundle.infolist():
            relative = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            total += info.file_size
            components = info.orig_filename.rstrip('/').split('/')
            unsafe_component = any(
                not part or part in {'.', '..'} or part.endswith((' ', '.'))
                or part.split('.')[0].upper() in RESERVED_NAMES
                or any(ord(character) < 32 or ord(character) == 127 or character in '<>"|?*' for character in part)
                for part in components)
            if (relative.is_absolute() or '..' in relative.parts or '\\' in info.orig_filename or '\x00' in info.orig_filename
                    or ':' in info.filename or unsafe_component
                    or mode & 0o170000 == 0o120000 or total > max_expanded):
                raise ValueError('Archive contains unsafe paths or exceeds the expanded size limit')
            path = destination.joinpath(*relative.parts)
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != destination):
                raise ValueError('Archive contains unsafe paths through a symbolic link')
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                if path.exists():
                    raise ValueError('Archive contains duplicate files')
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
    return destination


def create_backup(manager):
    with manager.maintenance, manager.registry.lock:
        if manager.registry.transactions(unresolved=True):
            raise ValueError('Resolve pending interactions before creating a backup')
        manager.suspended = True
        running = list(manager.supervisor.children)
        playback = {}
        try:
            for aid in running:
                status = manager.supervisor.child(aid).request('GET', '/api/summary', timeout=5)
                playback[aid] = 'take_control' if status.get('manual_mode') else 'pause' if status.get('paused') else None
            for aid in running:
                manager.supervisor.stop(aid, preserve_desired=True)
            bid = identifier()
            backups = manager.root / 'backups'
            backups.mkdir(exist_ok=True)
            destination = backups / (bid + '.zip')
            # Stage beside the archive, never in /tmp: the container mounts /tmp as a 256 MB
            # tmpfs, so staging a library of any real size there fails in RAM.
            with tempfile.TemporaryDirectory(prefix='.pokesim-backup-', dir=backups) as temporary:
                staging = Path(temporary)
                with closing(sqlite3.connect(staging / 'app.sqlite')) as target:
                    with manager.registry.lock:
                        manager.registry.db.backup(target)
                for name in ('assets', 'adventures', 'interactions', 'legacy_imports'):
                    source = manager.root / name
                    if source.exists():
                        # A sprite download can publish its staged directory while a backup runs.
                        # Only completed packs belong in the snapshot.
                        shutil.copytree(source, staging / name, ignore=shutil.ignore_patterns('*.lock', '*.log', '.install-*'))
                files = {}
                for path in staging.rglob('*'):
                    if path.is_file():
                        files[path.relative_to(staging).as_posix()] = file_checksum(path)
                manifest = {'format': 1, 'id': bid, 'created_at': time.time(), 'files': files}
                (staging / 'backup.json').write_text(json.dumps(manifest, indent=2))
                pending = backups / (bid + '.pending')
                with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    for path in staging.rglob('*'):
                        if path.is_file():
                            archive.write(path, path.relative_to(staging))
                pending.replace(destination)
            return {'id': bid, 'path': str(destination), 'created_at': manifest['created_at']}
        finally:
            manager.suspended = False
            for aid in running:
                try:
                    manager.supervisor.start(aid)
                    if playback.get(aid):
                        manager.supervisor.child(aid).request('POST', '/api/control', {'action': playback[aid]})
                except Exception as error:
                    manager.registry.update(aid, state='failed', error=str(error))


def restore_backup(archive, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore requires an empty destination directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pokesim-restore-', dir=destination.parent) as temporary:
        staging = extract_archive(archive, Path(temporary) / 'verified')
        manifest = json.loads((staging / 'backup.json').read_text())
        if not isinstance(manifest, dict) or manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
            raise ValueError('Unsupported backup format')
        actual = {p.relative_to(staging).as_posix() for p in staging.rglob('*') if p.is_file()} - {'backup.json'}
        if actual != set(manifest['files']) or 'app.sqlite' not in actual:
            raise ValueError('Backup file list is incomplete')
        for relative, expected in manifest['files'].items():
            if file_checksum(staging / relative) != expected:
                raise ValueError(f'Backup verification failed for {relative}')
        with closing(sqlite3.connect(staging / 'app.sqlite')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup database is damaged')
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
    return destination


def _backup_adventures(root):
    """Read only the metadata needed to choose a saved adventure."""
    from .registry import validate_id
    with closing(sqlite3.connect(f'file:{root / "app.sqlite"}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT id,name,version,rom_id,settings,summary FROM adventures').fetchall()
    result = []
    for row in rows:
        item = dict(row)
        validate_id(item['id'])
        rom_id = item['rom_id']
        if not isinstance(rom_id, str) or len(rom_id) != 64 or any(c not in '0123456789abcdef' for c in rom_id):
            raise ValueError('Backup contains an invalid ROM identifier')
        item['settings'] = json.loads(item['settings'])
        if not isinstance(item['settings'], dict) or not isinstance(item['name'], str):
            raise ValueError('Backup contains invalid adventure metadata')
        item['summary'] = json.loads(item['summary']) if item['summary'] else {}
        item['restorable'] = (root / 'adventures' / item['id'] / 'pokesim.sqlite').is_file()
        result.append(item)
    return result


@contextmanager
def _verified_backup(manager, archive):
    try:
        with tempfile.TemporaryDirectory(prefix='.pokesim-verify-', dir=manager.root) as temporary:
            root = restore_backup(archive, Path(temporary) / 'verified')
            yield root
    except (zipfile.BadZipFile, sqlite3.DatabaseError, FileNotFoundError, UnicodeError) as error:
        raise ValueError('Choose a complete, valid PokeSim backup ZIP') from error


def inspect_backup(manager, archive):
    with _verified_backup(manager, archive) as root:
        manifest = json.loads((root / 'backup.json').read_text())
        created_at = manifest.get('created_at')
        if type(created_at) not in (int, float) or not math.isfinite(created_at) or not 0 <= created_at <= time.time() + 86400:
            raise ValueError('Backup contains an invalid creation date')
        return {'created_at': created_at, 'adventures': [
            {key: item[key] for key in ('id', 'name', 'version', 'restorable')}
            for item in _backup_adventures(root)]}


def load_backup_adventure(manager, archive, adventure_id, name, request_id):
    """Load a verified save as a stopped, isolated copy without replacing live data."""
    from .migration import import_directory
    from .registry import digest, validate_id
    validate_id(adventure_id)
    validate_id(request_id)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError('Choose an adventure name of 1 to 120 characters')
    fingerprint = digest({'backup': Path(archive).stem, 'adventure': adventure_id, 'name': name.strip()})
    with manager.maintenance, manager.registry.lock:
        manager.check_available()
        previous = manager.registry.db.execute('SELECT * FROM operations WHERE id=?', (request_id,)).fetchone()
        if previous:
            if previous['kind'] != 'backup-load' or previous['digest'] != fingerprint:
                raise ValueError('This request ID already belongs to another operation')
            return manager.registry.adventure(json.loads(previous['result'])['id'])
        with _verified_backup(manager, archive) as root:
            row = next((item for item in _backup_adventures(root) if item['id'] == adventure_id), None)
            if not row or not row['restorable']:
                raise ValueError('This backup does not contain that saved adventure')
            settings = manager.validate_adventure_settings({**row['settings'], 'auto_start': False})
            rom = root / 'assets' / 'roms' / row['rom_id'] / 'rom.gb'
            if file_checksum(rom) != row['rom_id']:
                raise ValueError('The backup ROM does not match this adventure')
            restored = import_directory(manager, root / 'adventures' / adventure_id,
                                        rom=rom,
                                        name=name.strip(), stopped=True)
            restored = manager.registry.update(restored['id'], settings=settings, summary=row['summary'], provenance={
                'backup_id': Path(archive).stem, 'source_adventure': adventure_id,
                'trading_blocked': True, 'reason': 'Restored backup copies do not automatically trade'})
            with manager.registry.db:
                manager.registry.db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)',
                                            (request_id, 'backup-load', fingerprint, json.dumps({'id': restored['id']})))
            return restored
