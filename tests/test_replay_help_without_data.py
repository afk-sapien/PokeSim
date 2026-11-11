"""A replay command prints its help on a machine without game data."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_stuck_scenarios_help_needs_no_game_data(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if key not in {'ROM_PATH', 'GEN2_DATA_DIR', 'GEN2_CARTRIDGE_DIR', 'POKESIM_SCENARIOS'}}
    env['DATA_DIR'] = str(tmp_path)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(ROOT), env.get('PYTHONPATH')]))
    result = subprocess.run([sys.executable, '-m', 'pokesim.replay', 'stuck-scenarios', '--help'],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('usage: python -m pokesim.replay stuck-scenarios')
