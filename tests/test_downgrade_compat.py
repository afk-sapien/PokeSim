"""Gen 1 checkpoints written by 0.5 must stay loadable by 0.4.x, so a rollback keeps every adventure.

The three validators below reproduce what tag v0.4.19 checks before it loads a checkpoint
(pokesim/emulator.py, pokesim/headless.py and pokesim/trade/pair.py): the manifest must name
the legacy PyBoy version. 0.4.x has no notion of the Rust backend, so an untagged checkpoint is refused.
"""
import hashlib

import pytest

from pokesim.checkpoints import CheckpointStore
from pokesim_core.emulator_state import checkpoint_metadata, retag_checkpoint

INSTALLED_PYBOY = '2.7.0'  # what version('pyboy') returned in the 0.4.x images


def legacy_emulator_resume(metadata, rom_sha1, policy):
    """pokesim/emulator.py at v0.4.19, restore of a checkpoint."""
    if metadata.get('rom_sha1') != rom_sha1:
        raise ValueError('Checkpoint was created with a different ROM')
    if metadata.get('pyboy_version') != INSTALLED_PYBOY:
        raise ValueError('Checkpoint requires a different PyBoy version')
    if metadata.get('policy') != policy:
        raise ValueError('Checkpoint requires a different policy')


def legacy_headless_load(metadata, rom_sha1):
    """pokesim/headless.py at v0.4.19."""
    if not metadata:
        raise ValueError('A checkpoint manifest is required for a faithful replay')
    if metadata['rom_sha1'] != rom_sha1 or metadata['pyboy_version'] != INSTALLED_PYBOY:
        raise ValueError('ROM or emulator version does not match the checkpoint')


def legacy_pair_inspect(metadata):
    """pokesim/trade/pair.py at v0.4.19."""
    if metadata is None:
        raise ValueError('A verified checkpoint manifest is required')
    if metadata.get('pyboy_version') != INSTALLED_PYBOY or metadata.get('policy') != 'strategic':
        raise ValueError('Checkpoint runtime is incompatible with the trade worker')


def manifest():
    return {'app_version': '0.5.0', **checkpoint_metadata(), 'rom_sha1': 'abc', 'policy': 'strategic',
            'policy_state': {}, 'run_memory': {}, 'frame': 1}


def accepted_by_legacy(metadata):
    legacy_emulator_resume(metadata, 'abc', 'strategic')
    legacy_headless_load(metadata, 'abc')
    legacy_pair_inspect(metadata)


def test_gen1_manifest_from_the_rust_backend_loads_with_the_0419_logic(tmp_path):
    store = CheckpointStore(tmp_path)
    path = store.write_checkpoint(b'state', manifest())
    written = store.checkpoint_metadata(path)
    assert written['pyboy_version'] == '2.7.0'
    assert written['emulator']['backend'] == 'pyboy-rs'
    accepted_by_legacy(written)
    assert written['sha256'] == hashlib.sha256(b'state').hexdigest()


def test_checkpoint_retagged_after_a_trade_keeps_the_legacy_tag():
    traded = retag_checkpoint(manifest())
    assert traded['pyboy_version'] == '2.7.0'
    accepted_by_legacy(traded)


def test_checkpoint_imported_from_pyboy_keeps_the_legacy_tag():
    legacy = {'rom_sha1': 'abc', 'policy': 'strategic', 'pyboy_version': '2.7.0'}
    accepted_by_legacy(retag_checkpoint(legacy))


def test_locked_clock_checkpoint_is_refused_by_the_legacy_logic():
    """A locked cartridge clock cannot be reproduced by PyBoy 2.7.0, so 0.4.x must refuse it."""
    locked = {**checkpoint_metadata(rtc_clock={'locked': True}), 'rom_sha1': 'abc', 'policy': 'strategic'}
    assert 'pyboy_version' not in locked
    with pytest.raises((ValueError, KeyError)):
        legacy_headless_load(locked, 'abc')
    with pytest.raises(ValueError):
        legacy_pair_inspect(locked)
