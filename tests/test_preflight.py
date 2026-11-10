"""tools/preflight.py judges the ladder gate and the private replays against the known failures."""
import json
import subprocess

import pytest

from tools import preflight

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
<testcase classname="tests.test_scenarios" name="test_the_player_gets_going_again[red-a]"/>
<testcase classname="tests.test_scenarios" name="test_the_player_gets_going_again[gold-b]"><failure message="stuck"/></testcase>
<testcase classname="tests.test_scenarios" name="test_the_player_gets_going_again[silver-c]"><error message="raised"/></testcase>
<testcase classname="tests.test_scenarios" name="test_the_player_gets_going_again[blue-d]"><skipped message="no cartridge"/></testcase>
<testcase classname="tests.test_scenarios" name="test_scenarios_are_found_with_their_settings"/>
</testsuite></testsuites>
"""


def test_the_known_failures_file_skips_blank_lines_and_comments(tmp_path):
    path = tmp_path / 'known-failures.txt'
    path.write_text('# replays that fail on main\ngold-b\n\nsilver-c  # since October\n')
    assert preflight.known_failures(path) == {'gold-b', 'silver-c'}
    assert preflight.known_failures(tmp_path / 'missing.txt') == set()


def test_index_rows_that_expect_stuck_are_known_failures(tmp_path):
    index = tmp_path / 'index.toml'
    assert preflight.expected_stuck(index) == set()
    index.write_text('# header\n\n[[scenario]]\nname = "gold-b"\nexpect = "stuck"\n\n'
                     '[[scenario]]\nname = "red-a"\nexpect = "passes"\n')
    assert preflight.expected_stuck(index) == {'gold-b'}


def test_each_replay_outcome_is_read_from_the_junit_report(tmp_path):
    junit = tmp_path / 'replays.xml'
    junit.write_text(JUNIT)
    assert preflight.replay_outcomes(junit) == {'red-a': 'passed', 'gold-b': 'failed', 'silver-c': 'failed',
                                                'blue-d': 'skipped'}
    assert preflight.replay_outcomes(tmp_path / 'missing.xml') == {}


def test_only_failures_outside_the_baseline_fail_it():
    outcomes = {'red-a': 'passed', 'gold-b': 'failed', 'silver-c': 'failed'}
    problems, fixed, summary = preflight.judge(0, 1, outcomes, {'gold-b', 'silver-c', 'crystal-e'})
    assert problems == [] and fixed == []
    assert summary == 'gate passed, 1 replays passed, 2 known failures'
    problems, _, summary = preflight.judge(0, 1, outcomes, {'gold-b'})
    assert problems == ['1 new replay failures: silver-c'] and summary == problems[0]


def test_a_known_failure_that_passes_is_named_and_does_not_fail_it():
    problems, fixed, _ = preflight.judge(0, 0, {'red-a': 'passed'}, {'red-a'})
    assert problems == [] and fixed == ['red-a']


@pytest.mark.parametrize('gate, code, outcomes, problem', [
    (1, 0, {'red-a': 'passed'}, 'the ladder gate failed with exit 1'),
    (0, 0, {'red-a': 'passed', 'blue-d': 'skipped'}, '1 replays skipped: blue-d'),
    (0, 5, {}, 'no replays ran, pytest exit 5'),
    (0, 2, {'red-a': 'passed'}, 'pytest stopped with exit 2'),
])
def test_a_gate_failure_a_skipped_replay_or_a_broken_run_fails_it(gate, code, outcomes, problem):
    problems, _, summary = preflight.judge(gate, code, outcomes, set())
    assert problems == [problem] and summary == problem


def test_changed_tracked_files_are_refused(tmp_path):
    def git(*args):
        subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)

    git('init', '-q')
    (tmp_path / 'a.py').write_text('x = 1\n')
    git('add', 'a.py')
    git('-c', 'user.name=test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'a')
    (tmp_path / 'notes.txt').write_text('untracked files do not count\n')
    assert len(preflight.head(tmp_path)) == 40
    (tmp_path / 'a.py').write_text('x = 2\n')
    with pytest.raises(SystemExit, match='tracked files differ from HEAD'):
        preflight.head(tmp_path)


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """Runs main with the gate, the replays and gh replaced, and returns the statuses it posted."""
    posted = []
    data = tmp_path / 'data'
    (data / 'scenarios').mkdir(parents=True)
    (data / 'scenarios' / 'known-failures.txt').write_text('gold-b\n')
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.delenv('POKESIM_SCENARIOS', raising=False)
    monkeypatch.setattr(preflight, 'head', lambda: 'a' * 40)
    monkeypatch.setattr(preflight, 'pushed', lambda sha: True)
    monkeypatch.setattr(preflight, 'environment', lambda roms: {})
    monkeypatch.setattr(preflight, 'post', lambda sha, state, description: posted.append((state, description)))

    def start(gate=0, junit=JUNIT):
        def replays(env, path):
            path.write_text(junit)
            return 1
        monkeypatch.setattr(preflight, 'run_gate', lambda roms, env: gate)
        monkeypatch.setattr(preflight, 'run_replays', replays)
        return preflight.main([str(tmp_path / 'roms')]), posted, json.loads(
            (data / 'preflight' / f'{"a" * 40}.json').read_text())
    start.posted = posted
    return start


def test_a_passing_run_posts_pending_then_success(fake_run):
    junit = JUNIT.replace('<error message="raised"/>', '').replace('<skipped message="no cartridge"/>', '')
    code, posted, report = fake_run(junit=junit)
    assert code == 0
    assert posted == [('pending', 'playing the ladder gate and the private replays'),
                      ('success', 'gate passed, 3 replays passed, 1 known failures')]
    assert report['passed'] and report['replays']['gold-b'] == 'failed'


def test_an_index_row_that_expects_stuck_is_a_known_failure(fake_run, monkeypatch, capsys):
    monkeypatch.setattr(preflight, 'expected_stuck', lambda: {'silver-c', 'red-a'})
    code, _, report = fake_run(junit=JUNIT.replace('<skipped message="no cartridge"/>', ''))
    assert code == 0 and report['known_failures'] == ['gold-b', 'red-a', 'silver-c']
    out = capsys.readouterr().out
    assert 'red-a now passes, so set its row in scenarios/index.toml to expect passes' in out


def test_a_failing_run_posts_failure_with_the_first_problem(fake_run):
    code, posted, report = fake_run(gate=1)
    assert code == 1
    assert posted[-1] == ('failure', 'the ladder gate failed with exit 1')
    assert report['problems'] == ['the ladder gate failed with exit 1', '1 new replay failures: silver-c',
                                  '1 replays skipped: blue-d']


def test_a_run_that_raises_posts_an_error(fake_run, monkeypatch):
    def broken(roms, env):
        raise KeyboardInterrupt
    monkeypatch.setattr(preflight, 'run_gate', broken)
    with pytest.raises(KeyboardInterrupt):
        preflight.main(['roms'])
    assert fake_run.posted == [('pending', 'playing the ladder gate and the private replays'),
                               ('error', 'the preflight stopped before it finished')]


def test_an_unpushed_commit_is_refused_before_anything_runs(fake_run, monkeypatch):
    monkeypatch.setattr(preflight, 'pushed', lambda sha: False)
    with pytest.raises(SystemExit, match='is not on GitHub'):
        preflight.main(['roms'])
