from copy import deepcopy
import hashlib
import json
import os
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
        self.offer = {}
        self.outgoing = {'struct': '00', 'nickname': '00', 'trainer': '00'}
        self.generation = 1
        self.capsule_ready = False
        self.manual_reason = ''
        self.pokemon = [{'trade_key': key, 'dex': 2, 'name': 'Ivysaur', 'location': 'box', 'box': 1, 'slot': 1,
                         'cartridge_generation': 1, 'blocked': None},
                        {'trade_key': 'party-' + key, 'dex': 25, 'name': 'Pikachu', 'location': 'party', 'slot': 1,
                         'cartridge_generation': 1, 'blocked': None}]
        self.prepared = []

    def request(self, method, path, data=None, timeout=None):
        operation = path.rsplit('/', 1)[-1]
        self.calls.append(operation)
        if self.failures.get(operation, 0):
            self.failures[operation] -= 1
            raise RuntimeError('Injected ' + operation + ' failure')
        if operation == 'inventory':
            return {'offers': [{'trade_key': self.key, 'dex': self.dex, 'arrived_dex': self.dex,
                                **self.offer}], 'owned': self.owned}
        if operation == 'manual-inventory':
            return {'adventure_id': self.aid, 'cartridge_generation': self.generation, 'holding': False,
                    'time_capsule_ready': self.capsule_ready, 'reason': self.manual_reason,
                    'pokemon': deepcopy(self.pokemon)}
        if operation == 'collection_demand':
            self.collection_requests = data['requests']
            return {'requests': data['requests']}
        tid = data['id']
        if operation == 'prepare':
            self.prepared.append(dict(data))
            result = {'id': tid, 'phase': 'prepared', 'plan_digest': data['plan_digest'], 'selected_key': data['selected_key'],
                'source': {'adventure_id': self.aid, 'rom_path': '/rom', 'checkpoint_path': '/state',
                           'checkpoint_sha256': 'original', 'party_slot': 0, 'selected_key': data['selected_key']},
                'outgoing': deepcopy(self.outgoing)}
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


def test_collection_requests_work_for_one_or_multiple_adventures(setup):
    c = setup.coordinator
    left, right = setup.data['left_id'], setup.data['right_id']
    c._refresh_collection_demand([(left, {'owned': list(range(1, 152))}),
                                 (right, {'owned': [dex for dex in range(1, 152) if dex != 69]})])
    assert setup.peers[left].collection_requests == {'69': 1}
    assert setup.peers[right].collection_requests == {}
    c._refresh_collection_demand([(left, {'owned': list(range(1, 152))})])
    assert setup.peers[left].collection_requests == {}


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
    announced = []
    manager.notifications = SimpleNamespace(trade_completed=lambda row, display: announced.append(row['id']))
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
                          data=data, cable_calls=cable_calls, manager=manager, announced=announced)
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
    assert setup.announced == [row['id']]


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
    result = c.schedule_once()
    assert result['phase'] == 'completed'
    assert c.schedule_once() is None
    assert len(setup.cable_calls) == 1


def test_failed_trades_remain_visible_after_idle_poll_and_coordinator_restart(setup):
    c = setup.coordinator
    error = 'No supported walking route to the Cable Club is available yet'
    for _ in range(3):
        row = c.propose({**setup.data, 'request_id': identifier()})
        setup.registry.update_transaction(row['id'], phase='aborted', decision='ABORT', error=error)
    assert c.schedule_once() is None
    restarted = Coordinator(setup.manager)
    for coordinator in (c, restarted):
        global_status = coordinator.status()
        scoped = coordinator.adventure_status(setup.data['left_id'])
        for status in (global_status, scoped):
            assert status['attention']['recent_failure_count'] == 3
            assert 'could not reach the Cable Club' in status['attention']['reason']
            assert len(status['recent_failures']) == 3
        assert '3 recent trade attempts did not complete' in global_status['message']
        assert scoped['history'] == []
        assert scoped['recent_failures'][0]['peer_name'] == 'Second Red'
        assert 'error' not in scoped['recent_failures'][0]


def test_failure_warning_is_scoped_and_clears_after_success(setup):
    c = setup.coordinator
    row = c.propose(setup.data)
    setup.registry.update_transaction(row['id'], phase='aborted', decision='ABORT', error='private /worker/path')
    other = setup.registry.create('Unrelated Red', 'rom', {}, identifier())
    assert c.adventure_status(other['id'])['attention'] is None
    assert c.adventure_status(other['id'])['recent_failures'] == []
    assert 'private' not in c.status()['attention']['message']
    successful = c.propose({**setup.data, 'request_id': identifier()})
    c.execute(successful['id'])
    for status in (c.status(), c.adventure_status(setup.data['left_id'])):
        assert status['attention'] is None
        assert len(status['recent_failures']) == 1


@pytest.mark.parametrize(('error', 'reason'), [
    ('The route to the Cable Club is blocked by an unresolved obstacle', 'obstacle still blocks'),
    ('Cable Club preparation exceeded its travel deadline', 'took too long'),
    ('Every PC box is full. A free slot is needed to prepare this trade', 'free PC slot'),
    ('The route to the Cable Club needs a partner with Strength', 'partner with Strength'),
    ('Cable Club preparation stopped making progress', 'stopped making progress'),
    ('No safe unprotected reserve can leave the party for this trade', 'safely make room'),
])
def test_preparation_failure_has_a_specific_explanation_in_both_views(setup, error, reason):
    c = setup.coordinator
    row = c.propose(setup.data)
    setup.registry.update_transaction(row['id'], phase='aborted', decision='ABORT', error=error)
    for status in (c.status(), c.adventure_status(setup.data['left_id'])):
        assert reason in status['attention']['reason']
        assert status['recent_failures'][0]['failure_reason'] == status['attention']['reason']


def test_new_games_join_automatically_despite_obsolete_group_settings(setup):
    setup.registry.set_setting('trading', {'enabled': False, 'participants': []})
    old_id = setup.data['left_id']
    setup.registry.update(old_id, state='stopped', desired_state='stopped', archived=True)
    new = setup.registry.create('New Red', 'rom', {}, identifier())
    setup.registry.update(new['id'], state='running', desired_state='running')
    setup.peers[new['id']] = Peer(new['id'], 'new-offer')
    status = setup.coordinator.status()
    assert status['enabled']
    assert old_id not in status['participants']
    assert new['id'] in status['participants']
    result = setup.coordinator.schedule_once()
    assert result['phase'] == 'completed'
    assert new['id'] in result['plan']['participants']
    assert old_id not in result['plan']['participants']


def test_scheduler_recovers_committed_exchange_without_manual_action(setup):
    setup.peers[setup.data['right_id']].failures['apply'] = 2
    row = setup.coordinator.propose(setup.data)
    assert setup.coordinator.execute(row['id'])['phase'] == 'recovering'
    assert setup.coordinator.schedule_once()['phase'] == 'completed'
    assert setup.cable_calls == [row['id']]


def test_failed_automatic_recovery_is_bounded_and_preserves_reservation(setup):
    peer = setup.peers[setup.data['right_id']]
    peer.failures['apply'] = 10
    row = setup.coordinator.propose(setup.data)
    assert setup.coordinator.execute(row['id'])['phase'] == 'recovering'
    assert setup.coordinator.schedule_once()['phase'] == 'recovering'
    calls = len(peer.calls)
    assert setup.coordinator.schedule_once() is None
    assert len(peer.calls) == calls
    assert setup.coordinator.reserved(peer.aid)
    assert setup.cable_calls == [row['id']]


@pytest.mark.parametrize('change', [
    {'state': 'stopped', 'desired_state': 'stopped'},
    {'desired_state': 'stopped'},
    {'provenance': {'trading_blocked': True}},
])
def test_automatic_scheduler_skips_ineligible_adventures(setup, change):
    setup.registry.update(setup.data['left_id'], **change)
    assert setup.coordinator.schedule_once() is None
    assert setup.cable_calls == []


def test_scheduler_does_not_abort_an_exchange_waiting_for_execution(setup):
    row = setup.coordinator.propose(setup.data)
    assert setup.coordinator.schedule_once() is None
    assert setup.registry.transaction(row['id'])['decision'] is None


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


def trade_display_fixture(setup, nickname='HAUNTER'):
    c = setup.coordinator
    c.display_species = {'147': {'name': 'Haunter', 'dex': 93},
                         '14': {'name': 'Gengar', 'dex': 94},
                         '185': {'name': 'Oddish', 'dex': 43}}
    left, right = setup.data['left_id'], setup.data['right_id']
    for aid, species, name, nick, level in [(left, 147, 'Haunter', nickname, 32),
                                           (right, 185, 'Oddish', 'SPROUT', 12)]:
        peer = setup.peers[aid]
        peer.offer = {'species': species, 'name': name, 'nick': nick, 'level': level,
                      'dex': c.display_species[str(species)]['dex']}
        raw = bytearray(44)
        raw[0] = species
        raw[33] = level + (1 if aid == left else 0)
        encoded = bytes(ord(char) - ord('A') + 0x80 for char in nick).ljust(11, b'\x50')
        peer.outgoing = {'struct': raw.hex(), 'nickname': encoded.hex(), 'trainer': 'private-trainer'}
    original = c._run_cable

    def cable(row, plan):
        result = original(row, plan)
        result['participants'][left]['evidence'] = {
            'incoming_species': 185, 'received_species': 185, 'default_name_evolved': False}
        result['participants'][right]['evidence'] = {
            'incoming_species': 147, 'received_species': 14, 'default_name_evolved': nickname == 'HAUNTER'}
        return result

    c._run_cable = cable
    return left, right


def test_active_trade_display_persists_each_selected_offer(setup):
    left, right = trade_display_fixture(setup)
    row = setup.coordinator.propose(setup.data)
    for peer in setup.peers.values():
        peer.offer = {'name': 'Changed after proposal', 'nick': 'DIFFERENT', 'level': 99}
        peer.failures['inventory'] = 1
    for aid, peer_id, sent_name, received_name in [(left, right, 'Haunter', 'Oddish'),
                                                  (right, left, 'Oddish', 'Haunter')]:
        entry = setup.coordinator.adventure_status(aid)['active'][0]
        assert entry['peer_id'] == peer_id
        assert entry['sent']['name'] == sent_name
        assert entry['received']['name'] == received_name
        assert entry['received']['evolved_from'] is None
        assert entry['sent']['sprite_url'] == f"/games/{aid}/sprites/{entry['sent']['dex']}.png?v=rom-portraits-1"
        assert 'trade_key' not in entry['sent']
    assert row['plan']['display_offers'][left]['level'] == 32


@pytest.mark.parametrize('nickname,received_nickname', [('HAUNTER', 'GENGAR'), ('CASPER', 'CASPER')])
def test_completed_display_uses_actual_receipts_and_evolution(setup, nickname, received_nickname):
    left, right = trade_display_fixture(setup, nickname)
    c = setup.coordinator
    row = c.propose(setup.data)
    result = c.execute(row['id'])
    assert result['phase'] == 'completed'
    assert result['result']['display'][left]['sent']['level'] == 33
    restarted = Coordinator(setup.manager)
    restarted.display_species = c.display_species
    restarted._historical_receipt = lambda *args: pytest.fail('New results already contain durable display details')
    for coordinator in (c, restarted):
        shared = coordinator.status()['history'][0]['display']
        assert shared[left]['received']['name'] == 'Oddish'
        assert shared[right]['received']['name'] == 'Gengar'
        assert shared[right]['received']['evolved_from']['name'] == 'Haunter'
        assert shared[right]['received']['level'] == 33
        sent = coordinator.adventure_status(left)['history'][0]
        received = coordinator.adventure_status(right)['history'][0]
        assert sent['sent']['name'] == 'Haunter'
        assert sent['sent']['nickname'] == nickname
        assert sent['sent']['level'] == 33
        assert sent['received']['name'] == 'Oddish'
        assert sent['received']['nickname'] == 'SPROUT'
        assert received['sent']['name'] == 'Oddish'
        assert received['received']['name'] == 'Gengar'
        assert received['received']['nickname'] == received_nickname
        assert received['received']['dex'] == 94
        assert received['received']['evolved_from'] == {'name': 'Haunter', 'species': 147, 'dex': 93}
        assert received['received']['level'] == 33
        assert not any(private in json.dumps(received) for private in ('private-trainer', 'outgoing', 'struct', 'checkpoint'))


def legacy_completed_trade(setup, *, receipts=True, evidence=True):
    import sqlite3
    left, right = trade_display_fixture(setup)
    c = setup.coordinator
    row = c.propose(setup.data)
    result = c.execute(row['id'])
    plan = dict(result['plan'])
    plan.pop('display_offers')
    with setup.registry.db:
        setup.registry.db.execute('UPDATE interactions SET plan=? WHERE id=?', (json.dumps(plan), row['id']))
    manifest = deepcopy(result['result'])
    manifest.pop('display')
    if not evidence:
        for participant in manifest['participants'].values():
            participant.pop('evidence')
    setup.registry.update_transaction(row['id'], result=manifest)
    if receipts:
        for aid in (left, right):
            path = setup.manager.root / 'adventures' / aid / 'pokesim.sqlite'
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)')
                connection.execute('INSERT INTO kv VALUES (?, ?)',
                    ('managed_interaction:' + row['id'], json.dumps(setup.peers[aid].records[row['id']])))
    return left, right, row['id']


def test_historical_trade_uses_read_only_receipts_and_caches_without_workers(setup):
    left, right, tid = legacy_completed_trade(setup)
    for peer in setup.peers.values():
        peer.request = lambda *args, **kwargs: pytest.fail('History must not inspect current inventory')
    entry = setup.coordinator.adventure_status(right)['history'][0]
    assert entry['sent']['nickname'] == 'SPROUT'
    assert entry['received']['name'] == 'Gengar'
    assert entry['received']['nickname'] == 'GENGAR'
    assert entry['received']['level'] == 33
    setup.coordinator._historical_receipt = lambda *args: pytest.fail('Repeated history polls should use cached details')
    assert setup.coordinator.adventure_status(right)['history'][0] == entry
    assert setup.coordinator.adventure_status(left)['history'][0]['sent']['nickname'] == 'HAUNTER'


def test_historical_trade_with_only_species_evidence_keeps_unknown_fields_empty(setup):
    left, right, tid = legacy_completed_trade(setup, receipts=False)
    entry = setup.coordinator.adventure_status(right)['history'][0]
    assert entry['sent']['name'] == 'Oddish'
    assert entry['sent']['nickname'] is None
    assert entry['sent']['level'] is None
    assert entry['received']['name'] == 'Gengar'
    assert entry['received']['level'] is None


def test_historical_trade_without_details_does_not_guess_from_current_inventory(setup):
    left, right, tid = legacy_completed_trade(setup, receipts=False, evidence=False)
    for aid in (left, right):
        entry = setup.coordinator.adventure_status(aid)['history'][0]
        assert entry['sent'] is None
        assert entry['received'] is None
        assert not (setup.manager.root / 'adventures' / aid / 'pokesim.sqlite').exists()


def test_resolved_interaction_directories_are_pruned_but_unresolved_ones_are_kept(setup):
    """Each attempt keeps two save states, two cartridge saves and two screenshots.

    Nothing reads them once the exchange is resolved, and every backup copies the whole
    tree, so a library that has traded for months otherwise carries all of it forever.
    """
    root = setup.manager.root / 'interactions'
    for index in range(25):
        attempt = root / f'old-{index:02d}' / 'attempts' / 'a'
        attempt.mkdir(parents=True)
        (attempt / 'plan.json').write_bytes(b'{}')
        # Filesystem timestamp resolution must not decide the retention order.
        timestamp = 1_700_000_000 + index
        os.utime(root / f'old-{index:02d}', (timestamp, timestamp))

    row = setup.coordinator.propose(setup.data)
    live = root / row['id'] / 'attempts' / row['plan']['attempt_id']
    live.mkdir(parents=True, exist_ok=True)
    (live / 'plan.json').write_bytes(b'{}')

    removed = setup.coordinator._prune_interactions(keep=10)
    remaining = {path.name for path in root.iterdir() if path.is_dir()}
    assert removed == 15
    assert row['id'] in remaining, 'an unresolved exchange must keep its outputs for recovery'
    assert len(remaining) == 11
    assert 'old-24' in remaining and 'old-00' not in remaining


def test_pruning_keeps_everything_when_retention_is_zero(setup):
    """Zero means unlimited here, the same as it does for autosaves and stall bundles."""
    root = setup.manager.root / 'interactions'
    for index in range(3):
        (root / f'old-{index}').mkdir(parents=True)
    assert setup.coordinator._prune_interactions(keep=0) == 0
    assert len([path for path in root.iterdir() if path.is_dir()]) == 3


def test_a_failing_recovery_backs_off_instead_of_retrying_every_thirty_seconds(setup):
    """A recovery that cannot succeed used to be re-driven twice a minute forever.

    Each pass calls supervisor.start(recovery=True), so the churn also restarts a worker
    the operator had stopped. Retries still never give up — a committed exchange has to be
    finished on both sides — they just stop consuming the machine while they wait.
    """
    coordinator = setup.coordinator
    tid = 'c' * 32
    assert coordinator.recovery_delay(tid) == 30

    for expected in (30, 60, 120, 240, 480, 600, 600):
        coordinator.recovery_failures[tid] = coordinator.recovery_failures.get(tid, 0) + 1
        assert coordinator.recovery_delay(tid) == expected

    coordinator.recovery_failures.pop(tid, None)
    assert coordinator.recovery_delay(tid) == 30


def test_a_successful_recovery_clears_the_backoff(setup):
    row = setup.coordinator.propose(setup.data)
    setup.coordinator.recovery_failures[row['id']] = 4
    setup.coordinator.recover_one(row['id'])
    assert row['id'] not in setup.coordinator.recovery_failures


def test_a_slow_inventory_blocks_neither_the_trading_page_nor_adventure_starts(setup):
    c = setup.coordinator
    left = setup.peers[setup.data['left_id']]
    asked, answer = threading.Event(), threading.Event()
    original = left.request

    def slow(method, path, data=None, timeout=None):
        if path.endswith('/inventory'):
            asked.set()
            assert answer.wait(10)
        return original(method, path, data, timeout)

    left.request = slow
    result = {}
    worker = threading.Thread(target=lambda: result.update(row=c.propose(setup.data)))
    worker.start()
    assert asked.wait(10)
    try:
        # The page and a start both answer while the worker is still thinking.
        for lock in (c.view_guard, c.guard, setup.manager.maintenance):
            acquired = []
            reader = threading.Thread(target=lambda: acquired.append(lock.acquire(timeout=1) and lock.release() is None))
            reader.start()
            reader.join()
            assert acquired == [True]
        assert c.status()['active'] == []
        assert c.preview(setup.data['left_id']) is None
    finally:
        answer.set()
        worker.join(10)
    assert result['row']['phase'] and c.reserved(setup.data['left_id'])


def test_an_exchange_started_meanwhile_wins_over_a_slow_proposal(setup):
    c = setup.coordinator
    left = setup.peers[setup.data['left_id']]
    original = left.request
    first = []

    def racing(method, path, data=None, timeout=None):
        if path.endswith('/inventory') and not first:
            first.append(True)
            c.propose({**setup.data, 'request_id': identifier()})
        return original(method, path, data, timeout)

    left.request = racing
    with pytest.raises(ValueError, match='current Cable Club'):
        c.propose(setup.data)
    assert len(setup.registry.transactions(unresolved=True)) == 1


def test_an_adventure_stopped_meanwhile_cancels_a_slow_proposal(setup):
    c = setup.coordinator
    left = setup.peers[setup.data['left_id']]
    original = left.request

    def stopping(method, path, data=None, timeout=None):
        if path.endswith('/inventory'):
            setup.registry.update(setup.data['right_id'], state='stopped', desired_state='stopped')
        return original(method, path, data, timeout)

    left.request = stopping
    with pytest.raises(ValueError, match='must be running'):
        c.propose(setup.data)
    assert setup.registry.transactions(unresolved=True) == []


@pytest.mark.parametrize('speeds,expected', [((4, 16), 4), ((0, 4), 4), ((8, 0), 8), ((0, 0), 0), ((0.5, 1), 0.5)])
def test_cable_uses_slower_participant_without_changing_individual_paces(setup, speeds, expected):
    ids = (setup.data['left_id'], setup.data['right_id'])
    prepared = {}
    for aid, speed in zip(ids, speeds):
        setup.registry.update(aid, settings={'speed': speed})
        prepared[aid] = {'source': {'adventure_id': aid, 'rom_path': '/rom', 'checkpoint_path': '/state'}}
    row = {'id': identifier(), 'plan': {'attempt_id': identifier(), 'participants': ids}}
    assert setup.coordinator._session_plan(row, prepared)['speed'] == expected
    assert tuple(setup.registry.adventure(aid)['settings']['speed'] for aid in ids) == speeds


def test_time_capsule_pair_requires_readiness_and_compatible_offer():
    old = {'cartridge_generation': 1}
    modern = {'cartridge_generation': 2, 'time_capsule_ready': True}
    offer = {'time_capsule_compatible': True, 'cartridge_generation': 2, 'dex': 95, 'arrived_dex': 208}
    assert Coordinator._compatible_pair(old, modern, {}, offer)
    assert Coordinator._compatible_pair(modern, old, offer, {})
    assert not Coordinator._compatible_pair(old, {**modern, 'time_capsule_ready': False}, {}, offer)
    assert not Coordinator._compatible_pair(old, modern, {}, {**offer, 'time_capsule_compatible': False})
    assert Coordinator._offer_for(offer, old)['arrived_dex'] == 95
    assert Coordinator._offer_for(offer, modern)['arrived_dex'] == 208
    assert Coordinator._offer_for({**offer, 'dex': 64}, old)['arrived_dex'] == 65


def test_collection_requests_cross_generations_only_for_kanto_species(setup):
    left, right = setup.data['left_id'], setup.data['right_id']
    setup.coordinator._refresh_collection_demand([
        (left, {'cartridge_generation': 1, 'owned': list(range(1, 152))}),
        (right, {'cartridge_generation': 2, 'dex_total': 251,
                 'owned': [dex for dex in range(1, 252) if dex not in {1, 251}]})])
    assert setup.peers[left].collection_requests == {'1': 1}
    assert setup.peers[right].collection_requests == {}


def manual_request(setup, left_key='party-0', right_key='party-1'):
    return {'left_id': setup.data['left_id'], 'right_id': setup.data['right_id'],
            'left_key': left_key, 'right_key': right_key, 'request_id': identifier()}


def test_manual_trade_ignores_offers_locks_and_last_copies(setup):
    c = setup.coordinator
    for peer in setup.peers.values():
        peer.owned = []    # Every automatic last-copy rule would refuse this pair.
        peer.offer = {'trade_key': 'something-else'}
    entry = c.enqueue_manual(manual_request(setup))
    assert c.manual_status(entry['id'])['state'] == 'queued'
    assert c.manual_status(entry['id'])['position'] == 1
    result = c.drain_manual()
    assert result['phase'] == 'completed'
    row = setup.registry.transaction(entry['id'])
    assert row['plan']['manual'] is True
    assert row['plan']['left_key'] == 'party-0'
    assert setup.cable_calls == [entry['id']]
    assert all(peer.prepared[-1]['manual'] is True for peer in setup.peers.values())
    status = c.manual_status(entry['id'])
    assert status['state'] == 'started'
    assert status['phase'] == 'completed'
    assert status['cancellable'] is False
    assert not c.manual_waiting()


def test_manual_trade_is_idempotent_and_rejects_hard_limits_with_a_reason(setup):
    c = setup.coordinator
    data = manual_request(setup)
    entry = c.enqueue_manual(data)
    assert c.enqueue_manual(data)['id'] == entry['id']
    with pytest.raises(ValueError, match='another trade'):
        c.enqueue_manual({**data, 'left_key': 'other'})
    with pytest.raises(ValueError, match='different adventures'):
        c.enqueue_manual({**manual_request(setup), 'right_id': data['left_id']})
    setup.peers[data['left_id']].pokemon[1]['blocked'] = 'Eggs cannot be traded'
    c.drain_manual()
    status = c.manual_status(entry['id'])
    assert status['state'] == 'rejected'
    assert status['error'] == 'Eggs cannot be traded'
    assert setup.cable_calls == []


def test_manual_trade_explains_time_capsule_limits(setup):
    c = setup.coordinator
    modern = setup.peers[setup.data['right_id']]
    modern.generation = 2
    for mon in modern.pokemon:
        mon.update(cartridge_generation=2, time_capsule_compatible=False, time_capsule_reason='Togepi did not exist in Gen I')
    first = c.enqueue_manual(manual_request(setup))
    c.drain_manual()
    assert 'cannot use the Time Capsule yet' in c.manual_status(first['id'])['error']
    modern.capsule_ready = True
    second = c.enqueue_manual(manual_request(setup))
    c.drain_manual()
    assert 'Togepi did not exist in Gen I' in c.manual_status(second['id'])['error']
    assert setup.registry.transactions() == []


def test_manual_trades_run_in_order_ahead_of_the_scheduler(setup):
    c = setup.coordinator
    first = c.enqueue_manual(manual_request(setup))
    second = c.enqueue_manual(manual_request(setup, '0', '1'))
    assert c.manual_status(second['id'])['position'] == 2
    result = c.schedule_once()
    assert result['phase'] == 'completed'
    assert setup.cable_calls == [first['id'], second['id']]
    assert all(row['plan'].get('manual') for row in setup.registry.transactions())


def test_manual_trade_waits_for_a_busy_cable_club_and_sets_aside_automatic_trades(setup):
    c = setup.coordinator
    automatic = c.propose(setup.data)
    entry = c.enqueue_manual(manual_request(setup))
    assert c.drain_manual() is None
    row = setup.registry.transaction(automatic['id'])
    assert row['decision'] == 'ABORT'
    assert c._failure_reason({**row, 'phase': 'aborted'}) == 'This automatic trade made way for a trade you chose.'
    assert c.manual_status(entry['id'])['state'] == 'queued'
    assert c.recover_one(automatic['id'])['phase'] == 'aborted'
    assert c.drain_manual()['phase'] == 'completed'
    assert setup.cable_calls == [entry['id']]


def test_manual_trade_waits_when_execution_is_already_running(setup):
    c = setup.coordinator
    entry = c.enqueue_manual(manual_request(setup))
    assert c.execution.acquire(blocking=False)
    try:
        assert c.drain_manual() is None
    finally:
        c.execution.release()
    assert c.manual_status(entry['id'])['state'] == 'queued'


def test_cancelling_manual_trades_before_commit(setup):
    c = setup.coordinator
    queued = c.enqueue_manual(manual_request(setup))
    status = c.cancel_manual(queued['id'])
    assert status['state'] == 'cancelled'
    assert status['cancellable'] is False
    assert not c.manual_waiting()
    starting = c.enqueue_manual(manual_request(setup))
    c._manual_update(starting['id'], state='starting')
    assert c.cancel_manual(starting['id'])['cancellable'] is False
    c._manual_update(starting['id'], state='queued')    # A restart puts it back in line with the request kept.
    result = c.drain_manual()
    assert result['phase'] == 'aborted'
    assert setup.registry.transaction(starting['id'])['error'] == 'Cancelled by the owner'
    assert setup.cable_calls == []
    started = c.enqueue_manual(manual_request(setup))
    row = c.propose({**{name: started[name] for name in ('left_id', 'right_id', 'left_key', 'right_key')},
                     'request_id': started['id'], 'manual': True})
    c._manual_update(started['id'], state='started')
    assert c.manual_status(started['id'])['cancellable'] is True
    status = c.cancel_manual(row['id'])
    assert status['phase'] == 'aborted'
    assert status['failure_reason'] == 'This exchange was cancelled.'
    with pytest.raises(KeyError):
        c.cancel_manual(identifier())


def test_a_trade_cut_off_while_starting_is_resumed_after_restart(setup):
    c = setup.coordinator
    entry = c.enqueue_manual(manual_request(setup))
    c._manual_update(entry['id'], state='starting')
    assert c.drain_manual()['phase'] == 'completed'
    assert c.manual_status(entry['id'])['phase'] == 'completed'


def test_manual_options_list_every_pokemon_and_unavailable_adventures(setup):
    c = setup.coordinator
    setup.registry.update(setup.data['right_id'], state='stopped', desired_state='stopped')
    options = {game['id']: game for game in c.manual_options()['adventures']}
    left = options[setup.data['left_id']]
    assert left['available'] is True
    assert [mon['trade_key'] for mon in left['pokemon']] == ['0', 'party-0']
    assert left['pokemon'][1]['sprite_url'].startswith(f"/games/{setup.data['left_id']}/sprites/25.png")
    right = options[setup.data['right_id']]
    assert right['available'] is False
    assert right['reason'] == 'Start this adventure to trade from it'
    assert right['pokemon'] == []
    with pytest.raises(ValueError, match='Start this adventure'):
        c.enqueue_manual(manual_request(setup))


def test_gen2_trade_displays_read_species_data_once(setup, monkeypatch):
    """Loading a Gen II bundle parses and checksums about 3 MB; the trading page polls every few seconds."""
    from pokesim.gen2.data import GameData
    (setup.manager.root / 'gen2' / 'crystal').mkdir(parents=True)
    loads = []
    def load(root, game):
        loads.append(game)
        return SimpleNamespace(species={152: {'name': 'Chikorita'}})
    monkeypatch.setattr(GameData, 'load', load)
    c = setup.coordinator
    for _ in range(50):
        shown = c._mon_display({'species': 152, 'cartridge_generation': 2, 'level': 5})
        assert shown['name'] == 'Chikorita' and shown['dex'] == 152 and shown['level'] == 5
    assert loads == ['crystal']


def test_trade_views_build_only_the_rows_they_return(setup):
    registry, c = setup.registry, setup.coordinator
    left, right = setup.data['left_id'], setup.data['right_id']
    for phase, decision in [('completed', 'COMMIT')] * 300 + [('aborted', 'ABORT')] * 10:
        row = registry.create_transaction(identifier(), {'participants': [left, right], 'left_id': left, 'right_id': right})
        registry.update_transaction(row['id'], phase=phase, decision=decision)
    built = []
    original = c._trade_display
    c._trade_display = lambda row, *args, **kwargs: built.append(row['id']) or original(row, *args, **kwargs)
    status = c.status()
    assert len(status['history']) == 100 and len(status['recent_failures']) == 5
    assert len(built) <= 105
    built.clear()
    mine = c.adventure_status(left)
    assert len(mine['history']) == 20 and len(mine['recent_failures']) == 5 and mine['active'] == []
    assert len(built) <= 25
