"""A manager's pin in the replay log (docs/design/typed-goals.md section 5): a run pinned mid-way replays
from its trace, with the pin script fed back, to the same records."""
import os

import pytest

from test_goal_catalogue import REPLAY_FRAMES, post_game

# The first step a manager may pin the catalogue's first goal on.
PIN_STEP = 40


def play(generation, rom, checkpoint, folder, pins=None):
    """Play ``REPLAY_FRAMES`` from ``checkpoint`` into a trace in ``folder``. With no ``pins`` a manager
    pins the catalogue's first goal at the first step from ``PIN_STEP`` on that lists one, and with
    ``pins`` the run takes that pin script. Gives the trace head, the frame, the policy's save, the step
    and key pinned, and the segment read back."""
    from pokecore import trace as core

    from pokesim.runtime import trace
    if generation == 1:
        from pokesim.headless import HeadlessRun
        from pokesim.ram import read_snapshot
        run = HeadlessRun(rom, checkpoint, seed=7, trace=folder, pins=pins)
        snapshot = lambda: read_snapshot(run.pb.memory, run.frame)  # noqa: E731
    else:
        from pokesim.gen2.headless import HeadlessRun
        run = HeadlessRun(rom, checkpoint, seed=7, trace=folder, data_root=os.environ['GEN2_DATA_DIR'], pins=pins)
        snapshot = run.read
    pinned = None
    try:
        end, steps = run.frame + REPLAY_FRAMES, 0
        while run.frame < end:
            now = snapshot()
            if pins is None and pinned is None and steps >= PIN_STEP:
                goals = run.policy.catalogue(now)['goals']
                if goals:
                    pinned = steps, goals[0]['key']
                    run.pin_goal(pinned[1], now)
            run.step(now)
            steps += 1
        played = run.tracer.recorder.head, run.frame, run.policy.state_dict(), pinned
        name = run.tracer.name
    finally:
        run.stop()
    return (*played, core.Trace.read(folder / name / trace.SEGMENT))


def logged(segment):
    return [(record['kind'], record['frame'], record.get('digest'), record.get('source'), record.get('payload'))
            for record in segment.records]


@pytest.mark.parametrize('generation', [1, 2], ids=['gen1', 'gen2'])
def test_a_run_pinned_mid_way_replays_from_its_pin_script(generation, tmp_path):
    from pokesim.runtime import trace
    rom, checkpoint = post_game(generation)
    first = play(generation, rom, checkpoint, tmp_path / 'first')
    pinned, segment = first[3], first[4]
    assert pinned is not None
    script = trace.pin_script(segment)
    assert script == [pinned]
    # What play did with the pin is in the log beside the manager's set.
    outcomes = [record['payload'] for record in segment.records if record.get('source') == 'pin_outcome']
    assert outcomes and outcomes[0]['key'] == pinned[1]
    again = play(generation, rom, checkpoint, tmp_path / 'again', pins=script)
    assert logged(again[4]) == logged(segment)
    assert again[:3] == first[:3]
