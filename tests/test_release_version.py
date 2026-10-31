from pathlib import Path
import shutil

import pytest

from tools import release_version


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tree(tmp_path):
    for name in {name for name, _ in release_version.PINS}:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def test_every_pin_on_this_branch_names_the_package_version():
    assert release_version.version_problems(ROOT) == []


def test_a_lagging_quickstart_pin_is_reported(tree):
    path = tree / 'compose.quickstart.yaml'
    version = release_version.package_version(tree)
    path.write_text(path.read_text().replace(f'pokesim:{version}', 'pokesim:0.0.1'))
    assert release_version.version_problems(tree) == [f'compose.quickstart.yaml pins 0.0.1, not {version}']


def test_a_removed_pin_is_reported(tree):
    (tree / 'Dockerfile').write_text('FROM scratch\n')
    assert any(problem.startswith('Dockerfile has no version pin')
               for problem in release_version.version_problems(tree))


def test_bump_moves_every_pin_and_nothing_else(tree):
    old = release_version.package_version(tree)
    before = {name: (tree / name).read_text() for name, _ in release_version.PINS}
    release_version.bump(tree, '9.8.7')
    assert release_version.package_version(tree) == '9.8.7'
    assert release_version.version_problems(tree) == []
    for name, text in before.items():
        assert (tree / name).read_text() != text, name
    assert 'releases/download/v9.8.7/pokesim-9.8.7-py3' in (tree / 'README.md').read_text()
    assert 'pokesim:9.8.7}' in (tree / 'compose.quickstart.yaml').read_text()
    # Only the pinned lines change. The uv.lock dependencies and other packages keep their versions.
    lock_before = before['uv.lock'].splitlines()
    lock_after = (tree / 'uv.lock').read_text().splitlines()
    changed = [(a, b) for a, b in zip(lock_before, lock_after) if a != b]
    assert changed == [(f'version = "{old}"', 'version = "9.8.7"')]


def test_bump_refuses_a_bad_version_or_a_missing_pin(tree):
    with pytest.raises(ValueError, match='Invalid release version'):
        release_version.bump(tree, 'v1.0')
    (tree / 'install.sh').write_text('#!/bin/sh\n')
    pyproject = (tree / 'pyproject.toml').read_text()
    with pytest.raises(ValueError, match='install.sh has no version pin'):
        release_version.bump(tree, '9.8.7')
    assert (tree / 'pyproject.toml').read_text() == pyproject
