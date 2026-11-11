"""Shadow mode changes no decision: a stuck scenario plays the same goals with the shadow arbiter on or off.

The replays need private checkpoints, kept as stuck scenarios under the data folder: two Red runs whose
collection picks the shadow compares and whose overworld decisions the decide pipeline weighs, and a Gold and a Silver postgame run whose ladder
and postgame rotation it compares. Each plays twice from the same seed, and every step's goal, frame
and position must match, then the saved policy state.
"""
import json
import os
from pathlib import Path

import pytest

from pokesim.scenarios import Scenario, find_rom, gen1_variant, gen2_data_root, open_run, rom_candidates
from pokesim.scenarios import cartridge as checkpoint_cartridge

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = Path(os.environ.get('POKESIM_SCENARIOS') or Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios')
FRAMES = 30000


def scenario(name, generation):
    folder = SCENARIO_ROOT / name
    if not (folder / 'scenario.json').is_file():
        pytest.skip(f'No private {name} scenario under {SCENARIO_ROOT}')
    if generation == 2 and not os.environ.get('GEN2_CARTRIDGE_DIR'):
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    if generation == 2 and not (gen2_data_root() / 'gen2').is_dir():
        pytest.skip('Set GEN2_DATA_DIR to generated Gen II game data')
    loaded = Scenario.load(folder)
    if find_rom(checkpoint_cartridge(loaded.checkpoint)[1], rom_candidates()) is None:
        pytest.skip(f'No cartridge for {name}')
    if generation == 1:
        from pokesim.game_data import current_variant
        if gen1_variant(loaded) != current_variant():
            pytest.skip(f'{name} needs the {gen1_variant(loaded)} tables')
    return loaded


def replay(loaded, enabled, frames=FRAMES):
    from pokesim.ram import read_snapshot
    run, _ = open_run(loaded)
    read = run.read if hasattr(run, 'read') else lambda: read_snapshot(run.pb.memory, run.frame)
    try:
        run.policy.shadow.enabled = enabled
        start, trace = run.frame, []
        while run.frame - start < frames:
            snapshot = read()
            run.step(snapshot)
            goal = run.policy.goal
            trace.append((run.frame, goal.key if goal else None, snapshot.map, snapshot.x, snapshot.y))
        state = json.dumps(run.policy.state_dict(), sort_keys=True, default=str)
        return trace, state, run.policy.shadow.summary()
    finally:
        run.stop()


# Each case, the shadow points it reaches and the frames it needs to reach them. The Silver run first
# frees seven box slots, up to the refill mark, before it trains.
CASES = [('red-partial-training-20260915', 1, {'pipeline', 'collection'}, FRAMES),
         ('red-cerulean-cave-hunt-20261008', 1, {'pipeline', 'collection'}, FRAMES),
         ('gold-expshare-full-bag-20261027', 2, {'ladder'}, FRAMES),
         ('silver-np-gate-corner-20261020', 2, {'ladder', 'postgame'}, 55000)]


@pytest.mark.slow
@pytest.mark.parametrize('name,generation,points,frames', CASES)
def test_the_chosen_goal_is_the_same_with_the_shadow_on_or_off(name, generation, points, frames):
    loaded = scenario(name, generation)
    on, on_state, summary = replay(loaded, True, frames)
    off, off_state, idle = replay(loaded, False, frames)
    assert set(summary['decisions']) == points, summary
    assert not summary['failed'], summary
    assert not idle['decisions']
    assert len(on) == len(off)
    assert next((i for i, (a, b) in enumerate(zip(on, off)) if a != b), None) is None
    assert on_state == off_state
