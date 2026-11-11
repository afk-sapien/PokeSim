from pathlib import Path

import yaml

from tools import flake_rate

ROOT = Path(__file__).resolve().parents[1]


def run(attempt, conclusion):
    return {'run_attempt': attempt, 'conclusion': conclusion}


def test_a_run_that_passed_only_on_the_rerun_is_a_flake():
    runs = [run(1, 'success'), run(2, 'success'), run(2, 'failure'), run(1, 'cancelled')]
    assert flake_rate.tally(runs) == (4, 1, 1)


def test_each_workflow_reports_its_own_runs(monkeypatch, capsys):
    runs = {'ci.yml': [run(2, 'success'), run(1, 'failure'), run(1, 'success')],
            'python-install.yml': [run(2, 'success'), run(2, 'success'), run(2, 'failure'), run(1, 'failure'),
                                   run(1, 'success')]}

    def api(path, token):
        assert token == 'token'
        workflow = path.split('/workflows/')[1].split('/')[0]
        return {'workflow_runs': runs[workflow]}

    monkeypatch.setattr(flake_rate, 'api', api)
    monkeypatch.setenv('GH_TOKEN', 'token')
    monkeypatch.setattr('sys.argv', ['flake_rate.py', '--repo', 'owner/name'])
    flake_rate.main()
    lines = dict(line.split(': ', 1) for line in capsys.readouterr().out.splitlines())
    assert set(lines) == set(runs)
    assert lines['ci.yml'].startswith('3 main push runs') and '1 passed on the rerun (33.3%), 1 still failed' in lines['ci.yml']
    assert (lines['python-install.yml'].startswith('5 main push runs')
            and '2 passed on the rerun (40.0%), 2 still failed' in lines['python-install.yml'])


def test_the_rerun_workflow_watches_both_gated_workflows_and_reruns_only_once():
    workflow = yaml.safe_load((ROOT / '.github/workflows/rerun-failed-main.yml').read_text())
    # PyYAML reads the bare `on` key as True.
    trigger = workflow[True]['workflow_run']
    names = {yaml.safe_load((ROOT / '.github/workflows' / name).read_text())['name'] for name in flake_rate.REQUIRED}
    assert set(trigger['workflows']) == names
    assert trigger['branches'] == ['main']
    condition = workflow['jobs']['rerun']['if']
    assert "run_attempt == 1" in condition and "conclusion == 'failure'" in condition and "event == 'push'" in condition
