"""Exercise uploads in a fresh interpreter without the suite's cached game data."""
import os
from pathlib import Path
import subprocess
import sys

from pokesim import game_data


ROOT = Path(__file__).resolve().parents[1]


def test_first_rom_upload_and_start_without_legacy_data(tmp_path):
    result = subprocess.run([
        sys.executable, str(ROOT / 'tools/check_first_run.py'),
        '--data-dir', str(tmp_path), '--game-data', str(game_data.directory().resolve()),
    ], env={**os.environ, 'PYTHONPATH': str(ROOT)}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
