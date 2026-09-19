from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from tools.check_registry_image import check


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


def test_changed_remote_image_blocks_release(monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', Mock(side_effect=['sha256:tested', 'sha256:other']))
    monkeypatch.setattr(subprocess, 'run', Mock())
    with pytest.raises(ValueError, match='differs from the tested local image'):
        check(IMAGE)
