"""Resume permanent adventure deletion without reviving a partially removed game."""
import json
import logging
import shutil

from .registry import validate_id

log = logging.getLogger(__name__)

PREFIX = 'adventure-deletion:'


def _paths(manager, aid):
    source = manager.root / 'adventures' / aid
    trash = manager.root / '.deleted-adventures'
    target = trash / aid
    for path in (source.parent, source, trash, target):
        if path.is_symlink():
            raise ValueError('Adventure deletion refuses symbolic links')
    return source, target


def _finish(manager, aid):
    source, target = _paths(manager, aid)
    if source.exists():
        if target.exists():
            raise ValueError('Deletion has conflicting directories. Preserve both for recovery.')
        target.parent.mkdir(exist_ok=True)
        source.rename(target)
    # The durable intent remains until the directory is gone. A retry never starts a game.
    if target.exists():
        shutil.rmtree(target)
    with manager.registry.lock, manager.registry.db:
        manager.registry.db.execute('DELETE FROM adventures WHERE id=?', (aid,))
        manager.registry.db.execute('UPDATE settings SET value=? WHERE key=?',
                                    (json.dumps({'complete': True}), PREFIX + aid))
    with manager.supervisor.guard:
        manager.supervisor.children.pop(aid, None)
        manager.supervisor.retries.pop(aid, None)
        manager.supervisor.unhealthy_since.pop(aid, None)
    return {'deleted': aid}


def delete_adventure(manager, aid, confirmation):
    validate_id(aid)
    with manager.maintenance, manager.coordinator.guard, manager.supervisor._lock(aid):
        manager.check_available()
        marker = manager.registry.setting(PREFIX + aid)
        if marker and marker.get('complete'):
            return {'deleted': aid}
        row = manager.registry.adventure(aid)
        if confirmation != row['name']:
            raise ValueError('Type the adventure name to confirm permanent deletion')
        if row['state'] not in {'stopped', 'failed', 'deleting'} or row['desired_state'] != 'stopped':
            raise ValueError('Save and stop this adventure before deleting it')
        if manager.coordinator.reserved(aid):
            raise ValueError('Resolve this adventure\'s trade before deleting it')
        with manager.supervisor.guard:
            child = manager.supervisor.children.get(aid)
            if child and child.process is not None and child.process.poll() is None:
                raise ValueError('The adventure worker is still running')
        _paths(manager, aid)
        with manager.registry.lock, manager.registry.db:
            manager.registry.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)',
                                        (PREFIX + aid, json.dumps({'complete': False})))
            manager.registry.db.execute("UPDATE adventures SET state='deleting', archived=1 WHERE id=?", (aid,))
        return _finish(manager, aid)


def recover_deletions(manager):
    with manager.registry.lock:
        pending = [(row['key'][len(PREFIX):], json.loads(row['value'])) for row in
                   manager.registry.db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (PREFIX + '%',))]
    for aid, marker in pending:
        if not marker.get('complete'):
            try:
                _finish(manager, validate_id(aid))
            except (OSError, ValueError):
                log.exception('Adventure deletion needs a retry: %s', aid)
