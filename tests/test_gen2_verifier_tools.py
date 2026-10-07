"""The Gen II verifier scripts take their cartridge and data folders from the environment, not the cwd."""
import os
import subprocess
import sys
from pathlib import Path

from pokesim import game_data

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd, env=None):
    # The scripts import modules that read the Gen I bundle, whose default location is relative to the cwd.
    env = {**(os.environ if env is None else env), 'GAME_DATA_DIR': str(game_data.directory().resolve())}
    return subprocess.run([sys.executable, str(ROOT / 'tools' / args[0]), *args[1:]], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def test_trading_verifier_refuses_to_resume_an_earlier_store(tmp_path):
    output = tmp_path / 'out'
    (output / 'store').mkdir(parents=True)
    result = run('verify_gen2_trading.py', '--game', 'gold', '--load', str(tmp_path / 'x.state'),
                 '--output', str(output), cwd=tmp_path)
    assert result.returncode == 2
    assert 'fresh --output' in result.stderr


def test_save_verifier_reads_its_data_folder_from_the_environment(tmp_path):
    env = {**os.environ, 'GEN2_DATA_DIR': str(tmp_path / 'data')}
    (tmp_path / 'rom.gbc').write_bytes(b'')
    (tmp_path / 's.state').write_bytes(b'')
    result = run('verify_gen2_save.py', 'rom.gbc', 's.state', '--game', 'gold', '--output', 'o.sav', cwd=tmp_path, env=env)
    assert result.returncode != 0
    assert str(tmp_path / 'data') in result.stderr
