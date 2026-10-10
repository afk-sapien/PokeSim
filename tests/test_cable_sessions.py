"""Manual Cable Club sessions: party invariants, lifecycle and rollback."""
import asyncio
import hashlib
import json
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from pokesim.app import cable_sessions
from pokesim.app.coordinator import Coordinator
from pokesim.app.registry import Registry, identifier
from pokesim.gen2.data import GameData
from pokesim.gen2.manual_session import verify_parties
from pokesim.interactions.cable import CableError


def mon(species, ident):
    struct = bytearray(48)
    struct[0] = species
    struct[6:8] = ident.to_bytes(2, 'big')
    return {'struct': bytes(struct), 'nickname': bytes([0x80 + species % 26]) + b'\x50' * 10,
            'trainer': b'\x80\x81\x50' + b'\x00' * 8}


PIDGEOT, ODDISH, GYARADOS, DODRIO = mon(18, 1), mon(43, 2), mon(130, 3), mon(85, 4)
# Gen II item numbers, the same in Gold, Silver and Crystal.
ITEMS = {'EVERSTONE': 0x70, 'KINGS_ROCK': 0x52, 'METAL_COAT': 0x8F, 'DRAGON_SCALE': 0x97, 'UP_GRADE': 0xAC}


def test_a_one_for_one_swap_passes_with_evidence():
    before = [[PIDGEOT, ODDISH], [GYARADOS, DODRIO]]
    after = [[GYARADOS, ODDISH], [PIDGEOT, DODRIO]]
    left, right = verify_parties(before, after, [1, 1])
    assert left['sent_species'] == [18] and left['received_species'] == 130
    assert right['sent_species'] == [130] and right['received_species'] == 18


def test_a_trade_evolution_is_accepted_only_for_the_traded_pokemon():
    haunter, gengar = mon(93, 5), mon(94, 5)
    before = [[haunter, ODDISH], [GYARADOS]]
    after = [[GYARADOS, ODDISH], [gengar]]
    gengar_row = {**gengar, 'struct': gengar['struct']}
    # The fingerprint ignores species, so Gengar still counts as the Haunter that left.
    evidence = verify_parties(before, [[GYARADOS, ODDISH], [gengar_row]], [1, 1], evolve=lambda raw: 94)
    assert evidence[1]['received'] == [{'species': 94, 'incoming_species': 93}]
    with pytest.raises(CableError, match='unexpected species'):
        verify_parties(before, after, [1, 1], evolve=lambda raw: 93)


@pytest.mark.parametrize('after,trades,message', [
    ([[GYARADOS, ODDISH], [GYARADOS, DODRIO]], [1, 1], 'keep the same'),
    ([[PIDGEOT, PIDGEOT], [GYARADOS, DODRIO]], [1, 1], 'keep the same'),
    ([[GYARADOS], [PIDGEOT, DODRIO]], [1, 1], 'party size'),
    ([[GYARADOS, ODDISH], [PIDGEOT, DODRIO]], [1, 0], 'different number'),
    ([[GYARADOS, DODRIO], [PIDGEOT, ODDISH]], [1, 1], 'more Pokémon than it traded'),
    ([[GYARADOS, ODDISH], [PIDGEOT, DODRIO]], [0, 0], 'more Pokémon than it traded'),
])
def test_duplication_loss_and_unsaved_moves_are_rejected(after, trades, message):
    with pytest.raises(CableError, match=message):
        verify_parties([[PIDGEOT, ODDISH], [GYARADOS, DODRIO]], after, trades)


def test_a_stranger_cannot_appear_in_either_party():
    stranger = mon(150, 9)
    with pytest.raises(CableError):
        verify_parties([[PIDGEOT, ODDISH], [GYARADOS, DODRIO]], [[stranger, ODDISH], [PIDGEOT, DODRIO]], [1, 1])


# The session lifecycle against a fake worker process.

FAKE_WORKER = textwrap.dedent('''
    import hashlib, json, sys
    from pathlib import Path
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    plan = json.loads(Path(args['--plan']).read_text())
    out = Path(args['--out'])
    out.mkdir(parents=True)
    print(json.dumps({'phase': 'in_session', 'trades': 0}), flush=True)
    trades = 0
    for line in sys.stdin:
        command = json.loads(line)
        if command.get('button') == 'a':
            trades = 1
            print(json.dumps({'phase': 'in_session', 'trades': trades}), flush=True)
        if command.get('finish'):
            if not trades:
                print('Finished without a trade', flush=True)
                sys.exit(3)
            print(json.dumps({'phase': 'verifying', 'trades': trades}), flush=True)
            before, after, adapter = json.loads(sys.argv[-1])
            ids = [plan['left']['adventure_id'], plan['right']['adventure_id']]
            sha = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            manifest = {'status': 'verified', 'schema_version': 1, 'interaction_id': plan['interaction_id'],
                        'attempt_id': plan['attempt_id'], 'adapter_id': adapter, 'plan_sha256': sha, 'trades': trades,
                        'participants': {aid: {'adventure_id': aid, 'checkpoint_sha256': 'new-' + aid,
                                               'party_before': before[i], 'party_after': after[i],
                                               'evidence': {'trades': trades}} for i, aid in enumerate(ids)}}
            (out / 'manifest.json').write_text(json.dumps(manifest))
            sys.exit(0)
    sys.exit(1)
''')


def hexed(parties):
    return [[{key: value.hex() for key, value in row.items()} for row in rows] for rows in parties]


class Peer:
    def __init__(self, aid):
        self.aid = aid
        self.calls = []
        self.records = {}

    def request(self, method, path, data=None, timeout=None):
        operation = path.rsplit('/', 1)[-1]
        self.calls.append((operation, dict(data or {})))
        tid = data['id']
        if operation == 'prepare':
            self.records[tid] = {'id': tid, 'phase': 'prepared', 'plan_digest': data['plan_digest'], 'selected_key': None,
                                 'session': True, 'source': {'adventure_id': self.aid, 'rom_path': '/rom',
                                 'checkpoint_path': '/state', 'checkpoint_sha256': 'original', 'party_slot': 0,
                                 'selected_key': None}, 'outgoing': None}
        elif operation == 'stage':
            self.records[tid].update(phase='staged', attempt_id=data['attempt_id'], staged=data['result'])
        elif operation == 'apply':
            self.records[tid].update(phase='applied', decision='COMMIT')
        elif operation == 'release':
            self.records[tid].update(phase='released')
        elif operation == 'abort':
            self.records.setdefault(tid, {'id': tid}).update(phase='aborted', decision='ABORT')
        return dict(self.records[tid])

    def operations(self):
        return [operation for operation, _ in self.calls]


@pytest.fixture
def club(tmp_path, monkeypatch):
    from pokesim.gen2.cable_metadata import ADAPTER_ID
    registry = Registry(tmp_path)
    registry.add_rom('gold', 'sha-gold', 'gold')
    registry.add_rom('silver', 'sha-silver', 'silver')
    registry.add_rom('red', 'sha-red', 'red')
    games = [registry.create(name, rom, {}, identifier())
             for name, rom in (('Gold', 'gold'), ('Silver', 'silver'), ('Red', 'red'))]
    for game in games:
        registry.update(game['id'], state='running', desired_state='running')
    peers = {game['id']: Peer(game['id']) for game in games}
    supervisor = SimpleNamespace(child=lambda aid: peers[aid], start=lambda aid, recovery=False: None,
                                 stop=lambda aid: None)
    manager = SimpleNamespace(root=tmp_path, registry=registry, supervisor=supervisor, suspended=False,
                              assets=SimpleNamespace(game_data_dir=tmp_path), maintenance=threading.RLock(),
                              notifications=SimpleNamespace(trade_completed=lambda row, display: None))
    coordinator = Coordinator(manager)
    coordinator.prepare_poll = 0.01
    monkeypatch.setattr(coordinator, '_trade_display', lambda row, *args: {'trade': 'shown'})
    worker = tmp_path / 'fake_worker.py'
    worker.write_text(FAKE_WORKER)
    parties = {'parties': [hexed([[PIDGEOT, ODDISH], [GYARADOS, DODRIO]]),
                           hexed([[GYARADOS, ODDISH], [PIDGEOT, DODRIO]])]}
    real_popen = subprocess.Popen

    processes = []

    def popen(command, **kwargs):
        arguments = command[command.index('--plan'):]
        payload = json.dumps([*parties['parties'], ADAPTER_ID])
        processes.append(real_popen([sys.executable, str(worker), *arguments, payload], **kwargs))
        return processes[-1]
    monkeypatch.setattr(cable_sessions.subprocess, 'Popen', popen)
    loaded = []

    def load(root, version):
        loaded.append((root, version))
        return SimpleNamespace(items=ITEMS)
    monkeypatch.setattr(GameData, 'load', staticmethod(load))
    yield SimpleNamespace(coordinator=coordinator, sessions=coordinator.sessions, registry=registry, peers=peers,
                          gold=games[0]['id'], silver=games[1]['id'], red=games[2]['id'], parties=parties,
                          loaded=loaded, processes=processes)
    coordinator.close()
    registry.close()


def wait_for(sessions, sid, phases, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = sessions.status(sid)
        if status['phase'] in phases:
            return status
        time.sleep(0.05)
    raise AssertionError(f'Session stayed {status["phase"]}')


def open_session(club):
    status = club.sessions.create({'left_id': club.gold, 'right_id': club.silver})
    assert status['phase'] in {'preparing', 'travelling', 'ready'}
    thread = club.sessions.start(status['id'])
    return status['id'], thread


def test_a_session_runs_from_preparation_to_a_committed_trade(club):
    sid, thread = open_session(club)
    assert club.sessions.busy(club.gold) == sid
    assert club.sessions.for_adventure(club.gold)['session']['id'] == sid
    status = wait_for(club.sessions, sid, {'in_session'})
    assert status['controls_live'] and status['idle_seconds_left'] > 0
    with pytest.raises(ValueError, match='busy'):
        club.sessions.create({'left_id': club.gold, 'right_id': club.silver})
    club.sessions.press(sid, {'side': 'left', 'button': 'a'})
    with pytest.raises(ValueError, match='button'):
        club.sessions.press(sid, {'side': 'left', 'button': 'turbo'})
    club.sessions.finish(sid)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'done' and status['decision'] == 'COMMIT', status
    for peer in (club.peers[club.gold], club.peers[club.silver]):
        assert peer.operations() == ['prepare', 'stage', 'apply', 'release']
        assert peer.calls[0][1]['session'] is True
    assert club.sessions.busy(club.gold) is None
    assert [process.stdout.closed for process in club.processes] == [True]
    with pytest.raises(ValueError, match='already ended'):
        club.sessions.press(sid, {'side': 'left', 'button': 'a'})


def test_cancel_rolls_both_adventures_back(club):
    sid, thread = open_session(club)
    wait_for(club.sessions, sid, {'in_session'})
    club.sessions.cancel(sid)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'rolled_back' and 'cancelled' in status['reason']
    for aid in (club.gold, club.silver):
        assert 'abort' in club.peers[aid].operations() and 'stage' not in club.peers[aid].operations()


def test_five_idle_minutes_roll_both_adventures_back(club):
    club.sessions.idle_seconds = 0.5
    sid, thread = open_session(club)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'rolled_back' and 'five minutes' in status['reason']
    assert all('abort' in club.peers[aid].operations() for aid in (club.gold, club.silver))


def test_finishing_without_a_trade_rolls_back(club):
    sid, thread = open_session(club)
    wait_for(club.sessions, sid, {'in_session'})
    club.sessions.finish(sid)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'rolled_back' and 'without a trade' in status['reason']


def test_a_duplicated_party_never_stages(club):
    club.parties['parties'][1] = hexed([[PIDGEOT, ODDISH], [PIDGEOT, DODRIO]])
    sid, thread = open_session(club)
    wait_for(club.sessions, sid, {'in_session'})
    club.sessions.press(sid, {'side': 'right', 'button': 'a'})
    club.sessions.finish(sid)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'rolled_back'
    assert all('stage' not in club.peers[aid].operations() for aid in (club.gold, club.silver))


def test_a_trade_evolution_in_a_session_is_kept(club):
    haunter, gengar = mon(93, 5), mon(94, 5)
    club.parties['parties'] = [hexed([[haunter, ODDISH], [GYARADOS, DODRIO]]),
                               hexed([[GYARADOS, ODDISH], [gengar, DODRIO]])]
    sid, thread = open_session(club)
    wait_for(club.sessions, sid, {'in_session'})
    club.sessions.press(sid, {'side': 'left', 'button': 'a'})
    club.sessions.finish(sid)
    thread.join(20)
    status = club.sessions.status(sid)
    assert status['phase'] == 'done' and status['decision'] == 'COMMIT', status
    assert club.loaded == [(club.coordinator.manager.assets.game_data_dir, 'gold')]


def test_a_session_waits_for_the_exchange_before_it_to_finish(club):
    club.coordinator.execution.acquire()
    sid, thread = open_session(club)
    time.sleep(0.3)
    assert club.sessions.status(sid)['phase'] == 'preparing' and club.peers[club.gold].calls == []
    club.coordinator.execution.release()
    wait_for(club.sessions, sid, {'in_session'})
    club.sessions.cancel(sid)
    thread.join(20)


def test_a_session_that_cannot_start_rolls_back_instead_of_hanging(club):
    club.sessions.execution_wait = 0.2
    club.coordinator.execution.acquire()
    try:
        sid, thread = open_session(club)
        thread.join(5)
        status = club.sessions.status(sid)
        assert status['phase'] == 'rolling_back' and 'try again' in status['reason']
    finally:
        club.coordinator.execution.release()
    club.coordinator.next_recovery_at = 0
    club.coordinator.schedule_once()
    status = club.sessions.status(sid)
    assert status['phase'] == 'rolled_back' and 'try again' in status['reason']
    assert all(club.peers[aid].operations() == ['abort'] for aid in (club.gold, club.silver))


def test_the_worker_losing_its_parent_cancels_the_session():
    import io
    from pokesim.gen2.manual_session import read_commands
    cancelled = threading.Event()
    commands = read_commands(io.StringIO('{"side": "left", "button": "a"}\nnot json\n'), cancelled)
    assert cancelled.wait(5)
    assert commands.get(timeout=1) == {'side': 'left', 'button': 'a'} and commands.empty()


def test_other_generations_get_a_clear_reason(club):
    assert club.sessions.for_adventure(club.red)['reason'] == cable_sessions.UNSUPPORTED
    with pytest.raises(ValueError, match='Gold, Silver or Crystal'):
        club.sessions.create({'left_id': club.gold, 'right_id': club.red})
    with pytest.raises(ValueError, match='two different'):
        club.sessions.create({'left_id': club.gold, 'right_id': club.gold})


def test_partners_list_every_pair_with_the_reason_it_cannot_link(club):
    rows = {row['id']: row['reason'] for row in club.sessions.partners(club.gold)['partners']}
    assert rows == {club.silver: '', club.red: cable_sessions.CAPSULE_UNSUPPORTED}
    rows = {row['id']: row['reason'] for row in club.sessions.partners(club.red)['partners']}
    assert set(rows.values()) == {cable_sessions.CAPSULE_UNSUPPORTED}
    red = club.registry.adventure(club.red)
    assert club.sessions.pair_reason(red, {**red, 'id': 'x' * 32}) == cable_sessions.GEN1_UNSUPPORTED
    assert 'not yet supported' in cable_sessions.GEN1_UNSUPPORTED
    assert 'not yet supported' in cable_sessions.CAPSULE_UNSUPPORTED
    club.registry.update(club.silver, state='stopped', desired_state='stopped')
    rows = {row['id']: row['reason'] for row in club.sessions.partners(club.gold)['partners']}
    assert rows[club.silver].startswith('Silver: ')


def test_the_partners_route_answers_before_the_session_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pokesim.app.manager import Manager, create_app
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('gold', 'sha-gold', 'gold')
    manager.registry.add_rom('red', 'sha-red', 'red')
    one = manager.registry.create('One', 'gold', {}, identifier())
    red = manager.registry.create('Red', 'red', {}, identifier())
    with TestClient(create_app(manager)) as client:
        response = client.get(f'/api/v1/interactions/cable-sessions/partners?adventure_id={one["id"]}')
        assert response.status_code == 200
        assert response.json()['partners'] == [{'id': red['id'], 'name': 'Red', 'version': 'red',
                                                'reason': cable_sessions.CAPSULE_UNSUPPORTED}]
    manager.close()


def test_view_only_links_cannot_drive_a_session(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pokesim.app.manager import Manager, create_app
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    manager.registry.add_rom('gold', 'sha-gold', 'gold')
    games = [manager.registry.create(name, 'gold', {}, identifier()) for name in ('One', 'Two')]
    on_loop = []

    def viewer_only(aid):
        # The check reads the registry, so it must run off the library's event loop.
        on_loop.append(running_loop())
        return aid == games[1]['id']
    monkeypatch.setattr(manager.offers, 'viewer_only', viewer_only)
    with TestClient(create_app(manager)) as client:
        client.headers['X-PokeSim-CSRF'] = client.get('/api/v1/session').json()['csrf_token']
        response = client.post('/api/v1/interactions/cable-sessions',
                               json={'left_id': games[0]['id'], 'right_id': games[1]['id']})
        assert response.status_code == 403
        response = client.post(f'/view/{games[0]["id"]}/api/v1/interactions/cable-sessions', json={})
        assert response.status_code in {403, 404}
    assert on_loop and not any(on_loop)
    manager.close()


def running_loop():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_pacing_starts_when_the_owner_takes_the_controllers(tmp_path):
    """Frames spent walking into the club must not stall the owner's first seconds."""
    import queue

    from pokesim.gen2.manual_session import Session
    plan = SimpleNamespace(speed=1, timeout_seconds=60)
    session = Session(plan, tmp_path / 'out')
    session.sides = [SimpleNamespace(tick=lambda: True, release_buttons=lambda: None)] * 2
    session.preview = lambda: None
    session.frames = 6000    # About 100 seconds of scripted frames before the session starts.
    commands = queue.Queue()
    commands.put({'finish': True})
    started = time.monotonic()
    session.run(commands)
    for _ in range(6):
        session.tick()
    assert time.monotonic() - started < 2
