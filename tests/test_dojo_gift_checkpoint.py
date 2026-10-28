"""A postgame Fighting Dojo return takes the Hitmon the collection chose, from its own ball, on purpose.

The replays need private checkpoints, kept as stuck scenarios under the data folder: a Yellow run that
wants Hitmonlee and a Red run that wants Hitmonchan, both with the dojo flags reset. The walk from the
Karate Master to the ball kept one goal key while its targets changed, so the stall timer from the
battle ran out at the ball. The random recovery step then pressed A below the other ball and took the
wrong Hitmon, and the project waited for a gift that was gone.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = Path(os.environ.get('POKESIM_SCENARIOS') or Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios')
# The Red run finishes its Kanto Marathon first, which takes about 42000 frames.
FRAMES = 120000
# The tile below each ball, where the player stands facing up to take it.
BALLS = {'HITMONLEE': (4, 2), 'HITMONCHAN': (5, 2)}
CASES = [('yellow-dojo-gift-20261028', 'HITMONLEE'), ('red-dojo-gift-20261028', 'HITMONCHAN')]


def replay(folder):
    """Play a dojo checkpoint until a Hitmon joins and say how it was taken."""
    from pokesim.ram import SPECIES_NAMES, read_snapshot
    from pokesim.scenarios import Scenario, open_run
    from pokesim.strategy_data import MAPS
    run, _ = open_run(Scenario.load(folder))
    try:
        start = run.frame
        snapshot = read_snapshot(run.pb.memory, run.frame)
        held = [mon.species for mon in snapshot.party]
        place, walks = None, []
        recovery_step = run.policy._recovery_step

        def watched(s):
            # The recovery step walks and presses A at random, so the gift walk must never use it.
            if s.map == MAPS['FIGHTING_DOJO'] and run.policy.goal.key == 'collect_gift':
                walks.append([s.frame - start, s.x, s.y])
            return recovery_step(s)
        run.policy._recovery_step = watched
        while run.frame - start < FRAMES:
            gift = run.policy.goal is not None and run.policy.goal.key == 'collect_gift'
            run.step(snapshot)
            snapshot = read_snapshot(run.pb.memory, run.frame)
            if gift and snapshot.map == MAPS['FIGHTING_DOJO']:
                place = (snapshot.x, snapshot.y)
            names = [SPECIES_NAMES.get(mon.species, '').upper() for mon in snapshot.party]
            joined = [name for name in names if name in BALLS and names.count(name) > held.count(name)]
            if joined or len(snapshot.party) < len(held):
                # A release before the gift makes room. Count from the new party.
                held = [mon.species for mon in snapshot.party]
            if joined:
                return {'received': joined[0], 'place': place, 'random_walks': walks, 'frames': run.frame - start}
        return {'received': None, 'place': place, 'random_walks': walks, 'frames': run.frame - start}
    finally:
        run.stop()


def _replay_in_variant(folder, variant):
    """The Gen I tables load once per process, so a run of the other variant gets its own interpreter."""
    from pokesim.game_data import VARIANT_ENV, current_variant
    if variant == current_variant():
        return replay(folder)
    env = {**os.environ, VARIANT_ENV: variant}
    done = subprocess.run([sys.executable, __file__, str(folder)], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=1800, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('name,wanted', CASES)
def test_the_dojo_gift_is_the_chosen_hitmon_from_its_own_ball(name, wanted):
    from pokesim.scenarios import Scenario, find_rom, gen1_variant, rom_candidates
    from pokesim.scenarios import cartridge as checkpoint_cartridge
    folder = SCENARIO_ROOT / name
    if not (folder / 'scenario.json').is_file():
        pytest.skip(f'No private {name} scenario under {SCENARIO_ROOT}')
    scenario = Scenario.load(folder)
    if find_rom(checkpoint_cartridge(scenario.checkpoint)[1], rom_candidates()) is None:
        pytest.skip(f'No cartridge for {name}')
    result = _replay_in_variant(folder, gen1_variant(scenario))
    assert result['received'] == wanted, result
    # Taken from the tile below its ball with no random recovery step in the dojo.
    assert tuple(result['place']) == BALLS[wanted], result
    assert result['random_walks'] == [], result


if __name__ == '__main__':
    print(json.dumps(replay(Path(sys.argv[1]))))
