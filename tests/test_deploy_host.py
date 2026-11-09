"""tools/deploy_host.sh refuses a commit that would drop the deployed one or downgrade the live data."""
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'deploy_host.sh'
# The fake ssh and gh are shell scripts on PATH, which Windows does not run.
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='deploys from a POSIX shell')


def git(repo, *args, env=None):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit(repo, schema, message, date=None):
    """Commits on the current branch, at ``date`` (a git date) when given."""
    (repo / 'pokesim' / 'app').mkdir(parents=True, exist_ok=True)
    (repo / 'pyproject.toml').write_text('[project]\nversion = "0.7.0.dev0"\n')
    (repo / 'pokesim' / 'app' / 'registry.py').write_text(f'SCHEMA = {schema}\n')
    (repo / message).write_text(message)
    git(repo, 'add', '-A')
    env = {**os.environ, 'GIT_COMMITTER_DATE': date, 'GIT_AUTHOR_DATE': date} if date else None
    git(repo, '-c', 'user.name=test', '-c', 'user.email=test@example.com', 'commit', '-qm', message, env=env)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    """A base commit with a main commit and a feature commit on top of it, each its own branch."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'remote', 'add', 'origin', str(repo))
    shas = {'base': commit(repo, 1, 'base')}
    shas['main'] = commit(repo, 1, 'main')
    git(repo, 'checkout', '-q', '-b', 'feature', shas['base'])
    shas['feature'] = commit(repo, 2, 'feature')
    return repo, shas


def deploy(tmp_path, repo, revision, schema, *args):
    """Runs the script against a fake host that runs `revision` on data of `schema`, with no green gates."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / 'ssh').write_text(f'#!/bin/sh\ncat >/dev/null\nprintf "%s\\n%s\\n" {revision} {schema}\n')
    (bin_dir / 'gh').write_text('#!/bin/sh\necho missing\n')
    for tool in ('ssh', 'gh'):
        (bin_dir / tool).chmod(0o755)
    env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
           'DEPLOY_HOST': 'host', 'DEPLOY_DIR': '/srv/app'}
    return subprocess.run(['sh', str(SCRIPT), *args], cwd=repo, env=env, capture_output=True, text=True)


def test_a_main_commit_is_refused_while_the_host_runs_a_feature_commit(tmp_path, repo):
    repo, shas = repo
    git(repo, 'checkout', '-q', 'main')
    commit(repo, 2, 'schema')
    candidate = git(repo, 'rev-parse', 'HEAD')
    result = deploy(tmp_path, repo, shas['feature'], 2, candidate)
    assert result.returncode == 1
    assert f'does not contain the deployed commit {shas["feature"][:7]}' in result.stderr


def test_a_commit_on_top_of_the_deployed_one_passes_both_guards(tmp_path, repo):
    repo, shas = repo
    result = deploy(tmp_path, repo, shas['base'], 1, shas['feature'])
    assert result.returncode == 1
    assert "no green 'ci gate' check" in result.stderr


def test_rollback_to_skips_the_ancestry_guard(tmp_path, repo):
    repo, shas = repo
    result = deploy(tmp_path, repo, shas['main'], 1, '--rollback-to', shas['base'])
    assert "no green 'ci gate' check" in result.stderr


def test_an_older_schema_is_refused_even_as_a_rollback(tmp_path, repo):
    repo, shas = repo
    for args in ([shas['main']], ['--rollback-to', shas['main']]):
        result = deploy(tmp_path, repo, shas['feature'], 2, *args)
        assert result.returncode == 1
        assert "data schema 1, older than the live data's 2" in result.stderr


def soaked(tmp_path, repo, revision, sha, report, *args):
    """Runs the script with green gates and a docker that fails, so a commit past every check stops at the build."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / 'ssh').write_text(f'#!/bin/sh\ncat >/dev/null\nprintf "%s\\n%s\\n" {revision} 1\n')
    (bin_dir / 'gh').write_text('#!/bin/sh\necho success\n')
    (bin_dir / 'docker').write_text('#!/bin/sh\necho "docker reached" >&2\nexit 1\n')
    for tool in ('ssh', 'gh', 'docker'):
        (bin_dir / tool).chmod(0o755)
    reports = tmp_path / 'reports'
    reports.mkdir(exist_ok=True)
    if report is not None:
        import json
        (reports / f'{sha}.json').write_text(json.dumps(report))
    env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}', 'DEPLOY_HOST': 'host',
           'DEPLOY_DIR': '/srv/app', 'LIVE_SOAK_REPORTS': str(reports), 'MIN_FREE_GB': '0'}
    return subprocess.run(['sh', str(SCRIPT), *args, sha], cwd=repo, env=env, capture_output=True, text=True)


def test_a_commit_without_a_passing_live_soak_is_refused(tmp_path, repo):
    repo, shas = repo
    sha = shas['main']
    for report in (None, {'commit': sha, 'passed': False, 'problems': ['Red: reloaded a.state 3 times']},
                   {'commit': shas['base'], 'passed': True}):
        result = soaked(tmp_path, repo, shas['base'], sha, report)
        assert result.returncode == 1
        assert f'{sha[:7]} has no passing live soak' in result.stderr
        assert 'docker reached' not in result.stderr
    # A rollback needs one too.
    result = soaked(tmp_path, repo, shas['main'], shas['base'], None, '--rollback-to')
    assert 'has no passing live soak' in result.stderr


def test_a_commit_with_a_passing_live_soak_goes_on_to_the_build(tmp_path, repo):
    repo, shas = repo
    result = soaked(tmp_path, repo, shas['base'], shas['main'], {'commit': shas['main'], 'passed': True})
    assert 'live soak' not in result.stderr
    assert 'docker reached' in result.stderr


def test_a_fresh_main_commit_is_listed_but_does_not_block(tmp_path, repo):
    repo, shas = repo
    result = deploy(tmp_path, repo, shas['base'], 1, shas['feature'])
    assert 'lacks 1 commits from main' in result.stderr
    assert f'{shas["main"][:7]} main' in result.stderr
    assert "no green 'ci gate' check" in result.stderr


def test_a_main_commit_over_a_day_old_blocks_unless_behind_main(tmp_path, repo):
    repo, shas = repo
    git(repo, 'checkout', '-q', 'main')
    stale = commit(repo, 1, 'stale', date=f'{int(time.time()) - 2 * 86400} +0000')
    git(repo, 'checkout', '-q', 'feature')
    result = deploy(tmp_path, repo, shas['base'], 1, shas['feature'])
    assert result.returncode == 1
    assert f'{stale[:7]} stale' in result.stderr
    assert 'over a day old' in result.stderr
    result = deploy(tmp_path, repo, shas['base'], 1, '--behind-main', shas['feature'])
    assert 'over a day old' not in result.stderr
    assert "no green 'ci gate' check" in result.stderr


def test_an_unknown_deployed_commit_is_refused(tmp_path, repo):
    repo, shas = repo
    result = deploy(tmp_path, repo, 'f' * 40, 1, shas['main'])
    assert result.returncode == 1
    assert 'which this clone does not have' in result.stderr
