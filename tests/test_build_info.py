import json
from pathlib import Path
import subprocess
import tomllib

import pytest

from pokesim import __version__
from pokesim.build_info import source_info


def test_source_version_matches_package_metadata():
    root = Path(__file__).resolve().parents[1]
    assert tomllib.loads((root / 'pyproject.toml').read_text())['project']['version'] == __version__


def test_git_checkout_reports_revision_and_dirty_state(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(subprocess, 'check_output', lambda args, **kwargs:
                        'a' * 40 + '\n' if args[-1] == 'HEAD' else ' M example.py\n')
    assert source_info(tmp_path) == {'version': __version__, 'revision': 'a' * 40, 'dirty': True}


def test_installed_package_keeps_embedded_identity_without_git(tmp_path, monkeypatch):
    monkeypatch.delenv('POKESIM_REVISION', raising=False)
    package = tmp_path / 'pokesim'
    package.mkdir()
    expected = {'version': __version__, 'revision': 'b' * 40, 'dirty': False}
    (package / '_build.json').write_text(json.dumps(expected))
    assert source_info(tmp_path) == expected


def test_docker_can_supply_its_recorded_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('POKESIM_REVISION', 'c' * 40)
    assert source_info(tmp_path)['revision'] == 'c' * 40


def test_unknown_identity_is_explicit_and_mismatched_metadata_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv('POKESIM_REVISION', raising=False)
    assert source_info(tmp_path)['revision'] is None
    (tmp_path / 'pokesim').mkdir()
    (tmp_path / 'pokesim' / '_build.json').write_text(json.dumps({'version': 'wrong'}))
    with pytest.raises(RuntimeError, match='identity'):
        source_info(tmp_path)
