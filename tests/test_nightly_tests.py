"""tools/nightly_tests.sh's suite step, run on a copy of its scripts with a fake uv that plays no test."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# What pytest prints for a run with one failed replay.
PYTEST = '''short test summary info
FAILED tests/test_scenarios.py::test_the_player_gets_going_again[gold-b] - stuck
1 failed, 9 passed in 1.00s
'''
UV = '''#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_UV_CALLS"
case "$*" in *pytest*) printf '%s' "$FAKE_PYTEST"; exit 1 ;; esac
'''


def suite(tmp_path):
    """Runs the suite step from tmp_path/clone and returns the lines of its verdict file and uv's calls."""
    clone = tmp_path / 'clone'
    (clone / 'tools').mkdir(parents=True)
    for name in ('nightly_tests.sh', 'load_gate.sh'):
        shutil.copy(ROOT / 'tools' / name, clone / 'tools' / name)
    (tmp_path / 'bin').mkdir()
    (tmp_path / 'bin' / 'uv').write_text(UV, encoding='utf-8')
    (tmp_path / 'bin' / 'uv').chmod(0o755)
    (tmp_path / 'roms').mkdir()
    (tmp_path / 'roms' / 'red.gb').write_bytes(b'')
    (tmp_path / 'data' / 'scenarios').mkdir(parents=True)
    env = dict(os.environ, PATH=f'{tmp_path / "bin"}{os.pathsep}{os.environ["PATH"]}',
               FAKE_UV_CALLS=str(tmp_path / 'uv.txt'), FAKE_PYTEST=PYTEST,
               POKESIM_NIGHTLY_ENV=str(tmp_path / 'none.env'), POKESIM_NIGHTLY_RESULTS=str(tmp_path / 'results'),
               POKESIM_NIGHTLY_DAY='day', POKESIM_NIGHTLY_ROMS=str(tmp_path / 'roms'),
               POKESIM_NIGHTLY_DATA=str(tmp_path / 'data'), POKESIM_NIGHTLY_SCENARIOS=str(tmp_path / 'data' / 'scenarios'),
               POKESIM_LOAD_GATE=str(tmp_path / 'gate'), POKESIM_LOAD_GATE_HEAVY='1')
    subprocess.run(['bash', str(clone / 'tools' / 'nightly_tests.sh'), 'suite'], env=env, check=False, timeout=60)
    return ((tmp_path / 'results' / 'day.txt').read_text(encoding='utf-8').splitlines(),
            (tmp_path / 'uv.txt').read_text(encoding='utf-8').splitlines())


def test_the_suite_lets_the_helper_check_gen2_data_it_already_has(tmp_path):
    # A folder left by an older or broken preparation must still go through the helper, which checks each
    # game's manifest and prepares the data again when it fails.
    (tmp_path / 'clone' / '.release-local' / 'gen2-data' / 'gen2').mkdir(parents=True)
    _, calls = suite(tmp_path)
    assert 'run -q --locked python tools/prepare_gen2_test_data.py .release-local/gen2-data' in calls
