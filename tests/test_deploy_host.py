"""tools/deploy_host.sh refuses a commit that would drop the deployed one or downgrade the live data."""
import hashlib
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


def passing_trial(sha, **fields):
    return {'commit': sha, 'passed': True, 'finished': time.time(), 'image_id': 'sha256:built',
            'compose_sha256': 'c' * 64, **fields}


def soaked(tmp_path, repo, revision, sha, report, *args, trial=None):
    """Runs the script with green gates and a docker that knows one image and fails anything else, so a commit
    past every check stops at the image check or the build."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / 'ssh').write_text(f'#!/bin/sh\ncat >/dev/null\nprintf "%s\\n%s\\n" {revision} 1\n')
    (bin_dir / 'gh').write_text('#!/bin/sh\necho success\n')
    (bin_dir / 'docker').write_text('#!/bin/sh\nif [ "$1 $2" = "image inspect" ]; then echo sha256:built; exit 0; fi\n'
                                    'echo "docker reached" >&2\nexit 1\n')
    for tool in ('ssh', 'gh', 'docker'):
        (bin_dir / tool).chmod(0o755)
    reports = tmp_path / 'reports'
    import json
    for kind, body in (('smoke', report), ('image-trial', trial)):
        (reports / kind).mkdir(parents=True, exist_ok=True)
        (reports / kind / f'{sha}.json').unlink(missing_ok=True)
        if body is not None:
            (reports / kind / f'{sha}.json').write_text(json.dumps(body))
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


def test_a_commit_without_a_passing_image_trial_is_refused(tmp_path, repo):
    repo, shas = repo
    sha = shas['main']
    for trial in (None, passing_trial(sha, passed=False), passing_trial(sha, finished=time.time() - 2 * 86400),
                  passing_trial(sha, image_id='sha256:rebuilt')):
        result = soaked(tmp_path, repo, shas['base'], sha, {'commit': sha, 'passed': True}, trial=trial)
        assert result.returncode == 1
        assert 'live soak' not in result.stderr
        assert f'{sha[:7]} has no passing image trial' in result.stderr
        assert 'docker reached' not in result.stderr


def test_a_commit_with_a_passing_image_trial_goes_on_to_the_image_check(tmp_path, repo):
    repo, shas = repo
    sha = shas['main']
    result = soaked(tmp_path, repo, shas['base'], sha, {'commit': sha, 'passed': True}, trial=passing_trial(sha))
    assert 'live soak' not in result.stderr
    assert 'image trial' not in result.stderr
    assert 'docker reached' in result.stderr


def test_a_rollback_builds_its_image_without_an_image_trial(tmp_path, repo):
    repo, shas = repo
    sha = shas['base']
    result = soaked(tmp_path, repo, shas['main'], sha, {'commit': sha, 'passed': True}, '--rollback-to')
    assert 'image trial' not in result.stderr
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


def fake_host(tmp_path, shas, running=None):
    """Writes a host folder here and the fakes that a deploy of the main commit past every gate runs with,
    and returns the deploy's environment and the folder. The fake ssh answers the checks' read with the
    base commit on schema 1 and runs the host step in this shell. The fake docker logs each call, gives
    ``running``, by default the base commit, as the revision of the image the host runs, runs the alpine
    tar here, waits in compose stop until the file HOLD names exists, lists one stale pokesim image, and
    fails what the environment names: FAIL_BACKUP for the archive, FAIL_UP for every start, FAIL_HEALTH
    for the new image's start, FAIL_SMOKE for the smoke check and FAIL_RMI for removing an image. The new
    image moves app/app.sqlite to schema 2, which the old one refuses to start on, and leaves a rollback
    journal, as a stop in the middle of a write does."""
    import json
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / 'calls'
    (bin_dir / 'ssh').write_text(
        '#!/bin/sh\necho "ssh $*" >> "$CALLS"\nwhile [ "$1" = -o ]; do shift 2; done\nshift\n'
        f'case $# in\n  1) cat >/dev/null ;;\n  4) cat >/dev/null; printf "%s\\n%s\\n" {shas["base"]} 1 ;;\n'
        '  *) exec "$@" ;;\nesac\n')
    (bin_dir / 'gh').write_text('#!/bin/sh\necho success\n')
    (bin_dir / 'docker').write_text(
        '#!/bin/sh\necho "docker $*" >> "$CALLS"\n'
        'case "$1 $2" in\n'
        '  "image inspect") if echo "$*" | grep -q revision; then echo "$RUNNING"; else echo sha256:built; fi\n'
        '    exit 0 ;;\n'
        '  "compose stop") [ -z "${HOLD:-}" ] || while [ ! -e "$HOLD" ]; do sleep 0.1; done; exit 0 ;;\n'
        '  "images --format") echo pokesim:0.6.0-local-abcdef0; exit 0 ;;\n'
        '  "rmi "*) [ -z "${FAIL_RMI:-}" ]; exit ;;\n'
        '  "compose up") [ -z "${FAIL_UP:-}" ] || exit 1\n'
        '    if grep -qx POKESIM_IMAGE=pokesim:old .env; then [ "$(cat app/app.sqlite)" = 1 ]; exit; fi\n'
        '    echo 2 > app/app.sqlite; echo 2 > app/app.sqlite-journal; [ -z "${FAIL_HEALTH:-}" ]; exit ;;\nesac\n'
        '[ "$1" = exec ] && [ -n "${FAIL_SMOKE:-}" ] && exit 1\n'
        'if [ "$1" = run ] && echo " $* " | grep -q " alpine "; then\n'
        '  [ -z "${FAIL_BACKUP:-}" ] || exit 1\n  while [ "$1" != alpine ]; do shift; done\n'
        '  shift; exec "$@"\nfi\nexit 0\n')
    for tool in ('ssh', 'gh', 'docker'):
        (bin_dir / tool).chmod(0o755)
    host = tmp_path / 'host'
    (host / 'backups').mkdir(parents=True)
    (host / 'app').mkdir()
    (host / 'app' / 'app.sqlite').write_text('1\n')
    (host / 'compose.yaml').write_text('services: {}\n')
    (host / '.env').write_text('POKESIM_IMAGE=pokesim:old\n')
    sha = shas['main']
    reports = tmp_path / 'reports'
    trial = passing_trial(sha, compose_sha256=hashlib.sha256(b'services: {}\n').hexdigest())
    for kind, body in (('smoke', {'commit': sha, 'passed': True}), ('image-trial', trial)):
        (reports / kind).mkdir(parents=True)
        (reports / kind / f'{sha}.json').write_text(json.dumps(body))
    env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}', 'DEPLOY_HOST': 'host',
           'DEPLOY_DIR': str(host), 'LIVE_SOAK_REPORTS': str(reports), 'MIN_FREE_GB': '0', 'CALLS': str(calls),
           'RUNNING': running or shas['base']}
    return env, host


def deploy_to_host(tmp_path, repo, shas, running=None, **faults):
    """Deploys the main commit to a fake host, failing what ``faults`` names, see fake_host."""
    env, host = fake_host(tmp_path, shas, running)
    env.update({name: '1' for name, on in faults.items() if on})
    result = subprocess.run(['sh', str(SCRIPT), shas['main']], cwd=repo, env=env, capture_output=True, text=True)
    return result, host, (tmp_path / 'calls').read_text().splitlines()


def test_a_clean_deploy_switches_the_image_and_logs_it(tmp_path, repo):
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas)
    assert result.returncode == 0, result.stderr
    assert f'POKESIM_IMAGE=pokesim:0.7.0.dev0-local-{shas["main"][:7]}' in (host / '.env').read_text()
    assert 'deployed, backup backups/pre-local-' in (host / 'deploy.log').read_text()
    assert not (host / 'deploy.lock').exists()


@pytest.mark.parametrize('case', ['a backup with no json lists last', 'the last image cannot be removed'])
def test_a_good_deploy_exits_0_whatever_the_prune_finds(tmp_path, repo, case):
    repo, shas = repo
    env, host = fake_host(tmp_path, shas)
    if case == 'a backup with no json lists last':
        (host / 'backups' / 'pre-local-fffffff-20260901T000000Z.tar.gz').write_bytes(b'')
    else:
        env['FAIL_RMI'] = '1'
    result = subprocess.run(['sh', str(SCRIPT), shas['main']], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'deployed, backup backups/pre-local-' in (host / 'deploy.log').read_text()


def test_a_failed_backup_starts_the_old_image_again(tmp_path, repo):
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas, FAIL_BACKUP=True)
    assert result.returncode == 1
    stop = calls.index('docker compose stop -t 120')
    assert 'docker compose up -d --wait' in calls[stop:], 'the app was left stopped'
    assert (host / '.env').read_text() == 'POKESIM_IMAGE=pokesim:old\n'
    assert 'was not written, pokesim:old runs again' in (host / 'deploy.log').read_text()


def test_a_failed_restart_says_the_app_is_down(tmp_path, repo):
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas, FAIL_UP=True)
    assert result.returncode == 1
    log = (host / 'deploy.log').read_text()
    assert 'pokesim:old did not come back up, the app is down' in log
    assert 'runs again' not in log and 'rolled back' not in log
    assert (host / '.env').read_text() == 'POKESIM_IMAGE=pokesim:old\n'


@pytest.mark.parametrize('fault', ['FAIL_HEALTH', 'FAIL_SMOKE'])
def test_a_failure_after_the_new_image_started_brings_back_data_the_old_image_opens(tmp_path, repo, fault):
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas, **{fault: True})
    assert result.returncode == 1
    assert 'pokesim:old runs again' in (host / 'deploy.log').read_text()
    assert (host / 'app' / 'app.sqlite').read_text() == '1\n'
    # SQLite would play the new image's journal back into the old database.
    assert not (host / 'app' / 'app.sqlite-journal').exists()
    assert (host / '.env').read_text() == 'POKESIM_IMAGE=pokesim:old\n'


def test_a_second_deploy_is_refused_while_the_first_runs_however_long_it_takes(tmp_path, repo):
    repo, shas = repo
    env, host = fake_host(tmp_path, shas)
    calls, release = tmp_path / 'calls', tmp_path / 'release'
    command = ['sh', str(SCRIPT), shas['main']]
    first = subprocess.Popen(command, cwd=repo, env={**env, 'HOLD': str(release)}, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 60
        while not calls.exists() or 'docker compose stop -t 120' not in calls.read_text():
            assert first.poll() is None and time.monotonic() < deadline, 'the first deploy never stopped the app'
            time.sleep(0.05)
        # The first deploy has held the host for 20 minutes by now.
        then = time.time() - 20 * 60
        os.utime(host / 'deploy.lock', (then, then))
        second = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    finally:
        release.touch()
        out, err = first.communicate(timeout=60)
    assert second.returncode == 1, second.stdout
    assert 'another deploy is running' in second.stderr
    assert first.returncode == 0, err
    assert calls.read_text().count('docker compose stop') == 1


def test_a_deploy_is_refused_when_the_host_changed_after_its_checks(tmp_path, repo):
    """The checks read the base commit, then another deploy shipped the feature commit first."""
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas, running=shas['feature'])
    assert result.returncode == 1
    assert f'refused: the host runs {shas["feature"]} now, not the {shas["base"]}' in (host / 'deploy.log').read_text()
    assert 'docker compose stop -t 120' not in calls
    assert (host / '.env').read_text() == 'POKESIM_IMAGE=pokesim:old\n'


def test_every_ssh_call_fails_rather_than_asks_for_a_password(tmp_path, repo):
    repo, shas = repo
    result, host, calls = deploy_to_host(tmp_path, repo, shas)
    ssh = [call for call in calls if call.startswith('ssh ')]
    assert len(ssh) == 3
    assert all(call.startswith('ssh -o BatchMode=yes ') for call in ssh), ssh
