"""tools/alert_watch.py hands each new main-page alert over once, and again after it clears."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))

import alert_watch  # noqa: E402


def run(monkeypatch, state, problems, command=()):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(problems)))
    return alert_watch.main(['alert_watch.py', str(state), *command])


def problem(key, kind='help_request', message='Wandering Training Camp asked for help.'):
    return {'key': key, 'kind': kind, 'adventure_id': 'a' * 32, 'message': message, 'since': 0}


def test_each_alert_is_handed_over_once_and_again_after_it_clears(tmp_path, monkeypatch, capsys):
    state = tmp_path / 'alerts.json'
    out = tmp_path / 'tasks.txt'
    command = [sys.executable, '-c', f'import sys; open({str(out)!r}, "a").write(sys.stdin.read() + "\\n")']
    assert run(monkeypatch, state, [problem('help:a')], command) == 0
    assert run(monkeypatch, state, [problem('help:a'), problem('trade:x', 'trade')], command) == 0
    assert run(monkeypatch, state, [], command) == 0
    assert run(monkeypatch, state, [problem('help:a')], command) == 0
    tasks = out.read_text().splitlines()
    assert len(tasks) == 3
    assert tasks[0].startswith('PokeSim alert, help_request (adventure aaaa')
    assert 'Wandering Training Camp asked for help.' in tasks[0]
    assert 'trade' in tasks[1]


def test_an_alert_the_command_could_not_hand_over_is_tried_again(tmp_path, monkeypatch):
    state = tmp_path / 'alerts.json'
    assert run(monkeypatch, state, [problem('help:a')], [sys.executable, '-c', 'raise SystemExit(1)']) == 1
    assert json.loads(state.read_text()) == []
    assert run(monkeypatch, state, [problem('help:a')], [sys.executable, '-c', '']) == 0
    assert json.loads(state.read_text()) == ['help:a']


def test_a_run_with_no_command_prints_alerts_but_marks_none_seen(tmp_path, monkeypatch, capsys):
    # The overnight watch runs without a command and shares the timer's state file.
    state = tmp_path / 'alerts.json'
    assert run(monkeypatch, state, [problem('help:a')]) == 0
    assert 'asked for help' in capsys.readouterr().out and not state.exists()
    out = tmp_path / 'tasks.txt'
    command = [sys.executable, '-c', f'import sys; open({str(out)!r}, "a").write(sys.stdin.read())']
    assert run(monkeypatch, state, [problem('help:a')], command) == 0
    assert 'asked for help' in out.read_text()


def test_alerts_handed_over_before_the_app_went_down_stay_seen(tmp_path, monkeypatch):
    state = tmp_path / 'alerts.json'
    out = tmp_path / 'tasks.txt'
    command = [sys.executable, '-c', f'import sys; open({str(out)!r}, "a").write(sys.stdin.read() + "\\n")']
    run(monkeypatch, state, [problem('help:a')], command)
    run(monkeypatch, state, [problem('app-down', 'app_down', 'The app is not running.')], command)
    run(monkeypatch, state, [problem('help:a')], command)
    assert [line.split(',')[1].split()[0] for line in out.read_text().splitlines()] == ['help_request', 'app_down']


@pytest.fixture
def host(tmp_path):
    """A fake ssh whose remote command prints what ANSWER says, or fails when ANSWER is empty."""
    ssh = tmp_path / 'bin' / 'ssh'
    ssh.parent.mkdir()
    ssh.write_text('#!/bin/sh\n[ -n "$ANSWER" ] || exit 255\nprintf "%s" "$ANSWER"\n')
    ssh.chmod(0o755)

    def check(answer):
        env = {**os.environ, 'PATH': f'{ssh.parent}{os.pathsep}{os.environ["PATH"]}', 'ANSWER': answer,
               'POKESIM_WATCH_HOST': 'apphost', 'POKESIM_WATCH_LOGS': str(tmp_path / 'logs')}
        env.pop('POKESIM_WATCH_ALERT_COMMAND', None)
        return subprocess.run(['bash', str(TOOLS / 'alert_watch.sh')], env=env, capture_output=True, text=True).stdout
    return check


@pytest.mark.skipif(sys.platform == 'win32', reason='the watch runs on a Linux host')
def test_a_down_or_unreachable_app_is_one_alert_and_a_deploy_is_quiet(host):
    assert 'a deploy is running' in host('DEPLOYING')
    assert 'app_down' in host('DOWN') and 'is not running' in host('DOWN')
    assert 'alerts file cannot be read' in host('UNREADABLE')
    assert 'cannot be reached' in host('')
    assert 'asked for help' in host(json.dumps([problem('help:a')]))
