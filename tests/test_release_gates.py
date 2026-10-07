"""The publish gate must accept only complete, successful runs and stay in step with the workflows."""
from pathlib import Path
import re

import pytest

from tools import check_release_gates as gates

ROOT = Path(__file__).resolve().parents[1]


def job(name, conclusion='success', status='completed', steps=()):
    return {'name': name, 'conclusion': conclusion, 'status': status,
            'steps': [{'name': step, 'conclusion': 'success'} for step in steps]}


def complete(workflow):
    names = list(gates.REQUIRED[workflow])
    steps = list(gates.REQUIRED_STEPS[workflow])
    return [job(names[0], steps=steps)] + [job(name) for name in names[1:]]


@pytest.mark.parametrize('workflow', sorted(gates.REQUIRED))
def test_complete_successful_run_passes(workflow):
    assert gates.judge(workflow, complete(workflow))[0] == 'ok'


@pytest.mark.parametrize('workflow', sorted(gates.REQUIRED))
def test_failed_skipped_cancelled_or_missing_jobs_do_not_pass(workflow):
    jobs = complete(workflow)
    for conclusion in ('failure', 'skipped', 'cancelled'):
        assert gates.judge(workflow, [{**jobs[0], 'conclusion': conclusion}, *jobs[1:]])[0] == 'fail'
    assert gates.judge(workflow, jobs[:-1])[0] == 'fail'
    assert gates.judge(workflow, [{**jobs[0], 'steps': []}, *jobs[1:]])[0] == 'fail'


def test_unfinished_runs_are_waited_for_not_passed():
    jobs = complete('ci.yml')
    assert gates.judge('ci.yml', [{**jobs[0], 'status': 'in_progress', 'conclusion': None}, *jobs[1:]])[0] == 'wait'
    assert gates.judge('ci.yml', [])[0] == 'wait'


def workflow_job_names(workflow):
    """The job names GitHub reports for a workflow file, with every matrix combination expanded."""
    import itertools
    import yaml
    names = []
    for key, job in yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())['jobs'].items():
        matrix = (job.get('strategy') or {}).get('matrix') or {}
        axes = {name: values for name, values in matrix.items() if name not in ('include', 'exclude')}
        combos = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
        combos = [combo for combo in combos if not any(all(combo.get(k) == v for k, v in out.items())
                                                       for out in matrix.get('exclude', []))]
        combos += [dict(item) for item in matrix.get('include', [])]
        if not combos:
            names.append(job.get('name', key))
            continue
        for combo in combos:
            if 'name' in job:
                names.append(re.sub(r'\$\{\{ matrix\.(\w+) \}\}', lambda m: str(combo[m.group(1)]), job['name']))
            else:
                names.append(f"{key} ({', '.join(str(value) for value in combo.values())})")
    return names


@pytest.mark.parametrize('workflow', sorted(gates.REQUIRED))
def test_required_jobs_are_exactly_the_jobs_of_the_workflow(workflow):
    """Every job, every matrix shard (Windows included), is required, and nothing is required that does not exist."""
    assert sorted(gates.REQUIRED[workflow]) == sorted(workflow_job_names(workflow))


@pytest.mark.parametrize('workflow', sorted(gates.REQUIRED))
def test_required_steps_exist_in_the_workflow_files(workflow):
    text = (ROOT / '.github/workflows' / workflow).read_text()
    for step in gates.REQUIRED_STEPS[workflow]:
        assert f'name: {step}' in text, step


def test_a_job_whose_name_only_shares_a_prefix_does_not_satisfy_the_gate():
    jobs = complete('python-install.yml')
    renamed = [job_ for job_ in jobs if job_['name'] != 'install (macos-15)']
    assert gates.judge('python-install.yml', renamed)[0] == 'fail'
    ci = complete('ci.yml')
    assert gates.judge('ci.yml', [job_ for job_ in ci if job_['name'] != 'container']
                       + [job('container-proxy-2')])[0] == 'fail'


def test_every_native_test_shard_is_required():
    required = gates.REQUIRED['python-install.yml']
    for shard in range(1, 5):
        assert f'native tests (windows-latest, {shard}/4)' in required
    jobs = complete('python-install.yml')
    for index, item in enumerate(jobs):
        if item['name'].startswith('native tests'):
            assert gates.judge('python-install.yml', jobs[:index] + jobs[index + 1:])[0] == 'fail', item['name']


def test_publish_job_is_the_only_writer_and_never_runs_in_a_dry_run():
    text = (ROOT / '.github/workflows/release.yml').read_text()
    jobs = re.split(r'^  (?=[a-z-]+:\n)', text.split('\njobs:\n')[1], flags=re.M)
    writers = [part.split(':')[0] for part in jobs if 'packages: write' in part or 'docker push' in part
               or 'gh release' in part or 'docker login' in part]
    assert writers == ['publish']
    publish = next(part for part in jobs if part.startswith('publish:'))
    assert 'if: ${{ inputs.dry_run != true }}' in publish
    assert 'gate' in publish.split('needs:')[1].split('\n')[0]


def test_shards_cover_the_suite_exactly_once(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('pokesim_root_conftest', ROOT / 'conftest.py')
    conftest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conftest)

    class Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid

    class Hook:
        def pytest_deselected(self, items):
            pass

    class Config:
        hook = Hook()

    names = [f'tests/test_{module}.py::t{i}' for module in 'abcdefg' for i in range((ord(module) % 5) + 1)]
    chosen = []
    for index in range(1, 4):
        monkeypatch.setenv('POKESIM_TEST_SHARD', f'{index}/3')
        items = [Item(name) for name in names]
        conftest.pytest_collection_modifyitems(Config(), items)
        assert items
        chosen.extend(item.nodeid for item in items)
    assert sorted(chosen) == sorted(names)


def test_validate_and_gate_both_refuse_unfinished_pins():
    text = (ROOT / '.github/workflows/release.yml').read_text()
    validate = text.split('\n  gate:')[0]
    assert 'python tools/check_release_pins.py --remote' in validate
    gate = text.split('\n  gate:')[1].split('\n  build:')[0]
    assert '--tree release-source' in gate
    assert 'ref: ${{ needs.validate.outputs.revision }}' in gate


def test_gate_main_stops_on_temporary_pins(tmp_path, monkeypatch, capsys):
    (tmp_path / 'pyproject.toml').write_text('dependencies = ["x @ https://example.test/refs/heads/a/temp-wheels/x.whl"]\n')
    (tmp_path / 'uv.lock').write_text('')
    (tmp_path / 'Dockerfile').write_text('')
    monkeypatch.setenv('GH_TOKEN', 'unused')
    monkeypatch.setattr('sys.argv', ['gate', '--repo', 'o/r', '--sha', 'abc', '--tree', str(tmp_path)])
    with pytest.raises(SystemExit) as stopped:
        gates.main()
    assert 'Release pins are not final' in str(stopped.value)
