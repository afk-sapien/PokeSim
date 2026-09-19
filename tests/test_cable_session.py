"""Unit and opt-in cartridge integration checks for the isolated cable executor."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.interactions.cable import CableError, CableSide, sha256
from pokesim.interactions.cable_driver import CableDriver
from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan, run_session
from pokesim.interactions.verification import individual_key, party


def sample_plan():
    return CableSessionPlan('trade-1', 'attempt-1',
        CableParticipant('adventure-a', 'red.gbc', 'a.state'),
        CableParticipant('adventure-b', 'blue.gbc', 'b.state'), speed=0)


@pytest.mark.parametrize('change', [
    {'attempt_id': '../escape'}, {'attempt_id': ''}, {'max_steps': 0}, {'max_steps': True},
    {'timeout_seconds': float('nan')}, {'timeout_seconds': -1}, {'speed': float('inf')},
    {'speed': -1},
])
def test_plan_rejects_invalid_boundaries(change):
    with pytest.raises(CableError):
        replace(sample_plan(), **change).validate()


def test_plan_requires_distinct_owners():
    plan = sample_plan()
    with pytest.raises(CableError, match='distinct'):
        replace(plan, right=replace(plan.right, adventure_id=plan.left.adventure_id)).validate()


def test_plan_roundtrip():
    from dataclasses import asdict
    assert CableSessionPlan.from_dict(json.loads(json.dumps(asdict(sample_plan())))) == sample_plan()


def test_outputs_never_overwrite(tmp_path):
    out = tmp_path / 'occupied'
    out.mkdir()
    (out / 'manifest.json').write_text('previous')
    with pytest.raises(FileExistsError):
        run_session(sample_plan(), out)
    assert (out / 'manifest.json').read_text() == 'previous'


def test_identity_matches_existing_preference_contract():
    raw = bytearray(44)
    raw[12:14] = bytes([12, 34])
    raw[27:29] = bytes([0xab, 0xcd])
    row = {'struct': bytes(raw), 'nickname': b'TEST', 'trainer': b'OWNER'}
    assert individual_key(row) == sha256(json.dumps([0x0c22, [5, 10, 11, 12, 13]]).encode())[:24]
    raw[0] = 149
    raw[33] = 50
    assert individual_key({**row, 'struct': bytes(raw)}) == individual_key(row)


def test_transport_refuses_queue_overflow():
    from collections import Counter, deque
    side = object.__new__(CableSide)
    side.peer = SimpleNamespace(inbox={'byte': deque([1])})
    side.counts = Counter()
    side.pending = None
    side.max_queue = 1
    with pytest.raises(CableError, match='overflow'):
        side.exchange('byte', 'hSerialSendData')


def test_transport_deadlock_is_bounded():
    sides = [SimpleNamespace(tick=lambda: False), SimpleNamespace(tick=lambda: False)]
    with pytest.raises(CableError, match='deadlock'):
        CableDriver(sides, sample_plan()).tick(1)


@pytest.fixture
def cartridge_plan():
    root = os.environ.get('POKESIM_CABLE_FIXTURES')
    roms = os.environ.get('POKESIM_CABLE_ROMS')
    if not root or not roms:
        pytest.skip('Set POKESIM_CABLE_FIXTURES and POKESIM_CABLE_ROMS for private ROM integration')
    def participant(name, version):
        return CableParticipant(name, str(Path(roms) / f'poke{version}.gbc'),
            str(Path(root) / f'{version}.state'), str(Path(root) / f'{version}.sav'))
    return CableSessionPlan('cartridge-test', 'attempt-1', participant('a', 'red'),
                            participant('b', 'blue'), speed=0, timeout_seconds=60)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('pairing', ['red-blue', 'red-red', 'blue-blue'])
def test_real_trade_pairs_and_roles(cartridge_plan, tmp_path, reverse, pairing):
    plan = replace(cartridge_plan, external_left=reverse)
    if pairing == 'red-red':
        plan = replace(plan, right=replace(plan.left, adventure_id='b'))
    if pairing == 'blue-blue':
        plan = replace(plan, left=replace(plan.right, adventure_id='a'))
    manifest = run_session(plan, tmp_path / 'results')
    assert manifest['status'] == 'verified'
    assert manifest['return_method'] == 'cartridge_soft_reset_continue'
    for entry in manifest['participants'].values():
        assert sha256(Path(entry['state_path']).read_bytes()) == entry['checkpoint_sha256']
        evidence = entry['evidence']
        assert evidence['cartridge_restart_passed'] and evidence['checkpoint_reload_passed']
        assert evidence['cartridge_movement_passed'] and evidence['checkpoint_movement_passed']
        assert evidence['transport']['TradeCenter_Trade'] == 1
        assert evidence['transport']['ReturnToCableClubRoom'] == 1
        assert evidence['safe_return_map'] == 89


@pytest.mark.parametrize('slots', [(0, 5), (1, 4), (2, 3), (3, 2), (4, 1), (5, 0)])
def test_negotiated_party_slots(cartridge_plan, tmp_path, slots):
    plan = replace(cartridge_plan, left=replace(cartridge_plan.left, party_slot=slots[0]),
                   right=replace(cartridge_plan.right, party_slot=slots[1]))
    result = run_session(plan, tmp_path / 'results')
    assert all(row['evidence']['party_conserved'] for row in result['participants'].values())


def test_missing_cartridge_stream_uses_checkpoint_ram(cartridge_plan, tmp_path):
    plan = replace(cartridge_plan, left=replace(cartridge_plan.left, cartridge_save_path=None),
                   right=replace(cartridge_plan.right, cartridge_save_path=None))
    result = run_session(plan, tmp_path / 'results')
    assert all(row['evidence']['cartridge_restart_passed'] for row in result['participants'].values())


def test_no_cable_does_not_trade(cartridge_plan):
    sides = [CableSide(cartridge_plan.left), CableSide(cartridge_plan.right)]
    try:
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        before = [party(side.pb, side.sym) for side in sides]
        for i, side in enumerate(sides):
            side.attach(i + 1, enabled=False)
        driver = CableDriver(sides, replace(cartridge_plan, max_steps=200))
        driver.enter()
        with pytest.raises(CableError):
            driver.exchange()
        for side, original in zip(sides, before):
            assert not side.counts['TradeCenter_Trade']
            assert party(side.pb, side.sym) == original
    finally:
        for side in sides:
            side.stop()


def test_cancel_during_trade_leaves_no_manifest(cartridge_plan, tmp_path):
    sources = [Path(spec.checkpoint_path).read_bytes() for spec in (cartridge_plan.left, cartridge_plan.right)]
    def cancel(update):
        if update['phase'] == 'trading':
            raise CableError('Cancelled')
    with pytest.raises(CableError, match='Cancelled'):
        run_session(cartridge_plan, tmp_path / 'results', cancel)
    assert not (tmp_path / 'results' / 'manifest.json').exists()
    assert (tmp_path / 'results' / 'failure.json').exists()
    assert sources == [Path(spec.checkpoint_path).read_bytes() for spec in (cartridge_plan.left, cartridge_plan.right)]


def test_reject_stale_individual(cartridge_plan, tmp_path):
    plan = replace(cartridge_plan, left=replace(cartridge_plan.left, selected_key='stale'))
    with pytest.raises(CableError, match='individual'):
        run_session(plan, tmp_path / 'results')
    assert not (tmp_path / 'results' / 'manifest.json').exists()


def test_reject_stale_checkpoint(cartridge_plan, tmp_path):
    plan = replace(cartridge_plan, left=replace(cartridge_plan.left, checkpoint_sha256='0' * 64))
    with pytest.raises(CableError, match='digest'):
        run_session(plan, tmp_path / 'results')


def test_asymmetric_emulator_stepping(cartridge_plan, tmp_path, monkeypatch):
    tick = CableSide.tick
    def uneven_tick(side):
        moved = tick(side)
        if side.spec.adventure_id == 'b':
            moved = tick(side) or moved
        return moved
    monkeypatch.setattr(CableSide, 'tick', uneven_tick)
    result = run_session(cartridge_plan, tmp_path / 'results')
    assert result['status'] == 'verified'


def test_disconnect_stops_attempt(cartridge_plan, tmp_path, monkeypatch):
    tick = CableSide.tick
    def disconnect(side):
        if side.spec.adventure_id == 'b' and side.counts['byte_exchanged'] > 30:
            return False
        return tick(side)
    monkeypatch.setattr(CableSide, 'tick', disconnect)
    with pytest.raises(CableError, match='deadlock'):
        run_session(cartridge_plan, tmp_path / 'results')
    assert not (tmp_path / 'results' / 'manifest.json').exists()


def test_success_callback_failure_cannot_publish_manifest(cartridge_plan, tmp_path):
    def fail_progress(update):
        if update['phase'] == 'verified':
            raise CableError('Progress consumer stopped')
    with pytest.raises(CableError, match='Progress consumer'):
        run_session(cartridge_plan, tmp_path / 'results', fail_progress)
    assert not (tmp_path / 'results' / 'manifest.json').exists()


def test_selected_keys_bind_real_sources(cartridge_plan, tmp_path):
    specs = []
    for spec in (cartridge_plan.left, cartridge_plan.right):
        side = CableSide(spec)
        try:
            selected = party(side.pb, side.sym)[spec.party_slot]
            specs.append(replace(spec, selected_key=individual_key(selected)))
        finally:
            side.stop()
    result = run_session(replace(cartridge_plan, left=specs[0], right=specs[1]), tmp_path / 'results')
    assert result['participants']['a']['selected_key'] == specs[0].selected_key
    assert result['participants']['b']['selected_key'] == specs[1].selected_key


def test_parent_disconnect_cancels_child(cartridge_plan, tmp_path):
    from dataclasses import asdict
    import subprocess
    import sys
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps(asdict(replace(cartridge_plan, speed=1))))
    child = subprocess.Popen([sys.executable, '-m', 'pokesim.interactions.link_worker',
        '--plan', str(plan), '--watch-parent', '--out', str(tmp_path / 'results')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        first = json.loads(child.stdout.readline())
        assert first['phase'] == 'preparing'
        child.stdin.close()
        child.wait(timeout=10)
        assert child.returncode != 0
        assert not (tmp_path / 'results' / 'manifest.json').exists()
        failure = json.loads((tmp_path / 'results' / 'failure.json').read_text())
        assert 'cancelled' in failure['error']
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
