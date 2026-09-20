"""A stall keeps the moment it was noticed and the save from before it began."""
import json
from types import SimpleNamespace

from pokesim import config
from pokesim.checkpoints import CheckpointStore
from pokesim.emulator import BEFORE_STALL_CHECKPOINT, Emulator
from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE, StallWatch

MANIFEST = {'policy_state': {}, 'run_memory': {}, 'frame': 5}


def test_a_kept_autosave_outlives_pruning_and_still_validates(tmp_path):
    store = CheckpointStore(tmp_path / 'states')
    first = store.write_checkpoint(b'before', MANIFEST)
    store.keep_as(first, BEFORE_STALL_CHECKPOINT)
    for index in range(3):
        store.write_checkpoint(b'later %d' % index, MANIFEST)
    store.prune_autosaves(2)
    kept = store.state_path(BEFORE_STALL_CHECKPOINT)
    assert not first.exists() and kept.read_bytes() == b'before'
    assert store.checkpoint_metadata(kept)['frame'] == 5
    # Keeping a newer save replaces the old one instead of failing on the existing name.
    store.keep_as(store.latest_state(), BEFORE_STALL_CHECKPOINT)
    assert kept.read_bytes() == b'later 2' and len(store.autosaves()) == 2


def test_a_stall_bundle_holds_both_saves_and_old_bundles_are_dropped(tmp_path, monkeypatch):
    store = CheckpointStore(tmp_path / 'states')
    store.keep_as(store.write_checkpoint(b'before', MANIFEST), BEFORE_STALL_CHECKPOINT)
    stamps = iter(f'2026092{n}T000000Z' for n in range(1, 5))
    monkeypatch.setattr('pokesim.checkpoints.time.strftime', lambda *a: next(stamps))
    for _ in range(3):
        folder = store.write_stall_bundle(b'noticed', MANIFEST, {'map': 'Seafoam Islands B4F'}, b'png',
                                          store.state_path(BEFORE_STALL_CHECKPOINT), keep=2)
    assert [path.name for path in sorted(store.stalls.iterdir())] == ['stall-20260922T000000Z', 'stall-20260923T000000Z']
    bundle = CheckpointStore(folder)
    assert (folder / 'before.state').read_bytes() == b'before' and (folder / 'noticed.png').read_bytes() == b'png'
    assert bundle.checkpoint_metadata(folder / 'before.state') and bundle.checkpoint_metadata(folder / 'noticed.state')
    assert json.loads((folder / 'report.json').read_text()) == {'map': 'Seafoam Islands B4F', 'has_before': True}
    without = store.write_stall_bundle(b'noticed', MANIFEST, {}, None, None, keep=2)
    assert not (without / 'before.state').exists() and not json.loads((without / 'report.json').read_text())['has_before']


def test_only_progress_marks_the_next_autosave_as_the_one_to_keep():
    watch = StallWatch(game_minutes=120, real_minutes=0)
    assert watch.fresh
    watch.fresh = False
    watch.quiet(50 * MINUTE, 10)
    watch.quiet(10 * MINUTE, 20)            # a reloaded save restarts the clocks and nothing else
    assert not watch.fresh and watch.quiet(12 * MINUTE, 80) == (2, 1)
    watch.progress(13 * MINUTE, 90)
    assert watch.fresh


def game(tmp_path, **extra):
    store = CheckpointStore(tmp_path / 'states')
    snapshot = SimpleNamespace(valid=True, started=True, in_battle=0, map_name='Seafoam Islands B4F', x=4, y=9,
                               party=(SimpleNamespace(name='Lapras', level=40, hp=0, status=0),))
    store.get = lambda key: None
    store.set = store.prune_events = lambda *a: None
    return SimpleNamespace(store=store, snapshot=snapshot, stall=StallWatch(game_minutes=120, real_minutes=0),
                           play_clock=SimpleNamespace(state_dict=dict), policy=SimpleNamespace(state_dict=dict, details=dict),
                           _state_bytes=lambda: b'state', _manifest=lambda: dict(MANIFEST), _shot_png=lambda: b'png',
                           reloads=3, frame=0, **extra)


def test_the_first_autosave_after_progress_is_kept_and_later_ones_leave_it_alone(tmp_path):
    playing = game(tmp_path)
    Emulator._autosave(playing)
    kept = playing.store.state_path(BEFORE_STALL_CHECKPOINT)
    first = kept.stat().st_mtime_ns
    assert not playing.stall.fresh
    playing._state_bytes = lambda: b'inside the stall'
    Emulator._autosave(playing)
    assert kept.read_bytes() == b'state' and kept.stat().st_mtime_ns == first
    playing.stall.progress(10, 10)
    Emulator._autosave(playing)
    assert playing.store.state_path(BEFORE_STALL_CHECKPOINT).read_bytes() == b'inside the stall'


def test_a_save_inside_a_battle_is_never_the_one_kept(tmp_path):
    playing = game(tmp_path)
    playing.snapshot.in_battle = 2
    Emulator._autosave(playing)
    assert playing.store.state_path(BEFORE_STALL_CHECKPOINT) is None and playing.stall.fresh


def test_a_reported_stall_leaves_a_bundle_and_the_setting_turns_it_off(tmp_path, monkeypatch):
    seen = []
    playing = game(tmp_path, _handle_events=lambda events, snap: seen.extend(events))
    Emulator._autosave(playing)
    playing.stall.progress(0, 0)
    playing.frame = 130 * MINUTE
    Emulator._check_stall(playing, 600)
    folder, = playing.store.stalls.iterdir()
    report = json.loads((folder / 'report.json').read_text())
    assert report['has_before'] and report['reloads'] == 3 and report['party'] == [['Lapras', 40, 0, 0]]
    assert (folder / 'before.state').read_bytes() == b'state' and len(seen) == 1
    monkeypatch.setattr(config, 'KEEP_STALL_BUNDLES', 0)
    playing.stall.progress(0, 0)
    Emulator._check_stall(playing, 700)
    assert len(list(playing.store.stalls.iterdir())) == 1 and len(seen) == 2
