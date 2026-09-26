"""Check bootstrap failures without downloading or changing the user's tools."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest

from tools.check_quickstart import compose_command, compose_environment

ROOT = Path(__file__).resolve().parents[1]


def test_installers_select_the_current_release():
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    assert f'    version={version}\n' in (ROOT / 'install.sh').read_text()
    assert f"$version = '{version}'\n" in (ROOT / 'install.ps1').read_text()


@pytest.fixture
def shell_environment(tmp_path):
    if os.name == 'nt':
        pytest.skip('POSIX bootstrap tests run on Linux and macOS')
    commands = tmp_path / 'commands'
    commands.mkdir()
    home = tmp_path / 'user with spaces'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'PATH': str(commands), 'CALLS': str(tmp_path / 'calls')}
    for name in ('sh', 'mktemp', 'rm', 'cp', 'mkdir', 'chmod'):
        (commands / name).symlink_to(shutil.which(name))

    def script(name, body):
        path = commands / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    script('uname', 'echo Linux')
    script('id', 'echo 1000')
    return env, script


def run_installer(env):
    return subprocess.run(['sh', str(ROOT / 'install.sh')], env=env, text=True, capture_output=True)


def test_failed_bootstrap_download_does_not_execute_partial_script(shell_environment):
    env, script = shell_environment
    script('curl', 'exit 22')
    result = run_installer(env)
    assert result.returncode != 0
    assert not (Path(env['HOME']) / '.local/bin/uv').exists()
    assert 'PokeSim is installed' not in result.stdout


def test_reuse_uv_and_fail_without_reporting_success(shell_environment):
    env, script = shell_environment
    script('uv', 'exit 7')
    result = run_installer(env)
    assert result.returncode == 7
    assert 'Installing uv for' not in result.stdout
    assert 'PokeSim is installed' not in result.stdout


def test_bootstrap_without_uv_and_launch_from_path_with_spaces(shell_environment, tmp_path):
    env, script = shell_environment
    fake_bin = tmp_path / 'tool commands'
    fake_bin.mkdir()
    launcher = fake_bin / 'pokesim-desktop'
    launcher.write_text('#!/bin/sh\n[ "$1" = --help ]\n')
    launcher.chmod(0o755)
    fake_uv = tmp_path / 'fake-uv'
    fake_uv.write_text('''#!/bin/sh
if [ "$1 $2" = "tool dir" ]
then
    printf '%s\\n' "$FAKE_BIN"
else
    printf '%s\\n' "$@" > "$CALLS"
fi
''')
    fake_uv.chmod(0o755)
    bootstrap = tmp_path / 'bootstrap'
    bootstrap.write_text('''#!/bin/sh
set -eu
[ "$UV_NO_MODIFY_PATH" = 1 ]
mkdir -p "$UV_INSTALL_DIR"
cp "$FAKE_UV" "$UV_INSTALL_DIR/uv"
chmod +x "$UV_INSTALL_DIR/uv"
''')
    script('curl', '''for argument in "$@"
do
    destination=$argument
done
cp "$BOOTSTRAP" "$destination"
''')
    env.update(FAKE_UV=str(fake_uv), FAKE_BIN=str(fake_bin), BOOTSTRAP=str(bootstrap))
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    assert 'Installing uv for your user account' in result.stdout
    assert f'"{launcher}"' in result.stdout
    arguments = Path(env['CALLS']).read_text().splitlines()
    assert arguments[:6] == ['tool', 'install', '--python', '3.12', '--managed-python', '--upgrade']
    assert arguments[-1].startswith('https://github.com/afk-sapien/PokeSim/releases/download/')
    # Retry finds the user-local uv even though its directory is absent from PATH.
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    assert 'Installing uv for your user account' not in result.stdout


def test_root_install_explains_normal_user_requirement(shell_environment):
    env, script = shell_environment
    script('id', 'echo 0')
    result = run_installer(env)
    assert result.returncode != 0
    assert 'without sudo' in result.stderr


def test_unsupported_platform_explains_windows_installer(shell_environment):
    env, script = shell_environment
    script('uname', 'echo MINGW64_NT')
    result = run_installer(env)
    assert result.returncode != 0
    assert 'install.ps1' in result.stderr


def test_quickstart_only_changes_storage_default():
    docker = shutil.which('docker')
    if docker is None:
        pytest.skip('Compose configuration check needs Docker CLI, without a daemon')
    if subprocess.run([docker, 'compose', 'version'], capture_output=True).returncode:
        pytest.skip('Compose v2 is not installed on this host')
    configs = []
    env = {key: value for key, value in os.environ.items()
           if key not in {'DATA_PATH', 'HTTP_PORT', 'PUBLIC_URL', 'POKESIM_IMAGE', 'BIND_ADDRESS'}}
    env['HTTP_PORT'] = '18931'
    for name in ('compose.yaml', 'compose.quickstart.yaml'):
        result = subprocess.run([docker, 'compose', '--env-file', os.devnull, '-f', str(ROOT / name),
                                 'config', '--format', 'json'], env=env, text=True, capture_output=True, check=True)
        service = json.loads(result.stdout)['services']['pokesim']
        mount = service.pop('volumes')[0]
        assert mount['target'] == '/data'
        assert mount['type'] == ('bind' if name == 'compose.yaml' else 'volume')
        assert service['environment']['PUBLIC_URL'] == 'http://localhost:18931'
        configs.append(service)
    assert configs[0] == configs[1]


def test_quickstart_test_ignores_inherited_compose_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv('COMPOSE_FILE', '/real/deployment/compose.yaml')
    monkeypatch.setenv('COMPOSE_ENV_FILES', '/real/deployment/.env')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'real-deployment')
    monkeypatch.setenv('COMPOSE_PROFILES', 'production')
    monkeypatch.setenv('DATA_PATH', '/real/data')
    env = compose_environment('pokesim:test', 18932)
    assert not any(key.startswith('COMPOSE_') for key in env)
    assert 'DATA_PATH' not in env
    command = compose_command(tmp_path, 'disposable-test')
    assert command[command.index('-f') + 1] == str(tmp_path / 'compose.yaml')
    assert command[command.index('--env-file') + 1] == str(tmp_path / '.env')
    assert command[command.index('--project-name') + 1] == 'disposable-test'


@pytest.mark.parametrize('data_path,kind', [('pokesim-data', 'volume'), ('./my-library', 'bind')])
def test_proxy_preserves_quickstart_storage(tmp_path, data_path, kind):
    docker = shutil.which('docker')
    if docker is None or subprocess.run([docker, 'compose', 'version'], capture_output=True).returncode:
        pytest.skip('Compose configuration check needs the Compose v2 CLI')
    for source, destination in [('compose.quickstart.yaml', 'compose.yaml'), ('compose.proxy.yaml', 'compose.proxy.yaml')]:
        shutil.copyfile(ROOT / source, tmp_path / destination)
    (tmp_path / '.env').write_text('')
    env = compose_environment('pokesim:test', 18933)
    env.update(DATA_PATH=data_path, AUTH_USER='test', AUTH_HASH='unused-config-check', PUBLIC_URL='https://localhost:9443')
    configs = []
    for name in ('compose.yaml', 'compose.proxy.yaml'):
        result = subprocess.run([docker, 'compose', '-p', 'same-library', '--env-file', str(tmp_path / '.env'),
                                 '-f', str(tmp_path / name), 'config', '--format', 'json'],
                                env=env, text=True, capture_output=True, check=True)
        config = json.loads(result.stdout)
        mount = config['services']['pokesim']['volumes'][0]
        assert mount['type'] == kind
        if kind == 'volume':
            assert config['volumes'][mount['source']]['name'] == 'same-library_pokesim-data'
        configs.append(mount)
    assert configs[0] == configs[1]


def test_public_quickstart_uses_completed_release_assets():
    for name in ('README.md', 'docs/desktop.md', 'docs/self-hosting.md'):
        text = (ROOT / name).read_text()
        assert 'https://raw.githubusercontent.com/afk-sapien/PokeSim/main/' not in text
        assert 'https://github.com/afk-sapien/PokeSim/releases/latest/download/' in text
