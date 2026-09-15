from copy import deepcopy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from pokesim.app.coordinator import Coordinator
from pokesim.app.registry import Registry, identifier
from pokesim.interactions.cable_metadata import ADAPTER_ID


class Peer:
    def __init__(self, aid, key):
        self.aid = aid
        self.key = key
        self.calls = []
        self.records = {}
        self.failures = {}
        self.owned = [1]
        self.dex = 2

    def request(self, method, path, data=None, timeout=None):
        operation = path.rsplit('/', 1)[-1]
        self.calls.append(operation)
        if self.failures.get(operation, 0):
            self.failures[operation] -= 1
            raise RuntimeError('Injected ' + operation + ' failure')
        if operation == 'inventory':
            return {'offers': [{'trade_key': self.key, 'dex': self.dex, 'arrived_dex': self.dex}], 'owned': self.owned}
        tid = data['id']
        if operation == 'prepare':
            result = {'id': tid, 'phase': 'prepared', 'plan_digest': data['plan_digest'], 'selected_key': data['selected_key'],
                'source': {'adventure_id': self.aid, 'rom_path': '/rom', 'checkpoint_path': '/state',
                           'checkpoint_sha256': 'original', 'party_slot': 0, 'selected_key': data['selected_key']},
                'outgoing': {'struct': '00', 'nickname': '00', 'trainer': '00'}}
            self.records[tid] = result
        elif operation == 'stage':
            self.records[tid].update(phase='staged', attempt_id=data['attempt_id'], staged=data['result'])
        elif operation == 'apply':
            self.records[tid].update(phase='applied', decision='COMMIT')
        elif operation == 'release':
            self.records[tid].update(phase='released')
        elif operation == 'abort':
            self.records.setdefault(tid, {'id': tid}).update(phase='aborted', decision='ABORT')
        return deepcopy(self.records[tid])


class Supervisor:
    def __init__(self, registry, peers):
        self.registry = registry
        self.peers = peers
        self.starts = []
        self.stops = []

    def child(self, aid):
        return self.peers[aid]

    def start(self, aid, recovery=False):
        self.starts.append((aid, recovery))
        assert recovery

    def stop(self, aid):
        self.stops.append(aid)
        self.registry.update(aid, state='stopped')


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('rom', 'sha', 'red')
    games = [registry.create(name, 'rom', {}, identifier()) for name in ['First Red', 'Second Red']]
    for game in games:
        registry.update(game['id'], state='running', desired_state='running')
    peers = {game['id']: Peer(game['id'], str(index)) for index, game in enumerate(games)}
    supervisor = Supervisor(registry, peers)
    manager = SimpleNamespace(root=tmp_path, registry=registry, supervisor=supervisor, suspended=False,
                              assets=SimpleNamespace(game_data_dir=tmp_path), maintenance=threading.RLock())
    coordinator = Coordinator(manager)
    cable_calls = []
    def cable(row, plan):
        cable_calls.append(row['id'])
        return {'status': 'verified', 'schema_version': 1, 'interaction_id': row['id'],
                'attempt_id': row['plan']['attempt_id'], 'adapter_id': ADAPTER_ID,
                'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'participants': {aid: {'adventure_id': aid, 'checkpoint_sha256': 'new-' + aid}
                                 for aid in row['plan']['participants']}}
    coordinator._run_cable = cable
    data = {'left_id': games[0]['id'], 'right_id': games[1]['id'], 'left_key': '0', 'right_key': '1', 'request_id': identifier()}
    yield SimpleNamespace(coordinator=coordinator, registry=registry, peers=peers, supervisor=supervisor,
                          data=data, cable_calls=cable_calls, manager=manager)
    coordinator.close()
    registry.close()


def test_same_request_is_idempotent_and_different_selection_is_rejected(setup):
    c = setup.coordinator
    row = c.propose(setup.data)
    assert c.propose(setup.data)['id'] == row['id']
    with pytest.raises(ValueError, match='another exchange'):
        c.propose({**setup.data, 'left_key': 'changed'})
    with pytest.raises(ValueError, match='current Cable Club'):
        c.propose({**setup.data, 'request_id': identifier()})
    assert c.reserved(setup.data['left_id'])


def test_both_stages_precede_commit_and_both_apply_precede_release(setup):
    c = setup.coordinator
    row = c.propose(setup.data)
    observed = []
    for peer in setup.peers.values():
        original = peer.request
        def request(method, path, data=None, timeout=None, original=original):
            operation = path.rsplit('/', 1)[-1]
            if operation == 'stage':
                assert setup.registry.transaction(row['id'])['decision'] is None
            if operation == 'apply':
                assert setup.registry.transaction(row['id'])['decision'] == 'COMMIT'
                assert observed.count('stage') == 2
            if operation == 'release':
                assert observed.count('apply') == 2
            observed.append(operation)
            return original(method, path, data, timeout)
        peer.request = request
    result = c.execute(row['id'])
    assert result['phase'] == 'completed'
    assert result['decision'] == 'COMMIT'
    assert not c.reserved(setup.data['left_id'])
    calls = len(observed)
    assert c.execute(row['id'])['phase'] == 'completed'
    assert len(observed) == calls
    assert setup.cable_calls == [row['id']]


def test_failed_second_stage_aborts_without_applying_either_output(setup):
    setup.peers[setup.data['right_id']].failures['stage'] = 1
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.execute(row['id'])
    assert result['decision'] == 'ABORT'
    assert result['phase'] == 'aborted'
    assert all('apply' not in peer.calls for peer in setup.peers.values())
    assert all(peer.records[row['id']]['phase'] == 'aborted' for peer in setup.peers.values())


def test_partial_commit_recovery_replays_staged_results_without_another_cable_trade(setup):
    setup.peers[setup.data['right_id']].failures['apply'] = 2
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.execute(row['id'])
    assert result['decision'] == 'COMMIT'
    assert result['phase'] == 'recovering'
    assert setup.coordinator.reserved(setup.data['left_id'])
    assert all('release' not in peer.calls for peer in setup.peers.values())
    with pytest.raises(ValueError, match='committed'):
        setup.coordinator.cancel(row['id'])
    result = setup.coordinator.recover_one(row['id'])
    assert result['phase'] == 'completed'
    assert setup.cable_calls == [row['id']]
    assert all(recovery for _, recovery in setup.supervisor.starts)


def test_cancel_before_execution_durably_aborts_both_participants(setup):
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.cancel(row['id'])
    assert result['decision'] == 'ABORT'
    assert result['phase'] == 'aborted'
    assert setup.cable_calls == []


def test_recovery_aborts_undecided_intent_and_preserves_stop_request(setup):
    row = setup.coordinator.propose(setup.data)
    setup.registry.update(setup.data['left_id'], desired_state='stopped')
    result = setup.coordinator.recover_one(row['id'])
    assert result['phase'] == 'aborted'
    assert setup.data['left_id'] in setup.supervisor.stops
    assert setup.registry.adventure(setup.data['right_id'])['state'] == 'running'
    assert setup.cable_calls == []


def test_failed_abort_keeps_reservation_until_peer_recovers(setup):
    row = setup.coordinator.propose(setup.data)
    setup.peers[setup.data['right_id']].failures['abort'] = 1
    result = setup.coordinator.recover_one(row['id'])
    assert result['phase'] == 'recovering'
    assert result['decision'] == 'ABORT'
    assert setup.coordinator.reserved(setup.data['right_id'])
    assert setup.coordinator.recover_one(row['id'])['phase'] == 'aborted'


def test_wrong_attempt_manifest_cannot_commit(setup):
    original = setup.coordinator._run_cable
    setup.coordinator._run_cable = lambda row, plan: {**original(row, plan), 'attempt_id': 'stale'}
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.execute(row['id'])
    assert result['decision'] == 'ABORT'
    assert all('stage' not in peer.calls for peer in setup.peers.values())


def test_selection_respects_current_owner_eligibility(setup):
    with pytest.raises(ValueError, match='no longer eligible'):
        setup.coordinator.propose({**setup.data, 'left_key': 'locked-or-protected'})
    assert setup.registry.transactions() == []


def test_scheduler_uses_useful_eligible_offers_and_cooldown(setup):
    c = setup.coordinator
    c.configure({'enabled': True, 'participants': list(setup.peers)})
    result = c.schedule_once()
    assert result['phase'] == 'completed'
    assert c.schedule_once() is None
    assert len(setup.cable_calls) == 1


def test_group_cannot_remove_reserved_participant(setup):
    c = setup.coordinator
    c.configure({'enabled': True, 'participants': list(setup.peers)})
    c.propose(setup.data)
    with pytest.raises(ValueError, match='Resolve current'):
        c.configure({'enabled': False, 'participants': []})


def test_unknown_adapter_cannot_reach_staging(setup):
    original = setup.coordinator._run_cable
    setup.coordinator._run_cable = lambda row, plan: {**original(row, plan), 'adapter_id': 'untrusted-adapter'}
    row = setup.coordinator.propose(setup.data)
    result = setup.coordinator.execute(row['id'])
    assert result['decision'] == 'ABORT'
    assert all('stage' not in peer.calls for peer in setup.peers.values())


def test_legacy_trade_provenance_blocks_new_exchange(setup):
    setup.registry.update(setup.data['left_id'], provenance={'trading_blocked': True, 'reason': 'Reconcile legacy peers'})
    with pytest.raises(ValueError, match='Reconcile legacy peers'):
        setup.coordinator.propose(setup.data)
    assert setup.registry.transactions() == []


def test_closing_never_starts_another_participant_request(setup):
    setup.coordinator.closed.set()
    with pytest.raises(RuntimeError, match='shutting down'):
        setup.coordinator.inventory(setup.data['left_id'])
    assert not setup.peers[setup.data['left_id']].calls


def test_scheduler_preserves_quality_benefits_without_new_dex_entries():
    inventory = {'owned': [25], 'party': [{'dex': 25, 'level': 10}], 'storage': {'pokemon': []}}
    assert Coordinator._benefit(inventory, {'dex': 25, 'level': 20}) == 10
    assert Coordinator._benefit(inventory, {'dex': 25, 'level': 10}) == 0
