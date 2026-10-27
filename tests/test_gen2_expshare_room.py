"""A Gen II trainee whose held item the full bag cannot take back gets room made in the bag, then the share.

The replay needs a private Gold checkpoint, kept as a stuck scenario under the data folder: the postgame
Goldenrod Pokémon Center with Shellder in training, holding a Pearl, and an items pocket with every entry
taken. The game refuses the Exp. Share swap there, and the plan used to name it again after every refusal.
"""
from collections import Counter
import os
from pathlib import Path

import pytest

from pokesim.scenarios import Scenario, find_rom, gen2_data_root, open_run, rom_candidates
from pokesim.scenarios import cartridge as checkpoint_cartridge

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = Path(os.environ.get('POKESIM_SCENARIOS') or Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios')
FOLDER = SCENARIO_ROOT / 'gold-expshare-full-bag-20261027'
FRAMES = 24000
SHELLDER = 90


def test_a_full_bag_makes_room_for_the_exp_share_swap_from_a_real_checkpoint():
    if not os.environ.get('GEN2_CARTRIDGE_DIR'):
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    if not (FOLDER / 'scenario.json').is_file():
        pytest.skip(f'No private {FOLDER.name} scenario under {SCENARIO_ROOT}')
    if not (gen2_data_root() / 'gen2').is_dir():
        pytest.skip('Set GEN2_DATA_DIR to generated Gen II game data')
    scenario = Scenario.load(FOLDER)
    if find_rom(checkpoint_cartridge(scenario.checkpoint)[1], rom_candidates()) is None:
        pytest.skip('No Gold cartridge for the scenario')
    run, _ = open_run(scenario)
    start, frames, labels = run.frame, Counter(), set()
    while run.frame - start < FRAMES:
        before = run.frame
        run.step(run.read())
        goal = run.policy.goal
        frames[goal.key if goal else run.policy.mode] += run.frame - before
        if goal:
            labels.add(goal.label)
    # The swap loop took most of these frames before. Now a spare item goes to the PC and the swap succeeds.
    assert frames['collection_tidy'], frames.most_common(5)
    assert frames['collection_equip'] < FRAMES // 8, frames.most_common(5)
    share = run.policy.data.items['EXP_SHARE']
    assert any(mon.held_item == share for mon in run.read().party if mon.species == SHELLDER), labels
