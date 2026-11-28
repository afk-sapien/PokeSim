"""A workflow step that pipes a test run into a log must still fail when the tests fail."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
# How GitHub runs a step's script on Linux: an unnamed shell is `bash -e {0}`, `bash` adds pipefail.
SHELLS = {None: ['bash', '-e'], 'bash': ['bash', '--noprofile', '--norc', '-eo', 'pipefail']}


def step(workflow, name):
    jobs = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text(encoding='utf-8'))['jobs']
    return next(step for job in jobs.values() for step in job.get('steps', []) if step.get('name') == name)


@pytest.mark.parametrize('workflow', ['ci.yml', 'pokecore-release.yml'])
def test_the_pokecore_suite_step_fails_when_a_test_fails(workflow, tmp_path):
    found = step(workflow, 'Run the pokecore suite without silent skips')
    tools = tmp_path / 'bin'
    tools.mkdir()
    # A pytest run with one failure and no skips, which the skip check alone lets through.
    uv = tools / 'uv'
    uv.write_text('#!/bin/sh\necho "1 failed, 40 passed in 0.50s"\nexit 1\n', encoding='utf-8')
    uv.chmod(0o755)
    script = tmp_path / 'step.sh'
    script.write_text(found['run'], encoding='utf-8')
    env = {**os.environ, 'PATH': f'{tools}{os.pathsep}{os.environ["PATH"]}', 'RUNNER_TEMP': str(tmp_path)}
    result = subprocess.run([*SHELLS[found.get('shell')], str(script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, result.stdout
