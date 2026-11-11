"""Trace segments on the bundled demo ROM: the chain, verify, redecide and the recorder's attachment."""
import gzip
import shutil

import pytest

from pokecore.emulator import Emulator, Memory, demo_rom
from pokecore.trace import (DIVERGED, HARNESS, OK, Recorder, Segment, Trace, TraceError, chain_hash, digest, encoded,
                            main, read_chain, redecide, verify)

pytest.importorskip('pyboy_rs')

# The demo ROM runs this address about once a frame while WY (0xFF4A) is above 0x5A, from about frame 90.
HOOK = (0, 0x1C2)
WY = 0xFF4A
LEAD_IN = 90


def machine():
    return Emulator(demo_rom(), sound_emulated=False)


def hook_writes(game):
    def hook(_):
        game.memory[0xC123] = game.frame_count & 255
        game.memory[0xC130:0xC132] = [1, 2]
        game.register_file.A = game.register_file.A
    game.hook_register(*HOOK, hook, None)


def policy(choice='b', steps=6, retry=None, quiet=False, pipeline=None):
    """A small deterministic player: decide, press, tick, write. ``choice`` changes what it presses.

    ``quiet`` ticks with no rendering and no sound, as a headless production game does. ``pipeline``
    is the shadow pipeline pick each walk step logs.
    """
    flags = {'render': False, 'sound': False} if quiet else {}

    def play(recorder, _trace=None):
        game = recorder.emulator
        hook_writes(game)
        for step in range(steps):
            if pipeline is None:
                recorder.decide('walk', 1, step, 0)
            else:
                recorder.decide('walk', 1, step, 0, pipeline=pipeline)
            button = 'a' if step % 2 == 0 else choice
            game.press(button)
            game.tick(4, **flags)
            game.release(button)
            game.tick(2, **flags)
            game.memory[0xC200 + step] = step
            game.memory[WY] = 0x90
            if step == 2 and retry is not None:
                with recorder.reason('retry'):
                    game.load(retry)
        recorder.decide('done', 1, steps, 0)
    return play


def record(folder, play=None, *, check_every=10, lead_in=LEAD_IN, retry=False):
    """Record ``play`` on a fresh machine into folder/a.jsonl.gz. Returns the path."""
    path = folder / 'a.jsonl.gz'
    with machine() as game:
        game.tick(lead_in)
        saved = game.save() if retry else None
        recorder = Recorder(game, check_every=check_every)
        game.press('select')
        recorder.begin(Segment(path, keep_start=True), seed=7)
        (play or policy(retry=saved))(recorder)
        recorder.detach()
    return path


def rechained(trace, header=None, records=None):
    """The trace with a changed header or records and every hash made valid again."""
    header = dict(trace.header if header is None else header)
    previous, chained = digest(encoded(header)), []
    for record in (trace.records if records is None else records):
        record = dict(record)
        record['hash'] = chain_hash(previous, record)
        previous = record['hash']
        chained.append(record)
    return Trace(header, chained, path=trace.path)


@pytest.fixture
def recorded(tmp_path):
    return Trace.read(record(tmp_path, retry=True))


def test_a_segment_logs_every_change_and_verifies(recorded):
    kinds = {record['kind'] for record in recorded.records}
    assert {'decide', 'press', 'release', 'tick', 'write', 'load', 'check', 'hook'} <= kinds
    header = recorded.header
    assert header['seed'] == 7 and header['previous'] is None
    assert header['pending'] == [['select', True]]
    assert header['frame'] == LEAD_IN and 'clock' not in header
    assert (recorded.folder / f"{header['state_sha256']}.state").is_file()
    hooked = [record for record in recorded.records if record.get('hooks')]
    assert hooked, 'the demo hook should fire during the run'
    bank, address, fire, writes = hooked[0]['hooks'][0]
    assert [bank, address] == list(HOOK) and fire >= 0
    assert [0xC130, [1, 2]] in writes and ['A', writes[-1][1]] == writes[-1]
    assert any(record.get('reason') == 'retry' for record in recorded.records)
    result = verify(recorded, machine())
    assert (result.code, result.records) == (OK, len(recorded.records)), result.message


def test_a_tampered_record_breaks_the_chain(recorded, tmp_path):
    lines = gzip.decompress(recorded.path.read_bytes()).decode().splitlines()
    lines[4] = lines[4].replace('"kind":"', '"kind":"x', 1)
    broken = tmp_path / 'broken.jsonl.gz'
    broken.write_bytes(gzip.compress(('\n'.join(lines) + '\n').encode()))
    with pytest.raises(TraceError, match='unknown kind'):
        Trace.read(broken)
    records = [dict(item) for item in recorded.records]
    records[3]['frame'] += 1
    with pytest.raises(TraceError, match='breaks the hash chain'):
        Trace(recorded.header, records)
    with pytest.raises(TraceError, match='out of order'):
        Trace(recorded.header, recorded.records[1:])
    assert main(['verify', str(broken), '--rom', str(demo_rom())]) == HARNESS


def test_a_changed_write_value_diverges_at_the_next_digest(recorded):
    records = [dict(item) for item in recorded.records]
    write = next(item for item in records if item['kind'] == 'write' and 'address' in item)
    write['value'] = (write['value'] + 1) & 255
    result = verify(rechained(recorded, records=records), machine())
    assert result.code == DIVERGED
    assert result.details['index'] > write['index']
    assert result.details['kind'] in ('decide', 'check')


def test_a_changed_hook_write_diverges(recorded):
    records = [dict(item) for item in recorded.records]
    tick = next(item for item in records if item.get('hooks'))
    hooks = [[bank, address, fire, [list(pair) for pair in writes]] for bank, address, fire, writes in tick['hooks']]
    # Later fires overwrite 0xC123, so move the write to an address nothing else touches.
    hooks[0][3][0][0] = 0xC124
    tick['hooks'] = hooks
    assert verify(rechained(recorded, records=records), machine()).code == DIVERGED


def test_a_hook_that_no_longer_fires_diverges(recorded):
    records = [dict(item) for item in recorded.records]
    tick = next(item for item in records if item.get('hooks'))
    bank, address, fire, writes = tick['hooks'][0]
    tick['hooks'] = [[bank, address, fire + 10_000, writes]] + tick['hooks'][1:]
    result = verify(rechained(recorded, records=records), machine())
    assert result.code == DIVERGED and 'did not fire' in result.message


def test_provenance_mismatches_are_harness_failures(recorded):
    assert verify(recorded, machine(), state=b'not the start').code == HARNESS
    other = dict(recorded.header, rom_sha256='0' * 64)
    assert verify(rechained(recorded, header=other), machine()).code == HARNESS
    older = dict(recorded.header, emulator={'backend': 'pyboy-rs', 'version': '0.0.1'})
    result = verify(rechained(recorded, header=older), machine())
    assert result.code == HARNESS and '0.0.1' in result.message
    assert verify(rechained(recorded, header=older), machine(), check_emulator=False).code == OK
    busy = machine()
    busy.press('a')
    assert verify(recorded, busy).code == HARNESS


def test_a_missing_kept_state_is_a_harness_failure(recorded, tmp_path):
    lone = tmp_path / 'lone'
    lone.mkdir()
    shutil.copy(recorded.path, lone / 'a.jsonl.gz')
    result = verify(lone / 'a.jsonl.gz', machine())
    assert result.code == HARNESS and 'not kept' in result.message
    assert verify(lone / 'a.jsonl.gz', machine(), states=recorded.folder).code == OK


def test_a_write_from_a_hook_registered_before_attach_is_refused(tmp_path):
    path = tmp_path / 'a.jsonl.gz'
    with machine() as game:
        hook_writes(game)
        recorder = Recorder(game)
        recorder.begin(Segment(path, keep_start=True))
        game.tick(LEAD_IN + 10)
        recorder.detach()
    trace = Trace.read(path)
    assert any(record.get('unrecorded') for record in trace.records)
    result = verify(trace, machine())
    assert result.code == HARNESS and 'could not log' in result.message


def test_begin_follows_a_memory_object_the_emulator_built_after_attaching(tmp_path):
    from pokecore.memory_snapshot import snapshot_emulator
    recorders = []

    class Attached(Emulator):
        """Attaches a recorder at the end of the base constructor, before the snapshot memory exists."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            recorders.append(Recorder(self))

    path = tmp_path / 'a.jsonl.gz'
    with snapshot_emulator(Attached)(demo_rom(), sound_emulated=False) as game:
        (recorder,) = recorders
        built = game.memory
        assert type(built).__name__ == 'SnapshotMemory'
        game.tick(LEAD_IN)
        recorder.begin(Segment(path, keep_start=True))
        assert type(built).__name__ == 'TracedSnapshotMemory'
        game.memory[0xC123] = 5
        game.tick(2)
        recorder.detach()
        assert type(built).__name__ == 'SnapshotMemory'
    writes = [record for record in Trace.read(path).records if record['kind'] == 'write']
    assert [(record['address'], record['value']) for record in writes] == [(0xC123, 5)]
    assert verify(path, machine()).code == OK


def test_a_cut_off_segment_keeps_its_complete_records(tmp_path):
    path = tmp_path / 'a.jsonl.gz'
    with machine() as game:
        game.tick(LEAD_IN)
        recorder = Recorder(game, check_every=10)
        segment = Segment(path, keep_start=True)
        recorder.begin(segment)
        hook_writes(game)
        for _ in range(4):
            game.tick(5)
        segment.flush()
        shutil.copy(path, tmp_path / 'cut.jsonl.gz')
        game.tick(5)
        recorder.detach()
    whole, cut = Trace.read(path), Trace.read(tmp_path / 'cut.jsonl.gz')
    assert cut.truncated and not whole.truncated
    assert cut.records and cut.records == whole.records[:len(cut.records)]
    assert verify(cut, machine()).code == OK


def test_segments_chain_and_a_new_begin_names_the_last_head(tmp_path):
    first, second = tmp_path / '1.jsonl.gz', tmp_path / '2.jsonl.gz'
    with machine() as game:
        game.tick(LEAD_IN)
        recorder = Recorder(game)
        recorder.begin(Segment(first, keep_start=True))
        hook_writes(game)
        game.tick(3)
        head = recorder.head
        header = recorder.begin(Segment(second, keep_start=True))
        assert header['previous'] == head
        assert header['hooks'] == [list(HOOK)]
        game.tick(6)
        recorder.detach()
    assert any(record.get('hooks') for record in Trace.read(second).records)
    traces = read_chain([first, second])
    assert traces[0].head == head
    with pytest.raises(TraceError, match='does not follow'):
        read_chain([second, first])
    assert verify(second, machine()).code == OK
    with pytest.raises(ValueError, match='reserved'):
        Recorder(machine()).begin(Segment(tmp_path / '3.jsonl.gz'), frame=1)


def test_redecide_matches_the_same_policy_and_stops_at_a_changed_one(tmp_path):
    path = record(tmp_path)
    same = redecide(path, machine(), policy())
    assert same.code == OK, same.message
    changed = redecide(path, machine(), policy(choice='down'))
    assert changed.code == DIVERGED
    assert changed.details['kind'] == 'press'
    assert changed.details['last_decide']['goal'] == 'walk'
    shorter = redecide(path, machine(), policy(steps=2))
    assert shorter.code == DIVERGED


def test_a_pipeline_pick_is_logged_when_given_and_compared_when_logged(tmp_path):
    pick = {'goal': 'walk', 'source': 'story', 'rule': 'rank'}
    path = record(tmp_path, policy(pipeline=pick))
    decides = [record for record in Trace.read(path).records if record['kind'] == 'decide']
    assert [record.get('pipeline') for record in decides] == [pick] * 6 + [None]
    assert verify(path, machine()).code == OK
    assert redecide(path, machine(), policy(pipeline=pick)).code == OK
    changed = redecide(path, machine(), policy(pipeline={**pick, 'goal': 'heal'}))
    assert changed.code == DIVERGED and changed.details['kind'] == 'decide'
    assert redecide(path, machine(), policy()).code == DIVERGED
    # A log from before the field still replays under a policy that logs it.
    older = tmp_path / 'older'
    older.mkdir()
    assert redecide(record(older), machine(), policy(pipeline=pick)).code == OK


def test_a_quiet_recording_logs_its_flags_and_replays_with_them(tmp_path):
    path = record(tmp_path, policy(quiet=True), check_every=1)
    ticks = [record for record in Trace.read(path).records if record['kind'] == 'tick']
    assert ticks and all(record['render'] is False and record['sound'] is False for record in ticks)
    assert verify(path, machine()).code == OK
    loud = redecide(path, machine(), policy())
    assert loud.code == OK, loud.message


def test_redecide_reaches_the_end_of_a_log_from_inside_a_broad_except(tmp_path):
    path = record(tmp_path)

    def stubborn(recorder, trace):
        try:
            policy()(recorder, trace)
            while True:
                recorder.emulator.tick(1)
        except Exception:
            pytest.fail('the stop should pass an except Exception block')

    assert redecide(path, machine(), stubborn).code == OK


def test_the_recorder_blocks_sequences_and_detach_restores_the_emulator(tmp_path):
    with machine() as game:
        before = (type(game.memory), type(game.register_file))
        recorder = Recorder(game)
        with pytest.raises(RuntimeError, match='cannot be traced'):
            game.start_sequence([((), 1)])
        with pytest.raises(RuntimeError, match='cannot be traced'):
            game.restore_checkpoint(game.checkpoint())
        assert type(game.memory) is not Memory
        recorder.begin(Segment(tmp_path / 'a.jsonl.gz'))
        recorder.detach()
        assert (type(game.memory), type(game.register_file)) == before
        assert not {'tick', 'press', 'load', 'start_sequence'} & set(vars(game))
        game.memory[0xC000] = 1
        game.tick(2)
        assert recorder.index == 0
        game.restore_checkpoint(game.checkpoint())


def test_the_command_line_verifies_on_an_emulator_built_from_the_header(tmp_path, capsys):
    from pokecore.cli import main
    path = record(tmp_path)
    assert main(['trace', 'verify', str(path), '--rom', str(demo_rom())]) == OK, capsys.readouterr()
    assert main(['trace', 'verify', str(tmp_path / 'missing.jsonl.gz'), '--rom', str(demo_rom())]) == HARNESS


def test_a_refused_tick_leaves_the_trace_clean(tmp_path):
    path = tmp_path / 'a.jsonl.gz'
    with machine() as game:
        recorder = Recorder(game)
        recorder.begin(Segment(path, keep_start=True))
        with pytest.raises(ValueError):
            game.tick(0)
        game.tick(2)
        recorder.detach()
    assert verify(path, machine()).code == OK
