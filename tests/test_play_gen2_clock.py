"""play-gen2 freezes the cartridge clock at a fixed instant, so two runs of one seed match byte for byte."""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip('pyboy_rs')
from pokecore.gen2.clock import FIXED_CLOCK_EPOCH  # noqa: E402

from pokesim.replay import play_gen2  # noqa: E402

CRYSTAL = Path(os.environ.get('GEN2_CARTRIDGE_DIR', 'roms')) / 'crystal.gbc'
FRAMES = 600


@pytest.fixture
def play(tmp_path):
    if not CRYSTAL.exists() or not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR for a Crystal run')

    def run(name, *extra):
        output = tmp_path / name
        play_gen2.main([str(CRYSTAL), '--game', 'crystal', '--data', os.environ['GEN2_DATA_DIR'],
                        '--output', str(output), *extra])
        return output
    return run


def test_two_fresh_runs_end_in_the_same_state(play):
    first, second = play('first', '--frames', str(FRAMES)), play('second', '--frames', str(FRAMES))
    assert (first / 'final.state').read_bytes() == (second / 'final.state').read_bytes()
    # The clock stays frozen where the fresh run started it.
    assert json.loads((first / 'final.clock.json').read_text())['clock'] == FIXED_CLOCK_EPOCH


def test_two_continuations_of_one_state_end_in_the_same_state(play):
    start = play('start', '--frames', str(FRAMES)) / 'final.state'
    resume = ('--load', str(start), '--frames', str(FRAMES // 2))
    first, second = play('first', *resume), play('second', *resume)
    assert (first / 'final.state').read_bytes() == (second / 'final.state').read_bytes()
