from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import time

import pytest

from pokesim.app import cli


@pytest.mark.parametrize('arguments', [
    ['--data-dir', '/tmp/library', 'adventures', 'list'],
    ['adventures', '--data-dir', '/tmp/library', 'list'],
    ['adventures', 'list', '--data-dir', '/tmp/library'],
])
def test_directory_option_works_at_each_command_level(arguments):
    assert cli.parser().parse_args(arguments).data_dir == Path('/tmp/library')


def test_import_requires_explicit_stopped_confirmation():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(['import', '/tmp/legacy'])


def test_create_uses_installed_rom_and_starts_only_when_requested(monkeypatch):
    calls = []
    class Application:
        def __init__(self, root):
            self.root = root
        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {'id': 'a' * 32}
        def close(self):
            calls.append(('closed',))
    monkeypatch.setattr(cli, 'RunningApplication', Application)
    args = cli.parser().parse_args(['adventures', 'create', '--name', 'Another Red', '--rom-id', 'known', '--start'])
    assert cli.run(args)['id'] == 'a' * 32
    assert calls[0][1] == '/api/v1/adventures'
    assert calls[0][2]['json']['rom_id'] == 'known'
    assert len(calls[0][2]['json']['request_id']) == 32
    assert calls[1][1] == '/api/v1/adventures/' + 'a' * 32 + '/start'
    assert calls[2] == ('closed',)


def test_missing_application_identity_gives_actionable_error(tmp_path):
    with pytest.raises(ValueError, match='Start the PokeSim application'):
        cli.RunningApplication(tmp_path)


@pytest.mark.parametrize('auth', ['none', 'accounts'])
def test_commands_reach_a_server_whose_public_address_is_elsewhere(tmp_path, auth):
    """In a container PUBLIC_URL names the published port or a proxy, so a command run there, through
    `docker compose exec` for one, connects to the port the server itself listens on."""
    root = tmp_path / 'library'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('POKESIM_', 'AUTH', 'OIDC_')) and key not in {'HOST', 'PORT', 'PUBLIC_URL'}}
    env.update(PUBLIC_URL='https://pokesim.example', AUTH=auth)
    command = [sys.executable, '-m', 'pokesim', 'serve', '--data-dir', str(root), '--host', '127.0.0.1', '--port', '0']
    with (tmp_path / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 60
        while not (root / 'cli.token').exists():
            assert server.poll() is None, (tmp_path / 'server.log').read_text(encoding='utf-8')
            assert time.monotonic() < deadline, 'the server did not start'
            time.sleep(0.1)
        identity = json.loads((root / 'manager.json').read_text(encoding='utf-8'))
        assert identity['url'] == 'https://pokesim.example'
        assert identity['local_url'].startswith('http://127.0.0.1:')
        app = cli.RunningApplication(root)
        try:
            assert app.request('GET', '/api/v1/adventures')['adventures'] == []
            # A change gets past the CSRF check, so the refusal is about the missing adventure.
            with pytest.raises(ValueError, match='not found'):
                app.request('POST', f'/api/v1/adventures/{"a" * 32}/stop', json={})
        finally:
            app.close()
    finally:
        server.terminate()
        server.wait(timeout=30)


def test_restore_uses_requested_empty_destination(monkeypatch, tmp_path):
    from pokesim.app import backup
    captured = []
    monkeypatch.setattr(backup, 'restore_backup', lambda archive, destination: captured.append((archive, destination)) or destination)
    args = cli.parser().parse_args(['restore', '/tmp/export.zip', '--data-dir', str(tmp_path / 'new')])
    assert cli.run(args) == {'restored_to': str(tmp_path / 'new')}
    assert captured == [(Path('/tmp/export.zip'), tmp_path / 'new')]


def test_import_pair_requires_both_peers_and_stopped_confirmation():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(['import-pair', '--red', '/old/red', '--blue', '/old/blue'])


def test_import_pair_forwards_exact_sources_and_coordinator(monkeypatch, tmp_path):
    from pokesim.app import manager, legacy_import
    captured = []
    class Destination:
        def __init__(self, root):
            assert root == tmp_path
        def close(self):
            captured.append('closed')
    monkeypatch.setattr(manager, 'Manager', Destination)
    monkeypatch.setattr(legacy_import, 'import_pair', lambda app, **kwargs: captured.append(kwargs) or [{'id': 'paired'}])
    args = cli.parser().parse_args(['import-pair', '--red', '/old/red', '--blue', '/old/blue',
        '--red-rom', '/roms/red.gb', '--blue-rom', '/roms/blue.gb', '--coordinator-root', '/old/trader',
        '--stopped', '--data-dir', str(tmp_path)])
    assert cli.run(args) == {'adventures': [{'id': 'paired'}]}
    assert captured[0]['sources'] == {'red': Path('/old/red'), 'blue': Path('/old/blue')}
    assert captured[0]['roms'] == {'red': Path('/roms/red.gb'), 'blue': Path('/roms/blue.gb')}
    assert captured[0]['coordinator_root'] == Path('/old/trader')
    assert captured[0]['stopped'] is True
    assert captured[1] == 'closed'
