"""Run the local checks a bot behaviour pull request needs before it merges, and post the result on its commit.

CI cannot run them, since the ladder gate and the private stuck-scenario replays need the cartridges and
private saves on this machine. Push the branch first, then from its clean checkout run
  uv run --locked --extra dev python tools/preflight.py <cartridge folder> [--no-post]
It plays `tools/stage_ladder.py gate` (about 3 minutes) and then every replay under the heavy load gate
(about 7 minutes), and posts the `preflight` commit status on HEAD. A replay named in the scenarios folder's
known-failures.txt that fails is the known baseline. A gate failure, or any other failed, raised or skipped
replay, fails the preflight. The result also goes to the data folder's preflight/<commit>.json.
Gold, Silver and Crystal need GEN2_DATA_DIR, or the script prepares that data in .release-local/gen2-data.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = 'preflight'
REPLAY = 'test_the_player_gets_going_again'
GATE_TIMEOUT = '30m'
REPLAY_TIMEOUT = '40m'


def data_dir():
    return Path(os.environ.get('DATA_DIR') or ROOT / 'data')


def scenarios_dir():
    return Path(os.environ.get('POKESIM_SCENARIOS') or data_dir() / 'scenarios')


def head(root=ROOT):
    """The commit to test, refused while tracked files differ from it."""
    changed = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], check=True,
                             capture_output=True, text=True).stdout.strip()
    if changed:
        raise SystemExit('tracked files differ from HEAD, so commit or drop them first. The preflight tests HEAD.')
    return subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], check=True, capture_output=True,
                          text=True).stdout.strip()


def known_failures(path):
    """The scenario names in a known-failures file, without blank lines and # comments."""
    if not path.exists():
        return set()
    return {line.split('#', 1)[0].strip() for line in path.read_text(encoding='utf-8').splitlines()} - {''}


def replay_outcomes(junit):
    """Each replay's scenario and whether it passed, failed or was skipped, from a pytest JUnit report."""
    outcomes = {}
    if not Path(junit).exists():
        return outcomes
    for case in ET.parse(junit).getroot().iter('testcase'):
        name = case.get('name', '')
        if not name.startswith(f'{REPLAY}[') or not name.endswith(']'):
            continue
        if case.find('failure') is not None or case.find('error') is not None:
            outcome = 'failed'
        elif case.find('skipped') is not None:
            outcome = 'skipped'
        else:
            outcome = 'passed'
        outcomes[name[len(REPLAY) + 1:-1]] = outcome
    return outcomes


def judge(gate_code, pytest_code, outcomes, known):
    """The problems that fail the preflight, the known failures that now pass, and a summary for the status."""
    problems = []
    if gate_code != 0:
        problems.append(f'the ladder gate failed with exit {gate_code}')
    by = {outcome: sorted(name for name, seen in outcomes.items() if seen == outcome)
          for outcome in ('passed', 'failed', 'skipped')}
    new = [name for name in by['failed'] if name not in known]
    if new:
        problems.append(f'{len(new)} new replay failures: {", ".join(new)}')
    if by['skipped']:
        problems.append(f'{len(by["skipped"])} replays skipped: {", ".join(by["skipped"])}')
    if not outcomes:
        problems.append(f'no replays ran, pytest exit {pytest_code}')
    elif pytest_code not in (0, 1):
        problems.append(f'pytest stopped with exit {pytest_code}')
    fixed = [name for name in by['passed'] if name in known]
    if problems:
        summary = problems[0]
    else:
        summary = (f'gate passed, {len(by["passed"])} replays passed, '
                   f'{len(by["failed"])} known failures')
    return problems, fixed, summary[:140]


def post(sha, state, description):
    """Sets the preflight status on ``sha`` with the signed-in gh account."""
    subprocess.run(['gh', 'api', '-X', 'POST', f'repos/{{owner}}/{{repo}}/statuses/{sha}', '-f', f'state={state}',
                    '-f', f'context={CONTEXT}', '-f', f'description={description[:140]}'],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def pushed(sha):
    return subprocess.run(['gh', 'api', f'repos/{{owner}}/{{repo}}/commits/{sha}', '--silent'], cwd=ROOT,
                          check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def environment(roms):
    """The environment both checks run in, with Gen II game data prepared once when none is set."""
    env = dict(os.environ, DATA_DIR=str(data_dir()), GEN2_CARTRIDGE_DIR=str(roms))
    if not env.get('GEN2_DATA_DIR'):
        prepared = ROOT / '.release-local' / 'gen2-data'
        if not (prepared / 'gen2').is_dir():
            subprocess.run([sys.executable, str(ROOT / 'tools' / 'prepare_gen2_test_data.py'), str(prepared)],
                           cwd=ROOT, check=True)
        env['GEN2_DATA_DIR'] = str(prepared)
    return env


def run_gate(roms, env):
    """Plays the ladder gate, which takes the heavy load gate itself, and returns its exit code."""
    command = ['timeout', GATE_TIMEOUT, sys.executable, str(ROOT / 'tools' / 'stage_ladder.py'), 'gate', str(roms),
               str(data_dir() / 'ladder')]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def run_replays(env, junit):
    """Replays every private scenario in one pytest run under the heavy load gate and returns its exit code."""
    env = dict(env, POKESIM_SCENARIO_TESTS='1', POKESIM_SCENARIOS=str(scenarios_dir()))
    command = ['timeout', REPLAY_TIMEOUT, 'sh', str(ROOT / 'tools' / 'load_gate.sh'), 'heavy', sys.executable, '-m',
               'pytest', '-q', '-rfs', '-n', '0', '-p', 'no:cacheprovider', f'--junitxml={junit}',
               f'tests/test_scenarios.py::{REPLAY}']
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('roms', type=Path, help='a folder holding the clean cartridges')
    parser.add_argument('--no-post', action='store_true', help='print the result without posting a commit status')
    args = parser.parse_args(argv)
    sha = head()
    if not args.no_post and not pushed(sha):
        raise SystemExit(f'{sha[:7]} is not on GitHub, so push it first or pass --no-post')
    known = known_failures(scenarios_dir() / 'known-failures.txt')
    began = time.monotonic()
    if not args.no_post:
        post(sha, 'pending', 'playing the ladder gate and the private replays')
    try:
        env = environment(args.roms.resolve())
        gate_code = run_gate(args.roms.resolve(), env)
        with tempfile.TemporaryDirectory() as folder:
            junit = Path(folder) / 'replays.xml'
            pytest_code = run_replays(env, junit)
            outcomes = replay_outcomes(junit)
    except BaseException:
        if not args.no_post:
            post(sha, 'error', 'the preflight stopped before it finished')
        raise
    problems, fixed, summary = judge(gate_code, pytest_code, outcomes, known)
    report = {'commit': sha, 'passed': not problems, 'problems': problems, 'gate_exit': gate_code,
              'pytest_exit': pytest_code, 'known_failures': sorted(known), 'now_passing': fixed,
              'replays': outcomes, 'wall_seconds': round(time.monotonic() - began, 1)}
    out = data_dir() / 'preflight' / f'{sha}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    for problem in problems:
        print(problem)
    for name in fixed:
        print(f'{name} now passes, so take it off known-failures.txt once it passes on main')
    print(f'preflight {"passed" if not problems else "failed"} in {report["wall_seconds"]}s: {summary}. '
          f'Report in {out}')
    if not args.no_post:
        post(sha, 'success' if not problems else 'failure', summary)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
