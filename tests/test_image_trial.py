"""tools/image_trial.py judges a container trial of the deploy image and gates the deploy on its report."""
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace

import pytest

from pokesim.app.coordinator import SUMMARY
from tools import image_trial

LINE = '2026-11-11 10:05:00,000 {level} pokesim.app.{name}: {message}'


def trial_log(*extra, gen1=3, gen2=3, failed=0, summary=True):
    lines = [LINE.format(level='INFO', name='manager', message='Started 6 adventures')]
    if summary:
        lines.append(LINE.format(level='INFO', name='coordinator', message=SUMMARY % (5, 30, failed, gen1, gen2)))
    return '\n'.join([*lines, *extra]) + '\n'


def trial_probes(wanted=6, running=6, health=0, restarts=0):
    """A probe a minute for the whole trial. The boot's probes see nothing running yet."""
    return [{'seconds': seconds, 'restarts': restarts, 'wanted': wanted, 'health': 1 if booting else health,
             'running': 0 if booting else running}
            for seconds in range(60, image_trial.MIN_SECONDS + 1, 60)
            for booting in [seconds < image_trial.BOOT_SECONDS]]


def test_the_summary_pattern_reads_the_coordinators_line():
    totals = image_trial.summaries(SUMMARY % (5, 30, 1, 12, 9) + '\n' + SUMMARY % (5, 29, 0, 3, 4))
    assert totals == {'lines': 2, 'passes': 59, 'failed': 1, 'gen1': 15, 'gen2': 13}


def test_a_clean_trial_passes_even_while_the_boot_starts_nothing():
    problems, found = image_trial.judge(trial_probes(), trial_log(), 6, image_trial.MIN_SECONDS)
    assert problems == []
    assert found['trades']['passes'] == 30


@pytest.mark.parametrize(('probes', 'log', 'seconds', 'problem'), [
    (trial_probes(), trial_log(), image_trial.MIN_SECONDS - 60, 'ran 29 minutes, under 30'),
    (trial_probes(), trial_log(LINE.format(level='ERROR', name='loops', message='cable-coordinator failed')),
     image_trial.MIN_SECONDS, '1 error lines'),
    (trial_probes(), trial_log('Traceback (most recent call last):'), image_trial.MIN_SECONDS, '1 error lines'),
    (trial_probes(), trial_log(LINE.format(
        level='WARNING', name='supervisor', message='Adventure 1a2b restarts in 30 seconds because it exited, '
        'restart 1 in a row')), image_trial.MIN_SECONDS, '1 adventure restart or unhealthy lines'),
    (trial_probes(), trial_log(failed=1), image_trial.MIN_SECONDS, '1 trade scheduler passes failed'),
    (trial_probes(), trial_log(gen2=2), image_trial.MIN_SECONDS,
     '2 passes rated Gold, Silver or Crystal offers, under 3'),
    (trial_probes(), trial_log(summary=False), image_trial.MIN_SECONDS, 'no trade summary line'),
    (trial_probes(running=5), trial_log(), image_trial.MIN_SECONDS, '26 probes saw under 6 adventures running, lowest 5'),
    (trial_probes(health=1), trial_log(), image_trial.MIN_SECONDS, 'the health check failed at 26 probes'),
    (trial_probes(restarts=1), trial_log(), image_trial.MIN_SECONDS, 'the container restarted 1 times'),
    (trial_probes()[:3] + [{'seconds': 600, 'error': 'the container is gone'}], trial_log(), image_trial.MIN_SECONDS,
     '1 probes failed, first: the container is gone'),
])
def test_each_bar_fails_the_trial(probes, log, seconds, problem):
    problems, _ = image_trial.judge(probes, log, 6, seconds)
    assert problem in problems


def test_the_copy_takes_only_the_app_folder_and_compose_file_and_no_secret(tmp_path):
    database = tmp_path / 'app.sqlite'
    db = sqlite3.connect(database)
    db.execute('CREATE TABLE adventures (id TEXT, archived INTEGER, desired_state TEXT, state TEXT)')
    db.executemany('INSERT INTO adventures VALUES (?, ?, ?, ?)', [
        ('a', 0, 'running', 'stopped'), ('b', 0, 'running', 'stopped'), ('c', 0, 'stopped', 'stopped'),
        ('d', 1, 'running', 'stopped')])
    db.commit()
    db.close()
    backup = tmp_path / 'cold.tar.gz'
    files = {'./app/app.sqlite': database.read_bytes(), './app/manager.json': b'{"url": "https://app.example"}',
             './app/adventures/a/save.state': b'save', './compose.yaml': b'services: {}\n'}
    secrets = {f'./app/{name}': b'secret' for name in image_trial.SECRETS}
    outside = {'./.env': b'AUTH=accounts\n', './admin-initial-password.txt': b'secret',
               './app.failed-1/app.sqlite': b'old', './backups/pre.tar.gz': b'old'}
    with tarfile.open(backup, 'w:gz') as archive:
        for name, body in {**files, **secrets, **outside}.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    out = tmp_path / 'out'
    out.mkdir()
    done = subprocess.run([sys.executable, '-c', image_trial.EXTRACT, str(backup), str(out), *image_trial.SECRETS],
                          check=True, capture_output=True, text=True)
    assert json.loads(done.stdout) == {'url': 'https://app.example', 'wanted': 2}
    copied = sorted('./' + path.relative_to(out).as_posix() for path in out.rglob('*') if path.is_file())
    assert copied == sorted(files)


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv('LIVE_SOAK_REPORTS', str(tmp_path))
    monkeypatch.setattr(image_trial, 'image_id', lambda tag: 'sha256:built')
    (tmp_path / 'image-trial').mkdir()
    return tmp_path / 'image-trial'


SHA = 'a' * 40


def checked(reports, **fields):
    report = {'commit': SHA, 'passed': True, 'finished': time.time() - 3600, 'image_id': 'sha256:built',
              'compose_sha256': 'c' * 64, **fields}
    (reports / f'{SHA}.json').write_text(json.dumps(report))
    return image_trial.check(SimpleNamespace(sha=SHA, tag='pokesim:0.7.0-local-aaaaaaa'))


def test_a_fresh_passing_trial_of_the_same_image_lets_the_deploy_on(reports, capsys):
    assert checked(reports) == 0
    assert capsys.readouterr().out == 'c' * 64 + '\n'


@pytest.mark.parametrize(('fields', 'message'), [
    ({'passed': False, 'problems': ['1 error lines']}, 'did not pass (1 problems)'),
    ({'finished': time.time() - 2 * 86400}, 'over a day old'),
    ({'image_id': 'sha256:other'}, 'not the image the trial'),
    ({'commit': 'b' * 40}, 'no report for aaaaaaa'),
])
def test_a_failed_stale_or_other_trial_stops_the_deploy(reports, capsys, fields, message):
    assert checked(reports, **fields) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert message in captured.err
