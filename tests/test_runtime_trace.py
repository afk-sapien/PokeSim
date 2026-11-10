"""An adventure's trace folder: segments per autosave, pruning, and failures that never stop a game."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('pyboy_rs')
from pokecore import trace as core  # noqa: E402
from pokecore.emulator import Emulator, demo_rom  # noqa: E402

from pokesim import config  # noqa: E402
from pokesim.runtime import trace  # noqa: E402
from pokesim.runtime.manifest import checkpoint_manifest  # noqa: E402


@pytest.fixture
def game():
    machine = Emulator(demo_rom(), sound_emulated=False)
    yield machine
    machine.stop(save=False)


@pytest.fixture
def tracer(tmp_path, game):
    tracer = trace.Tracer(tmp_path / 'trace', 1, {'adventure': 'seed'})
    tracer.attach(game)
    yield tracer
    tracer.close()


def records(tracer, name):
    tracer.close()
    return core.Trace.read(tracer.folder / name / trace.SEGMENT)


def test_a_segment_links_its_autosave_as_the_start_state(tmp_path, tracer, game):
    state = game.save()
    kept = tmp_path / 'auto-v1-5.state'
    kept.write_bytes(state)
    assert tracer.begin('auto-v1-5', state, {'frame': 0}, kept=kept)
    start = tracer.folder / 'auto-v1-5' / f'{core.digest(state)}.state'
    assert os.path.samefile(start, kept)
    read = records(tracer, 'auto-v1-5')
    assert read.header['manifest'] == {'frame': 0} and read.header['seeds'] == {'adventure': 'seed'}
    assert read.state(read.header['state_sha256']) == state


def test_a_segment_with_no_autosave_keeps_its_own_start_state(tracer, game):
    assert tracer.ensure(lambda: {'frame': 0})
    assert tracer.name.startswith('start-')
    read = records(tracer, tracer.name)
    assert read.state(read.header['state_sha256']) == game.save()


def test_policy_steps_and_owner_commands_go_into_the_segment(tracer, game):
    tracer.ensure(dict)
    tracer.decide(SimpleNamespace(goal=SimpleNamespace(key='heal')), SimpleNamespace(map=1, x=2, y=3))
    tracer.decide(SimpleNamespace(goal=object()), SimpleNamespace(map=4, x=5, y=6))
    tracer.input('command', trace.command('speed', 2))
    found = records(tracer, tracer.name).records
    assert [(record['goal'], record['map']) for record in found if record['kind'] == 'decide'] == [('heal', 1),
                                                                                                    ('object', 4)]
    assert [record['payload'] for record in found if record['kind'] == 'input'] == [{'command': 'speed', 'arg': 2}]


def test_command_payloads_hold_only_plain_values():
    def call():
        pass
    assert trace.command('runtime_call', (call, object())) == {'command': 'runtime_call', 'call': call.__qualname__}
    assert trace.command('trade', ('peer', {'id': 1}, object())) == {'command': 'trade', 'args': ['peer', {'id': 1}]}
    assert trace.command('speed', 2) == {'command': 'speed', 'arg': 2}
    assert trace.command('owner', {'key': object()}) == {'command': 'owner', 'arg': {'key': 'object'}}


def test_prune_follows_the_autosaves_and_keeps_the_open_segment(tracer, game):
    for name in ('auto-v1-1', 'auto-v1-2', 'auto-v1-3'):
        assert tracer.begin(name, game.save(), {})
    tracer.prune([])
    assert [path.name for path in trace.segments(tracer.folder)] == ['auto-v1-1', 'auto-v1-2', 'auto-v1-3']
    tracer.prune([Path('auto-v1-2.state'), Path('auto-v1-3.state')])
    assert [path.name for path in trace.segments(tracer.folder)] == ['auto-v1-2', 'auto-v1-3']
    # The segment still being written stays, even past the oldest autosave.
    tracer.prune([Path('auto-v1-9.state')])
    assert [path.name for path in trace.segments(tracer.folder)] == ['auto-v1-3']


def test_a_segment_that_cannot_begin_stops_recording_and_waits_to_try_again(tmp_path, tracer, game, monkeypatch):
    folder = tracer.folder
    assert tracer.begin('auto-v1-1', game.save(), {})
    blocked = tmp_path / 'blocked'
    blocked.write_text('')
    tracer.folder = blocked
    assert not tracer.begin('auto-v1-2', game.save(), {})
    # Nothing more goes to the segment before the failure.
    assert not tracer.recording
    asked = []
    assert not tracer.ensure(lambda: asked.append(1) or {})
    assert not asked
    tracer.folder = folder
    monkeypatch.setattr(trace, 'RETRY_SECONDS', 0)
    assert tracer.ensure(dict) and tracer.recording


def test_a_disk_error_ends_the_segment_and_the_game_plays_on(tracer, monkeypatch):
    tracer.ensure(dict)
    sink = tracer.recorder.sink

    def full(self, record):
        raise OSError('No space left on device')
    monkeypatch.setattr(core.Segment, 'record', full)
    tracer.input('command', {'command': 'speed'})
    assert sink.broken
    tracer.input('command', {'command': 'speed'})
    assert sink.keep_state(b'state') == core.digest(b'state')
    tracer.close()


def test_a_tracer_needs_the_setting_and_a_states_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'SEED', None)
    store = SimpleNamespace(states=tmp_path, get=lambda key: None)
    monkeypatch.setattr(config, 'TRACE', False)
    assert trace.for_store(store, 1) is None
    monkeypatch.setattr(config, 'TRACE', True)
    assert trace.for_store(SimpleNamespace(), 1) is None
    tracer = trace.for_store(store, 2)
    assert tracer.folder == tmp_path / trace.FOLDER and tracer.generation == 2
    assert tracer.seeds() == {'adventure': None, 'fair_dvs': None, 'league_ledger': None}
    assert trace.for_run(None, 1, None, 7) is None


def test_a_host_with_no_tracer_ignores_notes_and_reasons():
    host = SimpleNamespace()
    trace.note(host, 'trade_demand', {'requests': {}})
    with trace.reason(host, 'reload'):
        pass


def test_a_gen1_manifest_carries_the_fields_a_replay_reads():
    policy = SimpleNamespace(state_dict=lambda: {'steps': 1})
    store = {'trade_barrier': 'trade-1', 'custom-reward-barrier-v1': 'reward-1'}
    manifest = checkpoint_manifest(None, policy, rom_sha1='abc', frame=5, store=store,
                                   play_clock=SimpleNamespace(state_dict=lambda: {'frames': 5}))
    assert manifest['rom_sha1'] == 'abc' and manifest['frame'] == 5 and manifest['policy'] == config.POLICY
    assert manifest['policy_state'] == {'steps': 1} and manifest['run_memory'] == {}
    assert manifest['play_clock'] == {'frames': 5}
    assert (manifest['trade_id'], manifest['reward_id']) == ('trade-1', 'reward-1')
    assert 'emulator' in manifest and 'generation' not in manifest and 'legendary_recovery' not in manifest
