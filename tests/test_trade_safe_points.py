"""Peers reach safe checkpoints independently within one bounded retry window."""
import io
import json
from urllib.error import HTTPError

import pytest

from pokesim.trade import service
from test_trade_fairness import scheduler


def conflict(message='Waiting for an unpaused overworld safe point', code=409):
    return HTTPError('http://peer/api/trade', code, 'Conflict', {},
                     io.BytesIO(json.dumps({'detail': message}).encode()))


def test_staggered_safe_points_can_prepare_without_overlapping(scheduler, monkeypatch):
    root, state, board, calls, attempts = scheduler
    state['game']['in_battle'] = 1
    clock = [0.0]
    held = set()
    seen = []
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(service.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    def control(c, name, action, transaction):
        seen.append((name, action, transaction))
        if action == 'prepare':
            ready = (name == 'red' and clock[0] < 0.5) or (name == 'blue' and clock[0] >= 0.5)
            if not ready:
                assert name not in held
                raise conflict()
            held.add(name)
            return {'phase': 'prepared'}
        assert action == 'abort'
        held.discard(name)
    monkeypatch.setattr(service.Coordinator, 'control', control)
    service.Coordinator(root).cycle()
    assert attempts == ['league_reward']
    assert not held
    assert len({row[2] for row in seen}) == 1
    assert len([row for row in seen if row[:2] == ('red', 'prepare')]) == 1


def test_retry_deadline_aborts_both_peers_and_clears_transaction(scheduler, monkeypatch):
    root, state, board, calls, attempts = scheduler
    clock = [0.0]
    seen = []
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(service.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    def control(c, name, action, transaction):
        seen.append((name, action))
        if action == 'prepare' and name == 'blue':
            raise conflict()
        return {'phase': 'prepared'}
    monkeypatch.setattr(service.Coordinator, 'control', control)
    with pytest.raises(TimeoutError, match='safe point'):
        service.Coordinator(root).cycle()
    assert clock[0] == 15
    assert ('red', 'abort') in seen and ('blue', 'abort') in seen
    assert attempts == [] and not (root / 'active.json').exists()


@pytest.mark.parametrize('code,message', [(403,'Not authorized'), (409,'Another exchange holds this game')])
def test_non_transient_rejection_is_not_retried(scheduler, monkeypatch, code, message):
    root, state, board, calls, attempts = scheduler
    seen = []
    def control(c, name, action, transaction):
        seen.append((name, action))
        if action == 'prepare':
            raise conflict(message, code)
    monkeypatch.setattr(service.Coordinator, 'control', control)
    with pytest.raises(HTTPError):
        service.Coordinator(root).cycle()
    assert seen == [('red','prepare'), ('red','abort')]
    assert not (root / 'active.json').exists()


def test_second_peer_does_not_receive_a_fresh_retry_window(scheduler, monkeypatch):
    root, state, board, calls, attempts = scheduler
    clock = [0.0]
    seen = []
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(service.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def control(c, name, action, transaction):
        seen.append((name, action, clock[0]))
        if action == 'prepare':
            if name == 'red' and clock[0] >= 10:
                return {'phase': 'prepared'}
            raise conflict()
    monkeypatch.setattr(service.Coordinator, 'control', control)
    with pytest.raises(TimeoutError):
        service.Coordinator(root).cycle()
    assert clock[0] == 15
    assert next(t for name, action, t in seen if name == 'blue') == 10
    assert seen[-2:] == [('red', 'abort', 15), ('blue', 'abort', 15)]
    assert not (root / 'active.json').exists()


@pytest.mark.parametrize('body', [b'not JSON', b'[]', b'{"detail":"Trade command is still pending, retry the same transaction"}'])
def test_unrecognized_conflict_is_not_retried(scheduler, monkeypatch, body):
    root, state, board, calls, attempts = scheduler
    seen = []
    def control(c, name, action, transaction):
        seen.append((name, action))
        if action == 'prepare':
            raise HTTPError('http://peer/api/trade', 409, 'Conflict', {}, io.BytesIO(body))
    monkeypatch.setattr(service.Coordinator, 'control', control)
    with pytest.raises(HTTPError):
        service.Coordinator(root).cycle()
    assert seen == [('red', 'prepare'), ('red', 'abort')]
    assert not (root / 'active.json').exists()
