import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from tools.check_registry_image import check, check_index


IMAGE = 'ghcr.io/afk-sapien/pokesim:0.2.0rc99'


def test_anonymous_pull_uses_empty_credentials_and_matches_tested_image(monkeypatch, tmp_path):
    credentials = tmp_path / 'credentials'
    credentials.mkdir()
    (credentials / 'config.json').write_text('{"auths":{"ghcr.io":{"auth":"private"}}}')
    monkeypatch.setenv('DOCKER_CONFIG', str(credentials))
    inspect = Mock(side_effect=['sha256:tested\n', 'sha256:tested\n'])
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
    assert inspect.call_count == 2
    assert configs and not configs[0].exists()


@pytest.mark.parametrize('error', [
    subprocess.CalledProcessError(1, ['docker', 'pull']),
    subprocess.TimeoutExpired(['docker', 'pull'], 300),
])
def test_inaccessible_registry_blocks_release_with_recovery_instructions(monkeypatch, error):
    monkeypatch.setattr(subprocess, 'check_output', Mock(return_value='sha256:tested'))
    monkeypatch.setattr(subprocess, 'run', Mock(side_effect=error))
    with pytest.raises(RuntimeError, match='visibility to Public'):
        check(IMAGE)


def test_platform_pull_matches_the_tested_architecture_image(monkeypatch):
    inspect = Mock(side_effect=['sha256:arm\n', 'sha256:arm\n'])
    monkeypatch.setattr(subprocess, 'check_output', inspect)
    pulls = []
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: pulls.append(command[3:]))
    check(IMAGE, tested=IMAGE + '-linux-arm64', platform='linux/arm64')
    assert inspect.call_args_list[0].args[0][-1] == IMAGE + '-linux-arm64'
    assert inspect.call_args_list[1].args[0][-1] == IMAGE
    assert pulls == [['pull', '--platform', 'linux/arm64', IMAGE]]


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


def test_changed_remote_image_blocks_release(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', Mock(side_effect=['sha256:tested', 'sha256:other']))
    monkeypatch.setattr(subprocess, 'run', Mock())
    with pytest.raises(ValueError, match='differs from the tested local image'):
        check(IMAGE)
