"""tools/alert_watch.py hands each new main-page alert over once, and again after it clears."""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

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
    assert run(monkeypatch, state, [problem('help:a')]) == 0
    assert json.loads(state.read_text()) == ['help:a']
