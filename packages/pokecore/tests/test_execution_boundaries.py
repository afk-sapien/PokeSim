import pytest

from pokecore.emulator import Emulator, demo_rom

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
