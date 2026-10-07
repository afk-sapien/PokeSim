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
    names = [prefix + ')' if '(' in prefix else prefix for prefix in gates.REQUIRED[workflow]]
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


@pytest.mark.parametrize('workflow', sorted(gates.REQUIRED))
def test_required_names_exist_in_the_workflow_files(workflow):
    text = (ROOT / '.github/workflows' / workflow).read_text()
    for step in gates.REQUIRED_STEPS[workflow]:
        assert f'name: {step}' in text, step
    for prefix in gates.REQUIRED[workflow]:
        assert re.search(rf'^  {re.escape(prefix.split(" ")[0])}[a-z-]*:', text, re.M), prefix


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
    import conftest

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
