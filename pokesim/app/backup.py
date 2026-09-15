"""Quiesced portable backups with checksummed, bounded restore."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
import zipfile

from .registry import identifier

MAX_EXPANDED = 16 * 1024**3


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
            if (relative.is_absolute() or '..' in relative.parts or '\\' in info.filename
                    or ':' in info.filename or mode & 0o170000 == 0o120000 or total > max_expanded):
                raise ValueError('Archive contains unsafe paths or exceeds the expanded size limit')
            path = destination.joinpath(*relative.parts)
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
                status = manager.supervisor.child(aid).request('GET', '/api/state', timeout=5)
                playback[aid] = 'take_control' if status.get('manual_mode') else 'pause' if status.get('paused') else None
            for aid in running:
                manager.supervisor.stop(aid, preserve_desired=True)
            bid = identifier()
            backups = manager.root / 'backups'
            backups.mkdir(exist_ok=True)
            destination = backups / (bid + '.zip')
            with tempfile.TemporaryDirectory(prefix='pokesim-backup-') as temporary:
                staging = Path(temporary)
                with sqlite3.connect(staging / 'app.sqlite') as target:
                    with manager.registry.lock:
                        manager.registry.db.backup(target)
                for name in ('assets', 'adventures', 'interactions', 'legacy_imports'):
                    source = manager.root / name
                    if source.exists():
                        shutil.copytree(source, staging / name, ignore=shutil.ignore_patterns('*.lock', '*.log'))
                files = {}
                for path in staging.rglob('*'):
                    if path.is_file():
                        files[str(path.relative_to(staging))] = hashlib.sha256(path.read_bytes()).hexdigest()
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
        if manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
            raise ValueError('Unsupported backup format')
        actual = {str(p.relative_to(staging)) for p in staging.rglob('*') if p.is_file()} - {'backup.json'}
        if actual != set(manifest['files']) or 'app.sqlite' not in actual:
            raise ValueError('Backup file list is incomplete')
        for relative, expected in manifest['files'].items():
            if hashlib.sha256((staging / relative).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Backup verification failed for {relative}')
        with sqlite3.connect(staging / 'app.sqlite') as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup database is damaged')
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
    return destination
