"""Opt-in real worker lifecycle, cartridge exchange, and durable adoption tests."""
import os
from pathlib import Path

import pytest

from tools.check_managed_cable import exercise


@pytest.mark.parametrize('abort', [False, True])
def test_real_managed_cable_flow(tmp_path, abort):
    fixtures = os.environ.get('POKESIM_CABLE_FIXTURES')
    roms = os.environ.get('POKESIM_CABLE_ROMS')
    data = os.environ.get('GAME_DATA_DIR')
    if not all((fixtures, roms, data)):
        pytest.skip('Private cartridge fixtures, ROMs, and generated game data are required')
    result = exercise(tmp_path / 'application', Path(fixtures), Path(roms), Path(data), abort)
    assert result['status'] == 'passed'
