"""Every stall trigger keeps a bundle, and ``python -m pokesim.replay capture`` turns one into a scenario."""
import gzip
import hashlib
import json
import os
import tomllib
from types import SimpleNamespace

import pytest

from pokesim.checkpoints import CheckpointStore, fresh_folder, write_bundle
from pokesim.emulator import Emulator
from pokesim.gen2 import standdown
from pokesim.gen2.emulator import Emulator as Gen2Emulator
from pokesim.replay import capture as scenario
from pokesim.replay.__main__ import main
from pokesim.runtime import capture, trace
from pokesim.stalls import BEFORE_STALL_CHECKPOINT, FRAMES_PER_GAME_MINUTE as MINUTE, LOOP_LIMIT, LoopGuard, StallWatch
from pokesim.store import Store

from test_loop_guard import add
from test_stall_bundles import MANIFEST, game
from test_supervision import ladder

LOOP = 'It received and released Totodile 6 times without other progress'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def kept(store):
    """The one bundle the store holds, and its report."""
    folder, = store.stalls.iterdir()
    return folder, json.loads((folder / 'report.json').read_text())


def test_a_quiet_stretch_is_captured_once_and_new_progress_starts_another():
    watch = StallWatch(game_minutes=120, real_minutes=15)
    watch.progress(100 * MINUTE, 0)
    assert not watch.capture_due(219 * MINUTE)
    assert watch.capture_due(220 * MINUTE)
    # The real-minute pacing holds back the alert, never the capture.
    assert watch.check(221 * MINUTE, 60) is None
    assert not watch.capture_due(221 * MINUTE)
    # A reload does not stop the play clock, so the stretch after it is the same one, with one capture.
    watch.check(240 * MINUTE, 120)
    assert not watch.capture_due(240 * MINUTE)
    watch.progress(300 * MINUTE, 200)
    assert watch.captured is None and watch.capture_due(420 * MINUTE)


def test_each_new_loop_is_taken_once(tmp_path):
    store = Store(tmp_path)
    try:
        guard = LoopGuard(clock=lambda: 1000.0)
        assert guard.take_trip() is None
        for _ in range(LOOP_LIMIT):
            add(store, 'obtain', 'Received Totodile from a custom PokeSim gift')
            add(store, 'release', 'Said goodbye to a spare Totodile')
        reason = guard.looping(store)
        assert reason and guard.take_trip() == reason and guard.take_trip() is None
        # The same loop seen again is not a new one.
        guard.looping(store)
        assert guard.take_trip() is None
    finally:
        store.close()


def test_a_second_bundle_in_the_same_second_gets_its_own_folder(tmp_path):
    first = tmp_path / 'stall-1'
    assert fresh_folder(first) == first
    first.mkdir()
    assert fresh_folder(first).name == 'stall-1-2'
    (tmp_path / 'stall-1-2').mkdir()
    assert fresh_folder(first).name == 'stall-1-3'


def test_a_bundle_links_its_closed_trace_segments(tmp_path):
    segment = tmp_path / 'trace' / 'auto-v1-5'
    segment.mkdir(parents=True)
    (segment / trace.SEGMENT).write_bytes(b'records')
    (segment / f'{sha(b"start")}.state').write_bytes(b'start')
    before = CheckpointStore(tmp_path / 'states').write_checkpoint(b'before', MANIFEST)
    folder = write_bundle(tmp_path / 'stall', b'noticed', MANIFEST, {'kind': 'quiet'}, None, before, [segment])
    assert os.path.samefile(folder / 'trace' / 'auto-v1-5' / trace.SEGMENT, segment / trace.SEGMENT)
    assert json.loads((folder / 'report.json').read_text()) == {'kind': 'quiet', 'has_before': True,
                                                                'trace': ['auto-v1-5']}
    assert (folder / 'before.state').read_bytes() == b'before' and not (folder / 'noticed.png').exists()


@pytest.fixture
def segments(tmp_path):
    """Five closed segments, the second starting at the save kept from before a stall."""
    folder = tmp_path / 'trace'
    for stamp in range(1, 6):
        (folder / f'auto-v1-{stamp}').mkdir(parents=True)
    (folder / 'auto-v1-2' / f'{sha(b"held")}.state').write_bytes(b'held')
    held = tmp_path / BEFORE_STALL_CHECKPOINT
    held.write_bytes(b'held')
    return trace.Tracer(folder, 1), held


def names(found):
    return [path.name for path in found]


def test_pruning_holds_the_segments_from_the_save_before_a_stall(segments, monkeypatch):
    tracer, held = segments
    autosaves = [held.with_name('auto-v1-4.state'), held.with_name('auto-v1-5.state')]
    tracer.prune(autosaves, hold=held)
    assert names(trace.segments(tracer.folder)) == ['auto-v1-2', 'auto-v1-3', 'auto-v1-4', 'auto-v1-5']
    # The hold keeps at most the newest HELD_SEGMENTS.
    monkeypatch.setattr(trace, 'HELD_SEGMENTS', 1)
    tracer.prune(autosaves, hold=held)
    assert names(trace.segments(tracer.folder)) == ['auto-v1-4', 'auto-v1-5']


def test_a_bundle_takes_the_closed_segments_from_the_held_save_on(segments, monkeypatch):
    tracer, held = segments
    assert names(tracer.closed(held)) == ['auto-v1-2', 'auto-v1-3', 'auto-v1-4', 'auto-v1-5']
    assert names(tracer.closed()) == ['auto-v1-1', 'auto-v1-2', 'auto-v1-3', 'auto-v1-4', 'auto-v1-5']
    # A tracer that is not recording begins no segment of its own.
    assert names(capture._segments(tracer, b'now', {}, held)) == names(tracer.closed(held))
    assert capture._segments(None, b'now', {}, held) == []
    monkeypatch.setattr(trace, 'HELD_SEGMENTS', 2)
    assert names(tracer.closed()) == ['auto-v1-4', 'auto-v1-5']


def test_a_gzipped_save_finds_the_segment_that_starts_at_its_unpacked_bytes(segments):
    tracer, held = segments
    packed = held.with_name('rung.state')
    packed.write_bytes(gzip.compress(b'held'))
    assert trace.held_segment(tracer.folder, packed).name == 'auto-v1-2'
    packed.write_bytes(b'\x1f\x8b broken')
    assert trace.held_segment(tracer.folder, packed) is None
    assert trace.held_segment(tracer.folder, held.with_name('missing.state')) is None
    assert trace.held_segment(tracer.folder, None) is None


def test_a_gen1_give_up_keeps_a_bundle_before_it_abandons_the_project(tmp_path):
    abandoned = []
    playing = game(tmp_path, supervisor=ladder(5), input_epoch=0, _handle_events=lambda events, snap: None)
    Emulator._autosave(playing)
    playing.policy = SimpleNamespace(collection=SimpleNamespace(project='dex', abandon=abandoned.append),
                                     goal=SimpleNamespace(title='Catch Lapras'), on_restore=lambda: None, details=dict)
    assert Emulator._give_up(playing, 'stuck')
    folder, report = kept(playing.store)
    assert report['kind'] == 'give_up' and report['why'] == 'stuck' and report['has_before']
    assert (folder / 'before.state').read_bytes() == b'state' and abandoned


def test_a_new_loop_keeps_one_bundle_in_either_generation(tmp_path):
    for generation, check in ((1, Emulator._check_guards), (2, Gen2Emulator._check_guards)):
        trips = iter([LOOP, None])
        playing = game(tmp_path / str(generation), last_reload_frame=0, paused=False, manual_mode=False,
                       preparation=False, loop_guard=SimpleNamespace(looping=lambda store: None,
                                                                     take_trip=lambda: next(trips)))
        check(playing)
        check(playing)
        _, report = kept(playing.store)
        assert report['kind'] == 'loop' and report['why'] == LOOP and not report['has_before']


def gen2(tmp_path, seen, **extra):
    playing = game(tmp_path, steps=SimpleNamespace(flush=lambda force=False: None),
                   statistics=SimpleNamespace(flush=lambda snapshot: None), history={}, screen_frame=0,
                   battle_frame=None, _event=lambda event, snapshot: seen.append(event), **extra)
    playing.policy.recoveries = 0
    return playing


def test_a_gen2_quiet_stretch_keeps_a_bundle_from_the_first_autosave_after_progress(tmp_path):
    seen = []
    playing = gen2(tmp_path, seen)
    Gen2Emulator._autosave(playing)
    assert playing.store.state_path(BEFORE_STALL_CHECKPOINT).read_bytes() == b'state' and not playing.stall.fresh
    playing.stall.progress(0, 0)
    playing.play_clock.frames = 130 * MINUTE
    Gen2Emulator._check_stall(playing)
    folder, report = kept(playing.store)
    assert report['kind'] == 'quiet' and report['why'] == 'no progress for 130 game minutes'
    assert report['has_before'] and report['party'] == [['Lapras', 40, 0, 0]] and len(seen) == 1
    # The same stretch keeps no second bundle.
    playing.play_clock.frames += MINUTE
    Gen2Emulator._check_stall(playing)
    assert len(list(playing.store.stalls.iterdir())) == 1


def test_a_gen2_give_up_keeps_a_bundle_before_the_rung_stands_down(tmp_path, monkeypatch):
    stood = []
    monkeypatch.setattr(standdown, 'rung_key', lambda rung: rung)
    monkeypatch.setattr(standdown, 'stalled_objectives', lambda policy: {'keys': []})
    monkeypatch.setattr(standdown, 'stand_down', lambda policy, key: stood.append(key))
    playing = gen2(tmp_path, [], supervisor=ladder(5), _reset_watch=lambda: None)
    playing.policy.ladder_rung, playing.policy.goal, playing.policy.menu = 'dex_10', None, None
    assert Gen2Emulator._give_up(playing, 'stuck')
    _, report = kept(playing.store)
    assert report['kind'] == 'give_up' and stood == ['dex_10'] and playing.policy.ladder_rung is None


def test_a_headless_run_keeps_the_same_bundle(tmp_path):
    run = SimpleNamespace(state=lambda: b'noticed', manifest=lambda: dict(MANIFEST))
    before = CheckpointStore(tmp_path / 'states').write_checkpoint(b'before', MANIFEST, compress=True)
    first = capture.keep_run(run, tmp_path / 'stalls' / 'stall-00130m', {'kind': 'ladder'}, before=before,
                             compress=True)
    again = capture.keep_run(run, tmp_path / 'stalls' / 'stall-00130m', {'kind': 'ladder'}, compress=True)
    assert again.name == 'stall-00130m-2'
    assert gzip.decompress((first / 'noticed.state').read_bytes()) == b'noticed'
    assert json.loads((first / 'report.json').read_text()) == {'kind': 'ladder', 'has_before': True}


def bundle(tmp_path, compress=False):
    """A quiet stall bundle whose save from before it is at frame 100, noticed at frame 900."""
    before = CheckpointStore(tmp_path / 'states').write_checkpoint(
        b'before', dict(MANIFEST, frame=100, rom_sha1='f' * 40), compress=compress)
    return write_bundle(tmp_path / 'stall', b'noticed', dict(MANIFEST, frame=900), {'kind': 'quiet', 'frame': 900},
                        None, before)


@pytest.fixture
def cli(tmp_path):
    root, index = tmp_path / 'scenarios', tmp_path / 'index.toml'

    def run(source, name='seafoam-boulders', *more):
        return main(['capture', str(source), '--name', name, '--root', str(root), '--index', str(index), *more])
    run.root, run.index = root, index
    return run


def test_capture_keeps_the_scenario_and_writes_its_row(tmp_path, cli):
    assert cli(bundle(tmp_path), 'seafoam-boulders', '--issue', '#412') == 0
    folder = cli.root / 'seafoam-boulders'
    assert (folder / 'start.state').read_bytes() == b'before'
    setup = json.loads((folder / 'scenario.json').read_text())
    assert setup['checkpoint'] == 'start.state' and setup['budget_game_minutes'] == 240
    text = cli.index.read_text()
    assert text.startswith(scenario.HEADER)
    assert tomllib.loads(text)['scenario'] == [{'name': 'seafoam-boulders', 'rom_sha1': 'f' * 40,
                                               'state_sha256': sha(b'before'), 'frames': [100, 900],
                                               'expect': 'stuck', 'kind': 'quiet', 'issue': 412}]


def test_a_second_capture_needs_force_and_keeps_the_header(tmp_path, cli):
    source = bundle(tmp_path)
    cli(source)
    cli(source, 'route-30')
    with pytest.raises(SystemExit, match='already has a row'):
        cli(source)
    cli.index.write_text('# Notes kept above the rows.\n' + cli.index.read_text()[len(scenario.HEADER):])
    assert cli(source, 'seafoam-boulders', '--force', '--expect', 'passes') == 0
    text = cli.index.read_text()
    assert text.startswith('# Notes kept above the rows.\n\n[[scenario]]')
    found = {row['name']: row['expect'] for row in tomllib.loads(text)['scenario']}
    assert found == {'route-30': 'stuck', 'seafoam-boulders': 'passes'}


def test_a_gzipped_start_is_named_by_its_unpacked_bytes(tmp_path, cli):
    cli(bundle(tmp_path, compress=True))
    row, = tomllib.loads(cli.index.read_text())['scenario']
    assert row['state_sha256'] == sha(b'before')
    assert (cli.root / 'seafoam-boulders' / 'start.state').read_bytes()[:2] == b'\x1f\x8b'


def test_a_plain_save_is_its_own_window(tmp_path, cli):
    save = CheckpointStore(tmp_path / 'states').write_checkpoint(b'save', dict(MANIFEST, frame=40))
    cli(save)
    row, = tomllib.loads(cli.index.read_text())['scenario']
    assert row['frames'] == [40, 40] and 'kind' not in row


@pytest.mark.parametrize('name, root, message', [
    ('Seafoam Boulders', None, 'lower case'),
    ('seafoam', scenario.ROOT / 'tests', 'private game data'),
])
def test_a_bad_name_or_a_tracked_folder_is_refused(tmp_path, name, root, message):
    more = ['--root', str(root)] if root else ['--root', str(tmp_path / 'scenarios')]
    with pytest.raises(SystemExit, match=message):
        main(['capture', str(bundle(tmp_path)), '--name', name, '--index', str(tmp_path / 'index.toml'), *more])
    assert not (tmp_path / 'index.toml').exists()


def test_the_tracked_index_keeps_its_header_and_valid_rows():
    assert scenario.INDEX.read_text(encoding='utf-8').startswith(scenario.HEADER)
    for row in scenario.rows():
        assert scenario.NAME.fullmatch(row['name']) and row['expect'] in scenario.EXPECTS
        assert len(row['rom_sha1']) == 40 and len(row['state_sha256']) == 64 and len(row['frames']) == 2
        assert row.get('kind', 'quiet') in capture.KINDS
