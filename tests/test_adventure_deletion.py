from unittest.mock import Mock

import pytest

from test_managed_app import client, login
from pokesim.app.deletion import delete_adventure, recover_deletions, PREFIX
from pokesim.app.registry import identifier


def adventure(manager, name='Disposable'):
    manager.registry.add_rom('fixture-rom', 'sha1', 'red')
    row = manager.registry.create(name, 'fixture-rom', {}, identifier())
    path = manager.root / 'adventures' / row['id']
    (path / 'save.state').write_bytes(b'private save')
    return row, path


def test_delete_preserves_other_adventures_roms_backups_and_is_idempotent(client):
    http, manager = client
    row, path = adventure(manager)
    other, other_path = adventure(manager, 'Keep')
    backups = manager.root / 'backups'
    backups.mkdir(exist_ok=True)
    (backups / 'keep.zip').write_bytes(b'backup')
    route = '/api/v1/adventures/' + row['id']
    assert http.request('DELETE', route, json={'confirmation': row['name']}).status_code == 403
    headers = login(http, manager)
    assert http.request('DELETE', route, headers=headers, json={'confirmation': 'wrong'}).status_code == 409
    for _ in range(2):
        response = http.request('DELETE', route, headers=headers, json={'confirmation': row['name']})
        assert response.status_code == 200
        assert response.json() == {'deleted': row['id']}
    assert not path.exists()
    assert other_path.exists() and (backups / 'keep.zip').read_bytes() == b'backup'
    assert manager.registry.roms()[0]['id'] == 'fixture-rom'
    assert [game['id'] for game in manager.registry.adventures()] == [other['id']]


@pytest.mark.parametrize('state,desired', [('running','running'), ('stopping','stopped'), ('failed','running'), ('recovering','stopped')])
def test_delete_rejects_unstopped_adventure(client, state, desired):
    _, manager = client
    row, path = adventure(manager)
    manager.registry.update(row['id'], state=state, desired_state=desired)
    with pytest.raises(ValueError, match='stop'):
        delete_adventure(manager, row['id'], row['name'])
    assert path.exists()


def test_delete_rejects_reserved_or_live_worker(client, monkeypatch):
    _, manager = client
    row, path = adventure(manager)
    monkeypatch.setattr(manager.coordinator, 'reserved', lambda aid: True)
    with pytest.raises(ValueError, match='trade'):
        delete_adventure(manager, row['id'], row['name'])
    monkeypatch.setattr(manager.coordinator, 'reserved', lambda aid: False)
    manager.supervisor.children[row['id']] = Mock(process=Mock(poll=lambda: None))
    with pytest.raises(ValueError, match='worker'):
        delete_adventure(manager, row['id'], row['name'])
    manager.supervisor.children.clear()
    assert path.exists()


def test_interrupted_delete_is_archived_and_resumes(client, monkeypatch):
    _, manager = client
    row, path = adventure(manager)
    import pokesim.app.deletion as deletion
    original = deletion.shutil.rmtree
    monkeypatch.setattr(deletion.shutil, 'rmtree', Mock(side_effect=OSError('disk busy')))
    with pytest.raises(OSError):
        delete_adventure(manager, row['id'], row['name'])
    pending = manager.registry.adventure(row['id'])
    assert pending['archived'] and pending['state'] == 'deleting'
    assert not path.exists()
    monkeypatch.setattr(deletion.shutil, 'rmtree', original)
    recover_deletions(manager)
    assert manager.registry.setting(PREFIX + row['id']) == {'complete': True}
    assert not (manager.root / '.deleted-adventures' / row['id']).exists()
    assert manager.registry.adventures() == []


def test_delete_refuses_symlink(client, tmp_path):
    _, manager = client
    row, path = adventure(manager)
    moved = tmp_path / 'outside'
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match='symbolic'):
        delete_adventure(manager, row['id'], row['name'])
    assert (moved / 'save.state').exists()
