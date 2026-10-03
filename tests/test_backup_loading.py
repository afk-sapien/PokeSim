"""Loading individual adventures must preserve current progress and isolate copies."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest

from pokesim import desktop_setup
from pokesim.app.backup import create_backup
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier
from pokesim.store import Store


@pytest.fixture
def saved_library(tmp_path, monkeypatch):
    manager = Manager(tmp_path / 'library', 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    raw = b'backup-test-cartridge'
    monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Pokémon Red')
    asset = manager.assets.install_rom(raw)
    row = manager.registry.create('Original', asset['id'], {'speed': 4, 'auto_start': True}, identifier())
    with closing(Store(manager.root / 'adventures' / row['id'])) as store:
        store.set('test_progress', 100)
    manager.registry.set_setting('nickname_parts', {'nickname_prefixes': ['OLD'], 'nickname_suffixes': []})
    backup = create_backup(manager)
    with closing(Store(manager.root / 'adventures' / row['id'])) as store:
        store.set('test_progress', 200)
    manager.registry.set_setting('nickname_parts', {'nickname_prefixes': ['NEW'], 'nickname_suffixes': []})
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        yield manager, client, headers, row, backup


def test_load_backup_copy_preserves_source_and_settings_and_retries(saved_library):
    manager, client, headers, original, backup = saved_library
    route = f"/api/v1/backups/{backup['id']}"
    info = client.get(route + '/inspect')
    assert info.status_code == 200
    assert info.json()['adventures'] == [{'id': original['id'], 'name': 'Original', 'version': 'red', 'restorable': True}]
    payload = {'adventure_id': original['id'], 'name': 'Recovered', 'request_id': identifier()}
    assert client.post(route + '/load', json=payload).status_code == 403
    response = client.post(route + '/load', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    copy = response.json()
    assert copy['id'] != original['id'] and copy['campaign_id'] != original['campaign_id']
    assert copy['state'] == copy['desired_state'] == 'stopped'
    assert copy['settings']['auto_start'] is False and copy['settings']['speed'] == 4
    assert copy['provenance']['trading_blocked'] is True
    for row, value in [(original, 200), (copy, 100)]:
        with closing(Store(manager.root / 'adventures' / row['id'])) as store:
            assert store.get('test_progress') == value
    assert manager.registry.setting('nickname_parts')['nickname_prefixes'] == ['NEW']
    again = client.post(route + '/load', headers=headers, json=payload)
    assert again.json()['id'] == copy['id']
    assert len(manager.registry.adventures()) == 2
    assert client.post(route + '/load', headers=headers, json={**payload, 'name': 'Different'}).status_code == 409
    listed = client.get('/api/v1/backups').json()['backups'][0]
    assert listed['size_bytes'] == Path(backup['path']).stat().st_size


def test_upload_backup_and_reject_invalid_archives_without_artifacts(saved_library):
    manager, client, headers, original, backup = saved_library
    data = Path(backup['path']).read_bytes()
    response = client.post('/api/v1/backups/upload', content=data, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['adventures'][0]['id'] == original['id']
    assert response.json()['id'] != backup['id']
    assert len(list((manager.root / 'backups').glob('*.zip'))) == 2
    assert client.post('/api/v1/backups/upload', content=b'not a ZIP', headers=headers).status_code == 409
    tampered = manager.root / 'tampered.zip'
    with zipfile.ZipFile(backup['path']) as source, zipfile.ZipFile(tampered, 'w') as output:
        for name in source.namelist():
            raw = source.read(name)
            if name == 'backup.json':
                manifest = json.loads(raw)
                manifest['files']['app.sqlite'] = 'bad-checksum'
                raw = json.dumps(manifest).encode()
            output.writestr(name, raw)
    bad = client.post('/api/v1/backups/upload', content=tampered.read_bytes(), headers=headers)
    assert bad.status_code == 409 and 'verification failed' in bad.json()['detail']
    assert len(list((manager.root / 'backups').glob('*.zip'))) == 2
    assert not list((manager.root / 'backups').glob('*.pending'))
    assert not list(manager.root.glob('.pokesim-verify-*'))
    assert len(manager.registry.adventures()) == 1


def test_delete_backup_requires_csrf_and_preserves_adventures(saved_library):
    manager, client, headers, original, backup = saved_library
    route = f"/api/v1/backups/{backup['id']}"
    second = create_backup(manager)
    restored = client.post(route + '/load', headers=headers, json={
        'adventure_id': original['id'], 'name': 'Recovered', 'request_id': identifier()}).json()
    assert client.delete(route).status_code == 403
    assert Path(backup['path']).exists()
    response = client.delete(route, headers=headers)
    assert response.status_code == 200
    assert response.json() == {'deleted': backup['id']}
    assert not Path(backup['path']).exists()
    assert Path(second['path']).is_file()
    assert client.delete(route, headers=headers).status_code == 200
    assert client.get(route + '/download').status_code == 404
    assert client.get(route + '/inspect').status_code == 404
    assert [row['id'] for row in client.get('/api/v1/backups').json()['backups']] == [second['id']]
    for row, value in [(original, 200), (restored, 100)]:
        with closing(Store(manager.root / 'adventures' / row['id'])) as store:
            assert store.get('test_progress') == value
    assert manager.registry.setting('nickname_parts')['nickname_prefixes'] == ['NEW']


def test_delete_backup_rejects_invalid_ids(saved_library):
    manager, client, headers, original, backup = saved_library
    for bid in ['not-an-id', backup['id'] + '.zip', '..%2Fapp.sqlite']:
        assert client.delete('/api/v1/backups/' + bid, headers=headers).status_code in (404, 409)
    assert Path(backup['path']).is_file()
    assert manager.registry.adventure(original['id'])['name'] == 'Original'
