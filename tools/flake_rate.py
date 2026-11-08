"""Count how often a push run on main failed once and passed when its failed jobs ran again.

The Rerun failed main workflow reruns a failed main push run once. A run whose first attempt failed and
whose second attempt passed is a flake. One that failed twice is a real failure.
Usage: GH_TOKEN=... python tools/flake_rate.py [--repo owner/name] [--days 30]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_release_gates import REQUIRED, api  # noqa: E402


def runs_of(repo, workflow, since, token):
    runs, page = [], 1
    while True:
        batch = api(f'repos/{repo}/actions/workflows/{workflow}/runs?branch=main&event=push'
                    f'&status=completed&created=>={since}&per_page=100&page={page}', token)['workflow_runs']
        runs.extend(batch)
        if len(batch) < 100:
            return runs
        page += 1


def tally(runs):
    """Return (runs, flakes, failures) for completed runs, judged by their latest attempt."""
    flakes = sum(run['run_attempt'] > 1 and run['conclusion'] == 'success' for run in runs)
    failures = sum(run['conclusion'] == 'failure' for run in runs)
    return len(runs), flakes, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'afk-sapien/PokeSim'))
    parser.add_argument('--days', type=int, default=30)
    arguments = parser.parse_args()
    token = os.environ['GH_TOKEN']
    since = (datetime.now(timezone.utc) - timedelta(days=arguments.days)).date().isoformat()
    for workflow in sorted(REQUIRED):
        total, flakes, failures = tally(runs_of(arguments.repo, workflow, since, token))
        rate = f'{100 * flakes / total:.1f}%' if total else 'n/a'
        print(f'{workflow}: {total} main push runs since {since}, {flakes} passed on the rerun ({rate}), '
              f'{failures} still failed')


if __name__ == '__main__':
    main()
