import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from tools.check_registry_image import check, check_index, check_unchanged


IMAGE = 'ghcr.io/afk-sapien/pokesim:0.2.0rc99'
LABELS = {'org.opencontainers.image.revision': 'abc'}


def local(arch='amd64', layers=('sha256:a', 'sha256:b'), created='2026-10-31T02:27:12.063827416Z'):
    """`docker image inspect` output. The ID differs by image store, so the check must ignore it."""
    return json.dumps({'Id': 'sha256:store-specific', 'Os': 'linux', 'Architecture': arch, 'Created': created,
                       'RootFS': {'Layers': list(layers)}, 'Config': {'Labels': LABELS}}).encode()


def config(arch='amd64', layers=('sha256:a', 'sha256:b'), created='2026-10-31T02:27:12.063827416Z'):
    return {'os': 'linux', 'architecture': arch, 'created': created,
            'rootfs': {'type': 'layers', 'diff_ids': list(layers)}, 'config': {'Labels': LABELS}}


def docker(local_output, registry_output):
    """Answer `docker image inspect` and `docker buildx imagetools inspect` and record the calls."""
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ['docker', 'image', 'inspect']:
            return local_output
        if isinstance(registry_output, Exception):
            raise registry_output
        return json.dumps(registry_output).encode()
    return Mock(side_effect=run), calls


def test_anonymous_pull_uses_empty_credentials_and_matches_tested_image(monkeypatch, tmp_path):
    credentials = tmp_path / 'credentials'
    credentials.mkdir()
    (credentials / 'config.json').write_text('{"auths":{"ghcr.io":{"auth":"private"}}}')
    monkeypatch.setenv('DOCKER_CONFIG', str(credentials))
    inspect, calls = docker(local(), config())
    monkeypatch.setattr(subprocess, 'check_output', inspect)
    configs = []

    def pull(command, **kwargs):
        assert command[:2] == ['docker', '--config']
        assert command[3:] == ['pull', IMAGE]
        config = Path(command[2])
        assert config != credentials
        assert list(config.iterdir()) == []
        assert kwargs['check'] is True
        configs.append(config)

    monkeypatch.setattr(subprocess, 'run', pull)
    check(IMAGE)
    assert calls[1][0][:4] == ['docker', 'buildx', 'imagetools', 'inspect']
    assert calls[1][1]['env']['DOCKER_CONFIG'] == str(configs[0])
    assert configs and not configs[0].exists()


@pytest.mark.parametrize('error', [
    subprocess.CalledProcessError(1, ['docker', 'pull']),
    subprocess.TimeoutExpired(['docker', 'pull'], 300),
])
def test_inaccessible_registry_blocks_release_with_recovery_instructions(monkeypatch, error):
    monkeypatch.setattr(subprocess, 'check_output', docker(local(), config())[0])
    monkeypatch.setattr(subprocess, 'run', Mock(side_effect=error))
    with pytest.raises(RuntimeError, match='visibility to Public'):
        check(IMAGE)


def test_platform_pull_matches_the_tested_architecture_image(monkeypatch):
    inspect, calls = docker(local('arm64'), {'linux/amd64': config(), 'linux/arm64': config('arm64'),
                                             'unknown/unknown': None})
    monkeypatch.setattr(subprocess, 'check_output', inspect)
    pulls = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: pulls.append(command[3:]))
    check(IMAGE, tested=IMAGE + '-linux-arm64', platform='linux/arm64')
    assert calls[0][0][-1] == IMAGE + '-linux-arm64'
    assert calls[1][0][-1] == IMAGE
    assert pulls == [['pull', '--platform', 'linux/arm64', IMAGE]]


@pytest.mark.parametrize('served', [config(layers=('sha256:a', 'sha256:other')), config(created='2026-11-01T00:00:00Z'),
                                    {'linux/amd64': config('amd64', layers=('sha256:other',)),
                                     'linux/arm64': config('arm64')}])
def test_changed_remote_image_blocks_release(monkeypatch, served):
    monkeypatch.setattr(subprocess, 'check_output', docker(local(), served)[0])
    monkeypatch.setattr(subprocess, 'run', Mock())
    with pytest.raises(ValueError, match='differs from the tested local image'):
        check(IMAGE)


def test_registry_without_the_tested_platform_blocks_release(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', docker(local('arm64'), config())[0])
    monkeypatch.setattr(subprocess, 'run', Mock())
    with pytest.raises(ValueError, match='differs from the tested local image'):
        check(IMAGE, platform='linux/arm64')


def test_push_guard_passes_a_missing_tag_and_the_same_image(monkeypatch, capsys):
    missing = subprocess.CalledProcessError(1, ['docker'], stderr=f'ERROR: {IMAGE}: not found\n'.encode())
    monkeypatch.setattr(subprocess, 'check_output', docker(local(), missing)[0])
    check_unchanged(IMAGE)
    assert 'not in the registry yet' in capsys.readouterr().out
    monkeypatch.setattr(subprocess, 'check_output', docker(local('arm64'), {'linux/arm64': config('arm64')})[0])
    check_unchanged(IMAGE, platform='linux/arm64')
    assert 'already serves the tested image' in capsys.readouterr().out


def test_push_guard_refuses_to_replace_a_different_image(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', docker(local(), config(created='2026-11-01T00:00:00Z'))[0])
    with pytest.raises(ValueError, match='Publish a new version'):
        check_unchanged(IMAGE)


def test_push_guard_stops_when_the_registry_cannot_answer(monkeypatch):
    denied = subprocess.CalledProcessError(1, ['docker'], stderr=b'ERROR: unauthorized\n')
    monkeypatch.setattr(subprocess, 'check_output', docker(local(), denied)[0])
    with pytest.raises(LookupError, match='unauthorized'):
        check_unchanged(IMAGE)


def index(*platforms):
    return json.dumps({'manifests': [
        {'digest': 'sha256:' + str(number) * 64, 'platform': dict(zip(('os', 'architecture'), platform.split('/')))}
        for number, platform in enumerate(platforms)]}).encode()


def test_index_check_returns_the_anonymous_index_digest(monkeypatch, tmp_path):
    raw = index('linux/amd64', 'linux/arm64', 'unknown/unknown')
    calls = []

    def inspect(command, **kwargs):
        calls.append((command, kwargs['env']['DOCKER_CONFIG']))
        return raw

    monkeypatch.setenv('DOCKER_CONFIG', str(tmp_path))
    monkeypatch.setattr(subprocess, 'check_output', inspect)
    assert check_index(IMAGE, ['linux/arm64', 'linux/amd64']) == 'sha256:' + hashlib.sha256(raw).hexdigest()
    assert calls[0][0] == ['docker', 'buildx', 'imagetools', 'inspect', '--raw', IMAGE]
    assert calls[0][1] != str(tmp_path)


@pytest.mark.parametrize('raw', [index('linux/amd64'), index('linux/amd64', 'linux/arm64', 'linux/riscv64'),
                                 b'{"mediaType": "application/vnd.oci.image.manifest.v1+json"}'])
def test_index_without_exactly_the_release_platforms_blocks_release(monkeypatch, raw):
    monkeypatch.setattr(subprocess, 'check_output', Mock(return_value=raw))
    with pytest.raises(ValueError, match='serves'):
        check_index(IMAGE, ['linux/amd64', 'linux/arm64'])
