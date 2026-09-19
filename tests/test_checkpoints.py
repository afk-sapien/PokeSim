import json

import pytest

from pokesim.checkpoints import CheckpointStore


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
