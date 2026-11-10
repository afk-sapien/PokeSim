from copy import deepcopy

import pytest

from pokecore.emulator import Emulator, ReplayDivergence, demo_rom

pytest.importorskip('pyboy_rs')


@pytest.mark.parametrize('cancel_at,budget,reason,frames', [
    (0, 10, 'cancelled', 0), (3, 0, 'budget', 0), (3, 2, 'budget', 2),
    (3, 3, 'cancelled', 3), (3, 10, 'cancelled', 3), (20, 10, 'completed', 10),
])
def test_cancellation_and_budget_boundaries(cancel_at, budget, reason, frames):
    with Emulator(demo_rom()) as emulator:
        emulator.start_sequence([(('a',), 4), ((), 6)])
        result = emulator.run_sequence(budget, cancelled=lambda: emulator.frame_count >= cancel_at)
        assert (result['reason'], result['frames'], emulator.frame_count) == (reason, frames, frames)
        assert result['completed'] == (frames == 10)
        if frames < 10:
            assert emulator.run_sequence(10)['frames'] == 10 - frames
        assert emulator.frame_count == 10


def test_cancellation_exception_preserves_resumable_progress():
    with Emulator(demo_rom()) as emulator, Emulator(demo_rom()) as reference:
        steps = [(('a',), 4), ((), 6)]
        emulator.start_sequence(steps)
        reference.start_sequence(steps)
        def cancel():
            if emulator.frame_count == 3:
                raise LookupError('consumer disconnected')
            return False
        with pytest.raises(LookupError, match='disconnected'):
            emulator.run_sequence(10, cancelled=cancel)
        assert emulator.frame_count == 3
        assert emulator.sequence_progress['remaining'] == 1
        assert emulator.run_sequence(10)['frames'] == 7
        reference.run_sequence(10)
        assert emulator.checkpoint() == reference.checkpoint()


@pytest.mark.parametrize('logical_start', [0, 1000])
@pytest.mark.parametrize('diagnostic_interval', [0, 7])
def test_replay_failure_keeps_logical_timeline_and_can_be_retried(logical_start, diagnostic_interval):
    with Emulator(demo_rom()) as source, Emulator(demo_rom()) as target:
        values = [19, 20]
        for index, emulator in enumerate((source, target)):
            def hook(_, emulator=emulator, index=index):
                emulator.memory[0xc123] = values[index]
            emulator.hook_register(0, 0x100, hook, None)
        initial = source.checkpoint()
        initial['frames'] = logical_start
        source.restore_checkpoint(initial)
        source.start_recording(90, diagnostic_interval=diagnostic_interval)
        source.tick(90)
        recording = source.stop_recording()
        with pytest.raises(ReplayDivergence) as caught:
            target.replay(recording)
        report = caught.value.details
        assert target.frame_count == logical_start + report['first_failed_offset']
        assert target.memory[0xc123] == 20
        if diagnostic_interval:
            assert report['last_verified_offset'] > 0
            assert report['resolution_frames'] == 7
        values[1] = values[0]
        assert target.replay(recording)['verified']
        assert target.checkpoint() == source.checkpoint()
        assert recording['initial']['frames'] == logical_start


@pytest.mark.parametrize('interval', [0, 3])
def test_zero_frame_recording_preserves_pending_inputs_and_offset(interval):
    with Emulator(demo_rom()) as source, Emulator(demo_rom()) as target:
        source.tick(10)
        checkpoint = source.checkpoint()
        checkpoint['frames'] = 100
        source.restore_checkpoint(checkpoint)
        source.press('a')
        source.start_recording(3, diagnostic_interval=interval)
        recording = source.stop_recording()
        assert target.replay(recording)['frames'] == 0
        assert target.frame_count == 100
        assert target.pending_inputs == (('a', True),)
        source.tick(2)
        target.tick(2)
        assert target.checkpoint() == source.checkpoint()


def test_hook_can_advance_another_machine_without_double_counting_rejected_recursion():
    with Emulator(demo_rom()) as primary, Emulator(demo_rom()) as secondary:
        seen = []
        def hook(_):
            before = primary.frame_count
            secondary.tick(3)
            with pytest.raises(RuntimeError, match='recursively'):
                primary.tick(1)
            seen.append((before, primary.frame_count, secondary.frame_count))
        primary.hook_register(0, 0x100, hook, None)
        primary.tick(90)
        assert len(seen) == 1
        assert seen[0][0] > 0
        assert seen[0][0] == seen[0][1]
        assert seen[0][2] == secondary.frame_count == 3
        assert primary.frame_count == 90


@pytest.mark.parametrize('endpoint', ['initial', 'final'])
def test_invalid_hook_state_is_rejected_before_core_replay_mutates_machine(endpoint):
    with Emulator(demo_rom()) as emulator:
        emulator.hook_register(0, 0x100, lambda _: None, None)
        emulator.start_recording(2)
        emulator.tick(2)
        recording = emulator.stop_recording()
        invalid = deepcopy(recording)
        for checkpoint in (invalid[endpoint]['execution'], invalid['backend'][endpoint]):
            checkpoint['hook_opcodes'] = []
        emulator.press('b')
        before = emulator.checkpoint()
        with pytest.raises(ValueError, match='Hook instructions'):
            emulator.replay(invalid)
        assert emulator.checkpoint() == before
