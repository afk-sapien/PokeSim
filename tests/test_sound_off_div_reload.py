"""A save made with sound off after the game writes the divider register loads again.

PyBoy RS 0.1.2 kept a sound event in its scheduler while sound was off, and a write to DIV (0xFF04)
moved it to a state the loader rejects with "Invalid scheduler state". Yellow writes DIV often, so a
checkpoint made a few frames later could not be loaded. PyBoy RS 0.1.4 fixes the save. A file that
0.1.2 already wrote stays broken. The replay needs the private Yellow dojo checkpoint.
"""
import io
import os
from pathlib import Path

import pytest

from pokesim import yellow

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = Path(os.environ.get('POKESIM_SCENARIOS') or Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios')
CHECKPOINT = SCENARIO_ROOT / 'yellow-dojo-gift-20261028' / 'start.state'
YELLOW_ROM = Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc'))
pytestmark = [
    pytest.mark.skipif(not YELLOW_ROM.exists() or not yellow.is_yellow(YELLOW_ROM), reason='no retail Yellow ROM'),
    pytest.mark.skipif(not CHECKPOINT.is_file(), reason='no private Yellow dojo checkpoint'),
]


def boot():
    return yellow.open_emulator(str(YELLOW_ROM), window='null', sound_emulated=False)


@pytest.mark.parametrize('frames', range(1, 8))
def test_a_sound_off_save_after_a_div_write_reloads(frames):
    pb = boot()
    try:
        pb.load_state(io.BytesIO(CHECKPOINT.read_bytes()))
        pb.tick(frames, False)
        pb.memory[0xFF04] = 0
        pb.tick(1, False)
        saved = io.BytesIO()
        pb.save_state(saved)
        wram = bytes(pb.memory[0xC000:0xE000])
    finally:
        pb.stop(save=False)
    other = boot()
    try:
        other.load_state(io.BytesIO(saved.getvalue()))
        assert bytes(other.memory[0xC000:0xE000]) == wram
    finally:
        other.stop(save=False)
