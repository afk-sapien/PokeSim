"""Copy stopped legacy adventures without changing their source."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from ..runtime.simulation import AdventureLock
from .registry import identifier
from .backup import extract_archive


def import_directory(manager, source, *, rom=None, name=None, stopped=False):
    source = Path(source).resolve()
    if not stopped:
        raise ValueError('Confirm the old service is stopped before importing its directory')
    desktop = (source / 'adventure' / 'pokesim.sqlite').is_file()
    data = source / 'adventure' if desktop else source
    if not (data / 'pokesim.sqlite').is_file():
        raise ValueError('Choose a desktop adventure folder or a legacy data folder with pokesim.sqlite')
    rom = Path(rom).resolve() if rom else source / 'rom.gb'
    if not rom.is_file():
        raise ValueError('The import needs its original ROM file')
    with manager.maintenance, AdventureLock(data):
        if manager.suspended:
            raise ValueError('Another maintenance operation is running')
        manager.suspended = True
        try:
            with sqlite3.connect(f'file:{data / "pokesim.sqlite"}?mode=ro', uri=True) as db:
                values = {row[0]: json.loads(row[1]) for row in db.execute('SELECT k,v FROM kv')}
                if values.get('trade_hold'):
                    raise ValueError('Resolve the old coordinator transaction before importing')
                trading_blocked = bool(values.get('trade_barrier'))
            starter = 'random'
            if desktop and (source / 'settings.json').is_file():
                starter = json.loads((source / 'settings.json').read_text()).get('starter', starter)
            asset = manager.assets.install_rom(rom.read_bytes())
            settings = manager.validate_adventure_settings({'starter': starter})
            aid_request = identifier()
            with tempfile.TemporaryDirectory(prefix='pokesim-import-') as temporary:
                stage = Path(temporary) / 'adventure'
                shutil.copytree(data, stage, ignore=shutil.ignore_patterns('runtime.lock', 'desktop.lock'))
                with sqlite3.connect(stage / 'pokesim.sqlite') as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('The copied adventure database failed validation')
                from ..checkpoints import CheckpointStore
                checkpoints = CheckpointStore(stage / 'states')
                for path in checkpoints.autosaves():
                    checkpoints.checkpoint_metadata(path)
                adventure = manager.registry.create(name or source.name, asset['id'], settings, aid_request)
                target = manager.root / 'adventures' / adventure['id']
                try:
                    shutil.copytree(stage, target, dirs_exist_ok=True)
                except Exception as error:
                    manager.registry.update(adventure['id'], state='failed', error='Import failed: ' + str(error))
                    raise
                return manager.registry.update(adventure['id'], provenance={
                    'imported_from': source.name, 'legacy_trade_barrier': values.get('trade_barrier'),
                    'trading_blocked': trading_blocked,
                    'reason': 'Legacy trading peers need coherent migration before new exchanges' if trading_blocked else None})
        finally:
            manager.suspended = False


def import_archive(manager, archive):
    with tempfile.TemporaryDirectory(prefix='pokesim-import-') as temporary:
        root = extract_archive(archive, temporary, max_expanded=2 * 1024**3)
        if (root / 'backup.json').is_file():
            raise ValueError('This is a whole-application backup. Restore it to a new directory with pokesim restore.')
        if not (root / 'rom.gb').is_file():
            raise ValueError('A legacy import archive must include rom.gb and its adventure data')
        return import_directory(manager, root, name='Imported adventure', stopped=True)
