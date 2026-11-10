import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'local_sims.sh'


def fake_systemd(tmp_path, installed=True, unit_active=False):
    """Put a systemctl and a systemd-run on PATH that log their arguments, one call per line.

    systemd calls any slice loaded, so `show` reports the slice's unit file, or none."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'calls.log'
    active = 0 if unit_active else 3
    fragment = '/units/pokesim-sims.slice' if installed else ''
    (bin_dir / 'systemctl').write_text(
        '#!/bin/sh\necho "systemctl $*" >> "$FAKE_LOG"\n'
        f"case $2 in show) echo '{fragment}' ;; is-active) exit {active} ;; esac\n",
        encoding='utf-8')
    (bin_dir / 'systemd-run').write_text('#!/bin/sh\necho "systemd-run $*" >> "$FAKE_LOG"\n', encoding='utf-8')
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    env = {**os.environ, 'PATH': f"{bin_dir}{os.pathsep}{os.environ['PATH']}", 'FAKE_LOG': str(log),
           'XDG_CONFIG_HOME': str(tmp_path / 'config')}
    env.pop('GEN2_DATA_DIR', None)
    env.pop('POKESIM_SIM_MEMORY', None)
    return env, log


def run(env, *args):
    return subprocess.run(['sh', str(SCRIPT), *args], capture_output=True, text=True, timeout=30, env=env)


def test_install_copies_every_pokesim_slice_and_reloads(tmp_path):
    env, log = fake_systemd(tmp_path)
    done = run(env, 'install')
    assert done.returncode == 0, done.stderr
    installed = sorted(p.name for p in (tmp_path / 'config' / 'systemd' / 'user').iterdir())
    assert installed == ['pokesim-sims.slice', 'pokesim-tests.slice', 'pokesim.slice']
    assert log.read_text(encoding='utf-8').splitlines() == ['systemctl --user daemon-reload']


def test_the_slices_cap_pokesim_at_12_cores_and_let_tests_win_the_cpu():
    slices = {name: (ROOT / 'deploy' / 'systemd' / name).read_text(encoding='utf-8')
              for name in ('pokesim.slice', 'pokesim-sims.slice', 'pokesim-tests.slice')}
    assert 'CPUQuota=1200%' in slices['pokesim.slice']
    assert 'MemoryMax=12G' in slices['pokesim-sims.slice']
    assert 'MemoryMax=10G' in slices['pokesim-tests.slice']
    weight = {name: int(text.split('CPUWeight=')[1].split()[0])
              for name, text in slices.items() if 'CPUWeight=' in text}
    assert weight['pokesim-tests.slice'] > weight['pokesim-sims.slice']


@pytest.mark.parametrize('unit_active', [False, True])
def test_start_runs_the_app_as_a_capped_service_in_the_sims_slice(tmp_path, unit_active):
    env, log = fake_systemd(tmp_path, unit_active=unit_active)
    env['GEN2_DATA_DIR'] = '/gen2'
    done = run(env, 'start', 'sims-unit', '/env', '/code', '/data', '8765', 'abc1234')
    assert done.returncode == 0, done.stderr
    calls = log.read_text(encoding='utf-8').splitlines()
    assert ('systemctl --user stop sims-unit' in calls) is unit_active
    assert calls[-1] == (
        'systemd-run --user --unit sims-unit --collect --slice=pokesim-sims.slice'
        ' -p Nice=19 -p MemoryMax=12G -p KillMode=mixed -p TimeoutStopSec=120 -p WorkingDirectory=/code'
        ' --setenv=AUTH=none --setenv=POKESIM_REVISION=abc1234 --setenv=GEN2_DATA_DIR=/gen2'
        ' /env/bin/pokesim app --data-dir /data --host 127.0.0.1 --port 8765'
        ' --public-url http://127.0.0.1:8765 --no-browser')


def test_start_refuses_before_the_slices_are_installed(tmp_path):
    env, log = fake_systemd(tmp_path, installed=False)
    done = run(env, 'start', 'sims-unit', '/env', '/code', '/data', '8765', 'abc1234')
    assert done.returncode == 1
    assert 'local_sims.sh install first' in done.stderr
    assert not any(line.startswith('systemd-run') for line in log.read_text(encoding='utf-8').splitlines())
