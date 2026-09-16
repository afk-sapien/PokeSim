import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import Mock
import zipfile

from fastapi.testclient import TestClient
import pytest

from pokesim import desktop, desktop_setup, game_data, platform_io
from pokesim.checkpoints import CheckpointStore


@pytest.mark.parametrize('platform,expected', [
    ('win32', ('AppData', 'Local', 'PokeSim')),
    ('darwin', ('Library', 'Application Support', 'PokeSim')),
    ('linux', ('.local', 'share', 'pokesim')),
])
def test_user_paths_do_not_depend_on_current_directory(tmp_path, monkeypatch, platform, expected):
    monkeypatch.setattr(desktop_setup.sys, 'platform', platform)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    assert desktop_setup.user_directory() == tmp_path.joinpath(*expected)


def test_rom_install_is_local_verified_and_cannot_replace_an_adventure(tmp_path, monkeypatch):
    raw = b'private-test-cartridge'
    monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Test')
    with pytest.raises(ValueError, match='clean'):
        desktop_setup.install_rom(tmp_path, b'not-a-ROM', 'random')
    assert not list(tmp_path.iterdir())
    desktop_setup.install_rom(tmp_path, raw, 'bulbasaur')
    assert (tmp_path / 'rom.gb').read_bytes() == raw
    assert desktop_setup.read_settings(tmp_path) == {'starter': 'bulbasaur'}
    with pytest.raises(ValueError, match='already'):
        desktop_setup.install_rom(tmp_path, raw, 'squirtle')
    assert desktop_setup.read_settings(tmp_path)['starter'] == 'bulbasaur'


def test_bad_settings_are_preserved_and_reported(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('broken')
    with pytest.raises(ValueError, match='Restore'):
        desktop_setup.read_settings(tmp_path)
    assert path.read_text() == 'broken'


def test_archive_checksum_failure_does_not_publish_data(tmp_path):
    with pytest.raises(ValueError, match='verification'):
        desktop_setup.prepare_archive(b'corrupt', tmp_path)
    assert not list(tmp_path.iterdir())


def test_archive_cannot_escape_extraction_directory(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(f'pokered-{game_data.SOURCE_REVISION}/../../escape', 'bad')
    raw = buffer.getvalue()
    monkeypatch.setattr(desktop_setup, 'REFERENCE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='contents'):
        desktop_setup.prepare_archive(raw, tmp_path)
    assert not list(tmp_path.iterdir())


def test_prepared_adventures_start_without_network(tmp_path, monkeypatch):
    load = Mock(return_value={})
    download = Mock(side_effect=AssertionError('No network for prepared games'))
    monkeypatch.setattr(game_data, 'load', load)
    monkeypatch.setattr(desktop_setup, 'urlopen', download)
    desktop_setup.ensure_game_data(tmp_path, Mock(), threading.Event())
    assert load.call_count == len(game_data.FILES)
    download.assert_not_called()


def test_process_lock_excludes_other_launches_and_releases_on_close(tmp_path):
    path = tmp_path / 'desktop.lock'
    script = '''
import sys
from pokesim.platform_io import lock_file
with open(sys.argv[1], 'a+b') as stream:
    try:
        lock_file(stream)
    except BlockingIOError:
        sys.exit(7)
'''
    with path.open('a+b') as stream:
        platform_io.lock_file(stream)
        result = subprocess.run([sys.executable, '-c', script, str(path)], check=False)
        assert result.returncode == 7
    assert subprocess.run([sys.executable, '-c', script, str(path)], check=False).returncode == 0


def test_windows_atomic_write_flushes_file_without_opening_directory(tmp_path, monkeypatch):
    path = tmp_path / 'save'
    # Change only the directory-sync platform decision, leaving pathlib intact.
    windows = Mock()
    windows.name = 'nt'
    monkeypatch.setattr(platform_io, 'os', windows)
    CheckpointStore.atomic_write(path, b'complete')
    assert path.read_bytes() == b'complete'
    platform_io.os.open.assert_not_called()


@pytest.fixture
def launcher(tmp_path):
    adventure = desktop.Adventure(tmp_path, 'http://127.0.0.1:9876')
    adventure.start = Mock()
    shutdown = Mock()
    app = desktop.create_desktop_app(adventure, 'secret', shutdown)
    with TestClient(app, base_url=adventure.url) as client:
        yield client, adventure, shutdown


def test_first_run_and_browser_assets_work_without_game_data(launcher):
    client, adventure, _ = launcher
    assert client.get('/').url.path == '/desktop'
    page = client.get('/desktop')
    assert 'content="secret"' in page.text
    assert 'Your first partner' in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert client.get('/desktop/assets/desktop.js').status_code == 200
    assert client.get('/desktop/assets/desktop.css').status_code == 200
    assert client.get('/desktop/status').json()['state'] == 'setup'
    adventure.start.assert_not_called()


def test_other_websites_cannot_operate_the_launcher(launcher):
    client, _, shutdown = launcher
    assert client.get('/desktop', headers={'Host': 'attacker.example:9876'}).status_code == 403
    assert client.post('/desktop/quit').status_code == 403
    assert client.post('/desktop/quit', headers={
        'X-PokeSim-Token': 'secret', 'Origin': 'https://attacker.example'
    }).status_code == 403
    assert client.post('/api/control', headers={'Origin': 'https://attacker.example'}).status_code == 403
    shutdown.assert_not_called()


def test_upload_errors_are_actionable_and_start_only_after_valid_install(launcher, monkeypatch):
    client, adventure, _ = launcher
    headers = {'X-PokeSim-Token': 'secret'}
    assert client.post('/desktop/rom', headers=headers, content=b'bad').status_code == 400
    assert client.post('/desktop/rom', headers=headers, content=b'x' * (desktop.MAX_ROM + 1)).status_code == 413
    adventure.start.assert_not_called()
    raw = b'local-cartridge'
    monkeypatch.setitem(desktop_setup.ROM_NAMES, hashlib.sha1(raw).hexdigest(), 'Test')
    assert client.post('/desktop/rom?starter=charmander', headers=headers, content=raw).status_code == 200
    assert desktop_setup.read_settings(adventure.root)['starter'] == 'charmander'
    adventure.start.assert_called_once()


def test_shutdown_waits_for_save_before_exiting(launcher):
    client, adventure, shutdown = launcher
    done = threading.Event()
    adventure.stop = lambda: done.set()
    shutdown.side_effect = lambda: pytest.fail('Quit before saving') if not done.is_set() else None
    response = client.post('/desktop/quit', headers={'X-PokeSim-Token': 'secret'})
    assert response.status_code == 200
    assert done.is_set()
    shutdown.assert_called_once()


def test_slow_shutdown_keeps_process_running(launcher):
    client, adventure, shutdown = launcher
    original = adventure.stop
    adventure.stop = Mock(side_effect=RuntimeError('Still saving'))
    try:
        response = client.post('/desktop/quit', headers={'X-PokeSim-Token': 'secret'})
        assert response.status_code == 409
        shutdown.assert_not_called()
    finally:
        adventure.stop = original


def test_startup_failure_keeps_recovery_ui_available(tmp_path):
    adventure = desktop.Adventure(tmp_path, 'http://127.0.0.1:9876')
    (tmp_path / 'rom.gb').write_bytes(b'invalid')
    adventure.start()
    adventure.thread.join(5)
    assert adventure.status()['state'] == 'error'
    assert 'stored ROM' in adventure.status()['error']
    assert adventure.game is None


def test_existing_instance_must_prove_its_identity(tmp_path, monkeypatch):
    (tmp_path / 'instance.json').write_text(json.dumps({'port': 9876, 'token': 'ours'}))
    response = Mock()
    response.__enter__ = Mock(return_value=io.BytesIO(b'{"token":"someone-else"}'))
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(desktop, 'build_opener', lambda *args: Mock(open=Mock(return_value=response)))
    assert desktop.existing_url(tmp_path) is None
