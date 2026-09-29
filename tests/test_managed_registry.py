import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from pokesim.app.registry import Registry, identifier
from pokesim.app.backup import extract_archive, restore_backup


def registry(tmp_path):
    result = Registry(tmp_path)
    result.add_rom('digest', 'sha1', 'red')
    return result


def test_create_is_durable_idempotent_and_rejects_changed_request(tmp_path):
    store = registry(tmp_path)
    request = identifier()
    first = store.create('Red one', 'digest', {'starter': 'random'}, request)
    assert store.create('Red one', 'digest', {'starter': 'random'}, request)['id'] == first['id']
    with pytest.raises(ValueError, match='different'):
        store.create('Red two', 'digest', {'starter': 'random'}, request)
    second = store.create('Red one', 'digest', {'starter': 'random'}, identifier())
    assert second['id'] != first['id']
    store.close()
    reopened = Registry(tmp_path)
    assert len(reopened.adventures()) == 2
    assert json.loads((tmp_path / 'adventures' / first['id'] / 'adventure.json').read_text())['campaign_id'] == first['campaign_id']
    reopened.close()


def test_commit_decision_cannot_reverse_after_restart(tmp_path):
    store = registry(tmp_path)
    tid = identifier()
    store.create_transaction(tid, {'participants': ['one', 'two']})
    store.update_transaction(tid, decision='COMMIT', phase='applying', result={'verified': True})
    store.close()
    store = Registry(tmp_path)
    with pytest.raises(ValueError, match='cannot change'):
        store.update_transaction(tid, decision='ABORT')
    assert store.transactions(True)[0]['decision'] == 'COMMIT'
    store.close()


def test_rejects_newer_schema(tmp_path):
    with sqlite3.connect(tmp_path / 'app.sqlite') as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError, match='newer'):
        Registry(tmp_path)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'x/../../escape', 'x\\escape', 'C:escape'])
def test_import_cannot_escape_destination(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        member = zipfile.ZipInfo('placeholder')
        member.filename = name
        output.writestr(member, b'invalid')
    with pytest.raises(ValueError, match='unsafe'):
        extract_archive(archive, tmp_path / 'output')


def test_restore_checks_content_before_publishing(tmp_path):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('backup.json', json.dumps({'format': 1, 'files': {'app.sqlite': 'wrong'}}))
        output.writestr('app.sqlite', b'not-a-database')
    destination = tmp_path / 'restore'
    with pytest.raises(ValueError, match='verification'):
        restore_backup(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize('speed', [None, 0, 4])
def test_legacy_global_speed_migrates_once_and_preserves_other_settings(tmp_path, speed):
    store = registry(tmp_path)
    first = store.create('Red', 'digest', {'speed': 8, 'mew_event': True}, identifier())
    second = store.create('Blue', 'digest', {}, identifier())
    store.update(second['id'], archived=True)
    with store.db:
        store.db.execute("DELETE FROM settings WHERE key='per_adventure_speed_v1'")
    if speed is not None:
        store.set_setting('speed', speed)
    store.set_setting('max_running', 1)
    store.close()
    store = Registry(tmp_path)
    expected = 1 if speed is None else speed
    assert store.adventure(first['id'])['settings'] == {'speed': expected, 'mew_event': True}
    assert store.adventure(second['id'])['settings']['speed'] == expected
    assert store.adventure(second['id'])['archived']
    assert store.setting('max_running') is None
    assert store.setting('speed') is None
    manifest = json.loads((tmp_path / 'adventures' / first['id'] / 'adventure.json').read_text())
    assert manifest['settings']['speed'] == expected
    store.update(first['id'], settings={'speed': 0.5})
    store.close()
    store = Registry(tmp_path)
    assert store.adventure(first['id'])['settings']['speed'] == 0.5
    assert store.create('New', 'digest', {}, identifier())['settings']['speed'] == 1
    store.close()
