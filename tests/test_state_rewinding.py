"""Slice S4 of docs/design/adventure-state-store.md: the rewinding state lives once, in each checkpoint's manifest.

Boot and reload read the policy state, the run memory and the Gen II history from the manifest. The
autosaves write no kv copy of them. Two old cases keep reading the last kv copy: a Gen I save with no
manifest takes the policy copy, and a Gen II boot takes the history copy for a manifest from before it
carried one. The playtime hours Gen I has announced are their own key, which a reload keeps.
"""
import ast
import io
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest

from pokecore.emulator_state import checkpoint_metadata
from pokesim.state import domains, manifests
from pokesim.store import Store

PACKAGE = Path(__file__).resolve().parents[1] / 'pokesim'
COPIES = {'policy_state', 'run_memory', 'gen2-history'}
LOCK = {'base': 1_700_000_000.0, 'offset': 0.0, 'frames': 12, 'follow_frames': True}


def on_a_store(func):
    """Whether a call goes to ``self.store`` or a local ``store``, not to a manifest's dict."""
    owner = func.value
    return (isinstance(owner, ast.Attribute) and owner.attr == 'store') or (isinstance(owner, ast.Name) and owner.id == 'store')


def store_calls(name):
    """Each ``get`` and ``set`` of a kv copy in a module, with the function it is in."""
    tree = ast.parse((PACKAGE / name).read_text(encoding='utf-8'))
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'set')
                    and on_a_store(node.func) and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in COPIES):
                found.append((function.name, node.func.attr, node.args[0].value))
    return found


@pytest.mark.parametrize('name, legacy', [
    ('emulator.py', [('_load_state_file', 'get', 'policy_state')]),
    ('gen2/emulator.py', [('_load_state_file', 'get', 'gen2-history')]),
])
def test_boot_and_reload_read_the_manifest_and_nothing_writes_a_kv_copy(name, legacy):
    assert store_calls(name) == legacy


def test_only_the_announced_playtime_hours_outlive_a_reload_in_kv():
    assert domains.KEYS['playtime-milestones-v1'].life == domains.RESETS_ON_RESTART
    assert domains.KEYS['playtime-milestones-v1'].generations == domains.GEN1
    assert 'run_memory' not in domains.KEYS


def gen1(tmp_path, monkeypatch):
    from pokesim.audio import AudioFeed
    from pokesim.emulator import Emulator
    from pokesim.events import RunMemory
    from pokesim.play_clock import PlayClock
    from test_events import snap
    monkeypatch.setattr('pokesim.emulator.read_snapshot', lambda memory, frame: snap())
    emu = Emulator.__new__(Emulator)
    emu.store, emu.mem, emu.pb, emu.policy = Store(tmp_path), RunMemory(), Mock(), Mock()
    emu.rom_sha1, emu.input_epoch, emu.frame, emu.executed_frames = 'rom', 0, 0, 0
    emu.audio, emu._audio_enabled, emu.play_clock = AudioFeed(), False, PlayClock()
    return emu


def test_a_gen1_reload_takes_the_policy_from_the_manifest_and_not_the_kv_copy(tmp_path, monkeypatch):
    from pokesim import config
    emu = gen1(tmp_path, monkeypatch)
    with closing(emu.store):
        emu.store.set('policy_state', {'goal': 'stale copy'})
        path = emu.store.write_checkpoint(b'save', {'rom_sha1': 'rom', 'pyboy_version': '2.7.0', 'policy': config.POLICY,
                                                    'policy_state': {'goal': 'saved'}, 'run_memory': {'seen_maps': [3]}})
        emu._load_state_file(path)
        emu.policy.load_state_dict.assert_called_once_with({'goal': 'saved'})
        assert emu.mem.seen_maps == {3}
        assert emu.store.get('run_memory') is None and emu.store.get('policy_state') == {'goal': 'stale copy'}


def test_a_gen1_save_with_no_manifest_takes_the_last_kv_copy_of_the_policy(tmp_path, monkeypatch):
    emu = gen1(tmp_path, monkeypatch)
    with closing(emu.store):
        emu.store.set('policy_state', {'goal': 'last copy'})
        path = emu.store.states / 'from-before-manifests.state'
        path.write_bytes(b'save')
        assert emu.store.checkpoint_metadata(path) is None
        emu._load_state_file(path)
        emu.policy.load_state_dict.assert_called_once_with({'goal': 'last copy'})


@pytest.fixture
def gen2(tmp_path, monkeypatch):
    from pokesim.gen2 import emulator as module
    monkeypatch.setattr(module, 'read_snapshot', lambda *args: None)
    monkeypatch.setattr(module, 'open_state', lambda path: io.BytesIO(b'state'))
    emu = module.Emulator.__new__(module.Emulator)
    emu.store, emu.pb, emu.rom_sha1, emu.data = Store(tmp_path), Mock(), 'rom', None
    emu._sync_clock = Mock()
    emu.policy, emu.play_clock, emu.audio, emu._reset_watch, emu._publish_frame = Mock(), Mock(), Mock(), Mock(), Mock()
    emu.statistics = Mock(previous=None)
    emu.history, emu.history_loaded = module.new_history(), False
    emu.store.set('gen2-history', {'maps': [1, 2], 'owned': [152], 'badges': 1, 'league': 0, 'capped_wins': 3})
    with closing(emu.store):
        yield emu


def gen2_save(emu, **fields):
    metadata = {**checkpoint_metadata(rtc_clock=LOCK), 'rtc_clock': LOCK, 'generation': 2, 'rom_sha1': 'rom',
                'frame': 9, 'policy_state': {'goal': 'saved'}, 'run_memory': {}, **fields}
    return emu.store.write_checkpoint(b'state', metadata)


def test_a_gen2_boot_takes_the_history_from_the_manifest(gen2):
    gen2._load_state_file(gen2_save(gen2, gen2_history={'maps': [7], 'owned': [], 'badges': 0, 'league': 0}))
    assert gen2.history['maps'] == [7]
    gen2.policy.load_state_dict.assert_called_once_with({'goal': 'saved'})
    assert gen2.store.get('policy_state') is None


def test_a_gen2_boot_on_a_manifest_with_no_history_takes_the_last_kv_copy(gen2):
    gen2._load_state_file(gen2_save(gen2))
    # The League count past the cartridge's cap goes, as it did when the boot read the copy first.
    assert gen2.history == {'maps': [1, 2], 'owned': [152], 'badges': 1, 'league': 0}
    assert gen2.history_loaded


def test_a_gen2_rewind_to_a_manifest_with_no_history_keeps_the_current_game(gen2):
    gen2._load_state_file(gen2_save(gen2, gen2_history={'maps': [7], 'owned': [], 'badges': 0, 'league': 0}))
    gen2._load_state_file(gen2_save(gen2))
    assert gen2.history['maps'] == [7]


@pytest.mark.parametrize('generation, keys', [
    (1, {'policy_state', 'playtime-milestones-v1'}),
    (2, {'policy_state', 'gen2-history'}),
])
def test_a_restart_drops_the_last_kv_copies(tmp_path, generation, keys):
    with closing(Store(tmp_path)) as store:
        for key in keys:
            store.set(key, {'old': True})
        store.restart(generation, {})
        assert {key: store.get(key) for key in keys} == dict.fromkeys(keys)


def test_a_tool_reads_the_newest_autosave_manifest(tmp_path):
    assert manifests.newest(tmp_path) is None
    (tmp_path / 'auto-v1-5.json').write_text(json.dumps({'policy_state': {'decisions': 5}}))
    (tmp_path / 'auto-v1-40.json').write_text(json.dumps({'policy_state': {'decisions': 40}}))
    (tmp_path / 'before-load.json').write_text(json.dumps({'policy_state': {'decisions': 99}}))
    assert manifests.newest(tmp_path)['policy_state'] == {'decisions': 40}
    # A manifest cut off mid-write gives way to the one before it.
    (tmp_path / 'auto-v1-41.json').write_text('{"policy_state"')
    assert manifests.newest(tmp_path)['policy_state'] == {'decisions': 40}
