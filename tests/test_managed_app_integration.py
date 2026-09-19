"""Opt-in full manager orchestration and restart recovery on real cartridges."""
import os
from pathlib import Path

import pytest

from tools.check_managed_app import exercise_app


def test_three_workers_and_committed_manager_recovery(tmp_path):
    fixtures = os.environ.get('POKESIM_CABLE_FIXTURES')
    roms = os.environ.get('POKESIM_CABLE_ROMS')
    data = os.environ.get('GAME_DATA_DIR')
    if not all((fixtures, roms, data)):
        pytest.skip('Private cartridge fixtures, ROMs, and generated game data are required')
    result = exercise_app(tmp_path / 'application', Path(fixtures), Path(roms), Path(data))
    assert result['status'] == 'passed'
