"""A replay command prints its help on a machine without game data."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', ['find-stalls', 'progress', 'stuck-scenarios', 'validate-progress'])
def test_help_needs_no_game_data(name, tmp_path):
    env = {key: value for key, value in os.environ.items()
           if key not in {'ROM_PATH', 'GAME_DATA_DIR', 'GEN2_DATA_DIR', 'GEN2_CARTRIDGE_DIR', 'POKESIM_SCENARIOS'}}
    env['DATA_DIR'] = str(tmp_path)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT), env.get('PYTHONPATH')]))
    result = subprocess.run([sys.executable, '-m', 'pokesim.replay', name, '--help'],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f'usage: python -m pokesim.replay {name}')
