from types import SimpleNamespace

import pytest

from pokecore.gen1_cable import CableEndpoint, CableError
from pokecore.compatibility import compare_result, run_suite


class Memory:
    def __init__(self):
        self.data = bytearray(65536)

    def __getitem__(self, key):
        return self.data[key[1] if isinstance(key, tuple) else key]

    def __setitem__(self, key, value):
        self.data[key[1] if isinstance(key, tuple) else key] = value


def endpoint(value):
    memory = Memory()
    memory[0xc100] = value
    memory[0xc200:0xc202] = b'\x00\x01'
    pb = SimpleNamespace(memory=memory, register_file=SimpleNamespace(PC=0x200, SP=0xc200),
                         tick=lambda *args: True, button_release=lambda button: None)
    symbols = {'hSerialSendData': (0, 0xc100), 'hSerialReceiveData': (0, 0xc101),
               'hSerialReceivedNewData': (0, 0xc102)}
    return CableEndpoint(pb, symbols, max_queue=1)


def test_trading_transport_exchanges_once_and_restores_parked_cpu():
    left, right = endpoint(11), endpoint(22)
    left.peer, right.peer = right, left
    left.exchange('byte', 'hSerialSendData')
    assert left.parked == (0x200, 0xc200, 0)
    assert not left.tick()
    right.exchange('byte', 'hSerialSendData')
    assert right.pb.memory[0xc101] == 11
    assert left.tick()
    assert left.pb.register_file.PC == 0x200
    left.exchange('byte', 'hSerialSendData')
    assert left.pb.memory[0xc101] == 22
    assert left.counts['byte_exchanged'] == right.counts['byte_exchanged'] == 1
    assert not left.inbox['byte'] and not right.inbox['byte']
    left.detach()
    right.detach()


def test_trading_overflow_and_pending_checkpoint_boundary_are_rejected():
    left, right = endpoint(11), endpoint(22)
    left.peer, right.peer = right, left
    right.inbox['byte'].append(99)
    with pytest.raises(CableError, match='overflow'):
        left.exchange('byte', 'hSerialSendData')
    right.inbox['byte'].clear()
    left.exchange('byte', 'hSerialSendData')
    with pytest.raises(CableError, match='pending'):
        left.detach()


def test_baseline_mismatch_and_performance_thresholds_are_not_silent():
    base = {'manifest_sha256': 'a', 'cases': [{'id': 'demo', 'status': 'passed',
             'fingerprint': [{'offset': 1, 'hardware': 'a'}], 'seconds': 1, 'peak_rss_mib': 10}]}
    changed = {'manifest_sha256': 'a', 'cases': [{'id': 'demo', 'status': 'passed',
                'fingerprint': [{'offset': 1, 'hardware': 'b'}], 'seconds': 2, 'peak_rss_mib': 20}]}
    failures = compare_result(changed, base, max_slowdown=10, max_memory_growth=10)
    assert any('checkpoint 1' in x for x in failures)
    assert any('slowdown' in x for x in failures)
    assert any('memory growth' in x for x in failures)
    changed['manifest_sha256'] = 'b'
    assert compare_result(changed, base) == ['Manifest differs from the baseline']


def test_missing_private_fixtures_cannot_satisfy_release_coverage(tmp_path):
    import json
    manifest = tmp_path / 'suite.json'
    manifest.write_text(json.dumps({'format': 1, 'cases': [
        {'id': 'missing', 'kind': 'trace', 'scope': 'private', 'categories': ['trading'],
         'rom': 'missing.gb', 'steps': [[[], 1]]}]}))
    result = run_suite(manifest, repeats=1, require_private=True)
    assert result['status'] == 'incomplete'
    assert 'trading' in result['missing_categories']
    assert result['cases'][0]['status'] == 'missing'
