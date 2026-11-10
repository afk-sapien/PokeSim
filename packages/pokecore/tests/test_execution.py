from copy import deepcopy

import pytest

from pokecore.emulator import Emulator, demo_rom

pyboy_rs = pytest.importorskip('pyboy_rs')


def test_core_sequence_recording_checkpoint_and_profile():
    with Emulator(demo_rom()) as first, Emulator(demo_rom()) as resumed, Emulator(demo_rom()) as replayed:
        first.tick(90)
        first.start_recording(20)
        profiling = pyboy_rs.has_feature('profiling')
        if profiling:
            first.start_profiling()
        first.start_sequence([(('a',), 4), ((), 2), (('down',), 5)])
        result = first.run_sequence(3)
        assert result['frames'] == 3
        assert first.frame_count == 93
        checkpoint = first.checkpoint()
        assert checkpoint['format'] == 2
        resumed.restore_checkpoint(checkpoint)
        assert resumed.sequence_progress == first.sequence_progress
        first.run_sequence(5)
        resumed.run_sequence(5)
        assert first.checkpoint() == resumed.checkpoint()
        if profiling:
            assert first.stop_profiling()['samples'] > 0
        else:
            with pytest.raises(RuntimeError, match='not compiled'):
                first.start_profiling()
        recording = first.stop_recording()
        assert replayed.replay(recording)['verified']
        assert replayed.checkpoint() == first.checkpoint()
        first.run_sequence(100)
        replayed.run_sequence(100)
        assert replayed.checkpoint() == first.checkpoint()


def test_pending_core_inputs_and_hook_inputs_are_preserved():
    with Emulator(demo_rom()) as first, Emulator(demo_rom()) as second:
        for emulator in (first, second):
            def hook(_, emulator=emulator):
                emulator.press('b')
            emulator.hook_register(0, 0x100, hook, None)
        first.start_recording()
        first.start_sequence([(('a',), 90)])
        first.run_sequence(90)
        recording = first.stop_recording()
        second.replay(recording)
        assert first.checkpoint() == second.checkpoint()
        first.press('a')
        with pytest.raises(RuntimeError, match='pending Core'):
            first.start_sequence([((), 1)])


def test_core_recording_with_initial_and_final_pending_inputs():
    with Emulator(demo_rom()) as first, Emulator(demo_rom()) as second:
        first.tick(90)
        first.press('a')
        first.start_recording()
        first.tick(4)
        first.release('a')
        recording = first.stop_recording()
        second.replay(recording)
        assert first.pending_inputs == second.pending_inputs
        first.tick()
        second.tick()
        assert first.checkpoint() == second.checkpoint()


def test_invalid_core_recording_does_not_advance():
    with Emulator(demo_rom()) as emulator:
        emulator.start_recording()
        emulator.tick(2)
        recording = emulator.stop_recording()
        before = emulator.checkpoint()
        bad = deepcopy(recording)
        bad['final']['frames'] = -1
        with pytest.raises(ValueError):
            emulator.replay(bad)
        assert emulator.checkpoint() == before


def test_failed_recording_can_be_discarded_and_core_restored():
    with Emulator(demo_rom()) as emulator:
        def fail(_):
            raise LookupError('hook failure')
        emulator.hook_register(0, 0x100, fail, None)
        initial = emulator.checkpoint()
        emulator.start_recording()
        with pytest.raises(LookupError):
            emulator.tick(90)
        with pytest.raises(RuntimeError, match='interrupted'):
            emulator.stop_recording()
        emulator.restore_checkpoint(initial)
        assert emulator.checkpoint() == initial


def test_sequence_cancellation_observes_live_core_frames_after_restore():
    with Emulator(demo_rom()) as emulator:
        emulator.tick(90)
        checkpoint = emulator.checkpoint()
        checkpoint['frames'] = 1000
        emulator.restore_checkpoint(checkpoint)
        seen = []
        def cancelled():
            seen.append(emulator.frame_count)
            return emulator.frame_count >= 1003
        emulator.start_sequence([((), 10)])
        result = emulator.run_sequence(10, cancelled=cancelled)
        assert result['reason'] == 'cancelled'
        assert result['frames'] == 3
        assert seen == [1000, 1001, 1002, 1003]
        assert emulator.frame_count == 1003
        assert emulator.checkpoint()['frames'] == 1003
        assert emulator.run_sequence(10)['frames'] == 7
        assert emulator.frame_count == 1010


@pytest.mark.parametrize('advance', ['tick', 'tick_read', 'sequence'])
def test_frame_dependent_hooks_match_single_frames_and_replay(advance):
    with Emulator(demo_rom()) as recorded, Emulator(demo_rom()) as batched:
        seen = [[], []]
        for index, emulator in enumerate((recorded, batched)):
            def hook(_, emulator=emulator, index=index):
                seen[index].append(emulator.frame_count)
                emulator.memory[0xc123] = emulator.frame_count & 255
            emulator.hook_register(0, 0x100, hook, None)
        recorded.start_recording(90, diagnostic_interval=1)
        for _ in range(90):
            recorded.tick(1)
        recording = recorded.stop_recording()
        if advance == 'sequence':
            batched.start_sequence([((), 90)])
            batched.run_sequence(90)
        elif advance == 'tick_read':
            batched.tick_read(90, 0xc123, 0xc124)
        else:
            batched.tick(90)
        assert seen[0] and seen[0][0] > 0
        assert seen[1] == seen[0]
        expected = list(seen[0])
        seen[0].clear()
        assert recorded.replay(recording)['verified']
        assert seen[0] == expected
        assert recorded.frame_count == 90


def test_frame_count_survives_hook_failure_and_legacy_restore():
    with Emulator(demo_rom()) as emulator:
        seen = []
        def fail(_):
            seen.append(emulator.frame_count)
            raise LookupError('hook failure')
        emulator.hook_register(0, 0x100, fail, None)
        initial = emulator.checkpoint()
        with pytest.raises(LookupError, match='hook failure'):
            emulator.tick(90)
        assert seen and seen[0] > 0
        assert emulator.frame_count == seen[0]
        emulator.restore_checkpoint(initial)
        assert emulator.frame_count == 0
        emulator.hook_deregister(0, 0x100)
        emulator.tick(90)
        legacy = emulator.checkpoint()
        legacy['format'] = 1
        del legacy['execution']
        emulator.tick(10)
        emulator.restore_checkpoint(legacy)
        assert emulator.frame_count == 90
        emulator.tick(3)
        assert emulator.frame_count == 93
