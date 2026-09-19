"""Reward backlogs must leave turns for overdue useful exchanges."""
import io
import json
from urllib.error import URLError

import pytest

from pokesim.trade import service


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    service.write(tmp_path / 'policy.json', {'enabled': True, 'league_rewards': True,
        'interval_seconds': 900, 'board_url': 'http://board', 'peers': {'red': {}, 'blue': {}}})
    state = {'health': {'ok': True}, 'game': {'party': [{}], 'storage': {'box_counts': [0] * 12}},
             'league_rewards': {'pending': 4}}
    monkeypatch.setattr(service, 'request', lambda *args: state)
    monkeypatch.setattr(service.Coordinator, 'control', lambda *args: {'phase': 'prepared'})
    board = {'routine_proposals': [{'reason': 'Both peers register a new species'}]}
    calls = []
    def get_board(*args, **kwargs):
        calls.append('board')
        return io.BytesIO(json.dumps(board).encode())
    monkeypatch.setattr(service.urllib.request, 'urlopen', get_board)
    attempts = []
    def stage(c, action, transaction):
        assert action == 'stage'
        active = json.loads(c.active_path.read_text())
        attempts.append(active.get('kind', 'trade'))
        service.write(tmp_path / f'transactions/{transaction}/result.json', {'status': 'no_opportunity'})
    monkeypatch.setattr(service.Coordinator, 'worker', stage)
    return tmp_path, state, board, calls, attempts


def test_persistent_reward_backlog_alternates_with_overdue_trades(scheduler):
    root, state, board, calls, attempts = scheduler
    for _ in range(4):
        service.Coordinator(root).cycle()
    assert attempts == ['league_reward', 'trade', 'league_reward', 'trade']


def test_reward_delivery_continues_during_trade_cooldown(scheduler):
    root, state, board, calls, attempts = scheduler
    service.write(root / 'public/status.json', {'completed': 0, 'history': [],
        'last_trade': service.time.time(), 'last_operation': 'league_reward'})
    service.Coordinator(root).cycle()
    assert attempts == ['league_reward']
    assert calls == []


def test_no_opportunity_does_not_delay_rewards(scheduler):
    root, state, board, calls, attempts = scheduler
    board['routine_proposals'] = []
    for _ in range(3):
        service.Coordinator(root).cycle()
    assert attempts == ['league_reward'] * 3


def test_board_failure_does_not_block_pending_rewards(scheduler, monkeypatch):
    root, state, board, calls, attempts = scheduler
    service.write(root / 'public/status.json', {'completed': 0, 'history': [], 'last_operation': 'league_reward'})
    def offline(*args, **kwargs):
        raise URLError('Board unavailable')
    monkeypatch.setattr(service.urllib.request, 'urlopen', offline)
    service.Coordinator(root).cycle()
    assert attempts == ['league_reward']


@pytest.mark.parametrize('unavailable', ['paused', 'unhealthy', 'no_party'])
def test_unavailable_peer_is_never_held_to_force_fairness(scheduler, unavailable):
    root, state, board, calls, attempts = scheduler
    if unavailable == 'paused':
        state['paused'] = True
    elif unavailable == 'unhealthy':
        state['health']['ok'] = False
    else:
        state['game']['party'] = []
    service.Coordinator(root).cycle()
    assert attempts == []
    assert not (root / 'active.json').exists()
