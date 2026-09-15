"""Failure recovery must obey the durable pair decision without replaying a swap."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('trade_pair', Path(__file__).parents[1] / 'tools/trade_pair.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    module.write(tmp_path / 'policy.json', {'peers': {'red': {'container': 'red'}, 'blue': {'container': 'blue'}}})
    c = module.Coordinator(tmp_path)
    calls = []
    monkeypatch.setattr(module, 'run', lambda *args: calls.append(args))
    monkeypatch.setattr(module, 'request', lambda *args: {'health': {'ok': True}})
    monkeypatch.setattr(c, 'worker', lambda *args: calls.append(args))
    return c, calls


def test_interrupted_publication_removes_both_outputs_before_restarting(coordinator):
    c, calls = coordinator
    files = [c.root / 'red.state', c.root / 'blue.state']
    for path in files:
        path.write_bytes(b'partial publication')
    active = {'id': '123', 'phase': 'preparing', 'targets': [str(p) for p in files], 'stopped': ['red', 'blue']}
    module.write(c.active_path, active)
    c.cycle()
    assert all(not p.exists() for p in files)
    assert calls == [('docker', 'start', 'red'), ('docker', 'start', 'blue')]
    assert not c.active_path.exists()


def test_committed_recovery_restarts_both_and_does_not_publish_again(coordinator):
    c, calls = coordinator
    active = {'id': '124', 'ts': 10, 'phase': 'committed', 'stopped': ['red', 'blue']}
    module.write(c.root / 'transactions/124/result.json', {'moved': [], 'reason': 'Useful trade'})
    module.write(c.active_path, active)
    c.cycle()
    assert calls == [('journal', '124'), ('docker', 'start', 'red'), ('docker', 'start', 'blue')]
    module.write(c.active_path, active)
    c.cycle()
    status = json.loads((c.root / 'status.json').read_text())
    assert status['completed'] == 1 and len(status['history']) == 1


def test_journal_failure_keeps_recovery_pending_and_never_starts_one_side(coordinator, monkeypatch):
    c, calls = coordinator
    active = {'id': '125', 'phase': 'committed', 'stopped': ['red', 'blue']}
    module.write(c.active_path, active)
    def fail(*args):
        raise OSError('Disk unavailable')
    monkeypatch.setattr(c, 'worker', fail)
    with pytest.raises(OSError):
        c.cycle()
    assert c.active_path.exists() and calls == []


def test_battle_menu_and_unhealthy_states_are_not_safe():
    base = {'health': {'ok': True}, 'game': {'party': [{}]}}
    assert module.safe(base)
    for key in ['in_battle', 'textbox', 'start_menu']:
        assert not module.safe({**base, 'game': {**base['game'], key: True}})
    assert not module.safe({'game': base['game']})


def test_disabled_policy_still_recovers_an_interrupted_transaction(coordinator):
    c, calls = coordinator
    assert not c.config.get('enabled')
    module.write(c.active_path, {'id': '126', 'phase': 'preparing', 'stopped': ['red', 'blue']})
    c.cycle()
    assert len(calls) == 2
