import hashlib
import json
import os
import threading

import pytest

from pokesim.checkpoints import (GZIP_MAGIC, CheckpointStore, compress_event_states, compress_state, open_state,
                                 read_manifest)

# A save state is mostly zeroed RAM, so a short pattern in a long run of zeros stands in for one.
RAW = b'\x01\x02\x03' + bytes(200_000)
MEMORY = {'policy_state': {}, 'run_memory': {}, 'generation': 2}


@pytest.fixture
def checkpoints(tmp_path):
    return CheckpointStore(tmp_path / 'states')


def test_failed_manifest_write_keeps_previous_checkpoint(checkpoints, monkeypatch):
    metadata = {'policy_state': {}, 'run_memory': {}}
    previous = checkpoints.write_checkpoint(b'previous', metadata)
    atomic_write = checkpoints.atomic_write

    def fail_manifest(path, data):
        if path.suffix == '.json':
            raise OSError('disk full')
        atomic_write(path, data)

    monkeypatch.setattr(checkpoints, 'atomic_write', fail_manifest)
    with pytest.raises(OSError, match='disk full'):
        checkpoints.write_checkpoint(b'new', metadata)
    assert checkpoints.autosaves() == [previous]
    assert set(checkpoints.states.iterdir()) == {previous, previous.with_suffix('.json')}
    assert checkpoints.checkpoint_metadata(previous)['policy_state'] == {}


def test_unserializable_metadata_does_not_publish_state(checkpoints):
    with pytest.raises(TypeError):
        checkpoints.write_checkpoint(b'new', {'policy_state': object()})
    assert list(checkpoints.states.iterdir()) == []


@pytest.mark.parametrize('metadata', [None, [], 'invalid', 1, {'format': 2}])
def test_invalid_manifest_shape_is_rejected(checkpoints, metadata):
    path = checkpoints.autosave_path()
    path.write_bytes(b'state')
    path.with_suffix('.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='format'):
        checkpoints.checkpoint_metadata(path)


def test_state_lookup_rejects_symlinks_outside_state_directory(checkpoints, tmp_path):
    outside = tmp_path / 'outside.state'
    outside.write_bytes(b'private')
    (checkpoints.states / 'linked.state').symlink_to(outside)
    assert checkpoints.state_path('linked.state') is None
    local = checkpoints.states / 'local.state'
    local.write_bytes(b'local')
    assert checkpoints.state_path('local.state') == local


def test_state_lookup_rejects_broken_paths(checkpoints):
    (checkpoints.states / 'loop.state').symlink_to('loop.state')
    for name in ['loop.state', 'missing.state', '../outside.state', 'bad\x00.state']:
        assert checkpoints.state_path(name) is None


def test_compressed_checkpoint_verifies_and_loads(checkpoints):
    path = checkpoints.write_checkpoint(RAW, MEMORY, name='event-7.state', compress=True)
    assert path.read_bytes()[:2] == GZIP_MAGIC
    assert path.stat().st_size < 2_000
    assert checkpoints.checkpoint_metadata(path)['generation'] == 2
    with open_state(path) as source:
        assert source.read() == RAW


def test_event_states_written_uncompressed_are_compressed_in_place(tmp_path):
    adventures = tmp_path / 'adventures'
    checkpoints = CheckpointStore(adventures / 'a' / 'states')
    old = checkpoints.write_checkpoint(RAW, MEMORY, name='event-1.state')
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    autosave = checkpoints.write_checkpoint(RAW, MEMORY)
    new = checkpoints.write_checkpoint(RAW, MEMORY, name='event-2.state', compress=True)
    untouched = new.read_bytes()

    saved = compress_event_states(adventures, threading.Lock())

    assert saved > 190_000
    assert old.read_bytes() == compress_state(RAW)
    assert old.stat().st_mtime_ns == 1_000_000_000
    assert checkpoints.checkpoint_metadata(old)['generation'] == 2
    with open_state(old) as source:
        assert source.read() == RAW
    assert autosave.read_bytes() == RAW
    assert new.read_bytes() == untouched
    assert compress_event_states(adventures, threading.Lock()) == 0
    assert not list(checkpoints.states.glob('.pending-*'))


def test_interrupted_compression_repairs_the_manifest(tmp_path):
    checkpoints = CheckpointStore(tmp_path / 'a' / 'states')
    path = checkpoints.write_checkpoint(RAW, MEMORY, name='event-3.state')
    # The save was replaced but the run stopped before its manifest was rewritten.
    path.write_bytes(compress_state(RAW))
    assert json.loads(path.with_suffix('.json').read_text())['sha256'] == hashlib.sha256(RAW).hexdigest()

    compress_event_states(tmp_path, threading.Lock())

    assert checkpoints.checkpoint_metadata(path)['generation'] == 2


def test_compression_stops_when_asked(tmp_path):
    checkpoints = CheckpointStore(tmp_path / 'a' / 'states')
    path = checkpoints.write_checkpoint(RAW, MEMORY, name='event-4.state')
    assert compress_event_states(tmp_path, threading.Lock(), stop=lambda: True) == 0
    assert path.read_bytes() == RAW


# A sidecar is mostly the policy state, which repeats itself enough for gzip to keep about a third.
POLICY = {'policy_state': {'plan': [{'goal': 'collect', 'map': n % 7} for n in range(400)]}, 'run_memory': {}, 'generation': 2}


def test_journal_sidecars_are_written_compressed_and_still_read(checkpoints):
    path = checkpoints.write_checkpoint(RAW, POLICY, name='event-8.state', compress=True)
    sidecar = path.with_suffix('.json')
    assert sidecar.read_bytes()[:2] == GZIP_MAGIC
    assert sidecar.stat().st_size < len(json.dumps(POLICY)) // 3
    assert checkpoints.checkpoint_metadata(path)['policy_state'] == POLICY['policy_state']
    assert read_manifest(sidecar)['generation'] == 2
    autosave = checkpoints.write_checkpoint(RAW, POLICY)
    assert json.loads(autosave.with_suffix('.json').read_text())['generation'] == 2, 'autosave sidecars stay plain'


def test_plain_sidecars_of_compressed_saves_are_compressed_in_place(tmp_path):
    checkpoints = CheckpointStore(tmp_path / 'a' / 'states')
    path = checkpoints.write_checkpoint(RAW, POLICY, name='event-9.state', compress=True)
    plain = json.dumps(read_manifest(path.with_suffix('.json'))).encode()
    path.with_suffix('.json').write_bytes(plain)

    assert compress_event_states(tmp_path, threading.Lock()) > len(plain) // 2

    assert path.with_suffix('.json').read_bytes()[:2] == GZIP_MAGIC
    assert checkpoints.checkpoint_metadata(path)['policy_state'] == POLICY['policy_state']
    assert compress_event_states(tmp_path, threading.Lock()) == 0
