"""Require that the CI and Python install workflows already passed for one exact commit.

The publish workflow uses this instead of repeating the whole verification matrix. A run counts only
when it is a push run of this repository's workflow file for the exact commit, every job in it
succeeded (a skipped or cancelled job is not a pass), and every required job is present.
Runs that are still in progress are awaited; a failed run or a missing run fails the gate.
"""
import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Job-name prefixes that must be present and successful. Matrix jobs append their parameters in parentheses
# or after a comma, so these match by prefix. Removing a job from a workflow must fail the gate loudly.
REQUIRED = {
    'ci.yml': ['dependency-audit', 'lint', 'tests (3.11', 'tests (3.12', 'tests (3.14', 'container'],
    'python-install.yml': ['install (ubuntu-22.04', 'install (ubuntu-24.04-arm', 'install (windows-latest',
                           'install (macos-15-intel', 'install (macos-15', 'acceleration'],
}
# A step that must have succeeded somewhere in the run, so a gate cannot be satisfied by renaming it away.
REQUIRED_STEPS = {
    'ci.yml': ['Exercise real browser flows', 'Verify the authenticated HTTPS proxy',
               'Reject fixable high and critical image vulnerabilities'],
    'python-install.yml': ['Test native service and Python launcher', 'Verify the user-facing installer and repeat installation'],
}


def api(path, token):
    request = Request('https://api.github.com/' + path, headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def jobs_of(repo, run_id, token):
    jobs, page = [], 1
    while True:
        batch = api(f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}', token)['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def judge(workflow, jobs):
    """Return (state, reason) for one run's jobs: state is ok, wait or fail."""
    if not jobs:
        return 'wait', 'no jobs reported yet'
    if any(job['status'] != 'completed' for job in jobs):
        return 'wait', 'jobs still running'
    bad = [f"{job['name']}={job['conclusion']}" for job in jobs if job['conclusion'] != 'success']
    if bad:
        return 'fail', 'not successful: ' + ', '.join(bad)
    names = [job['name'] for job in jobs]
    for prefix in REQUIRED[workflow]:
        if not any(name.startswith(prefix) for name in names):
            return 'fail', f'required job missing: {prefix}'
    for step in REQUIRED_STEPS[workflow]:
        ok = any(item['name'] == step and item['conclusion'] == 'success' for job in jobs for item in job.get('steps', []))
        if not ok:
            return 'fail', f'required step did not succeed: {step}'
    return 'ok', f'{len(jobs)} jobs succeeded'


def check(repo, sha, workflow, token):
    path = f'.github/workflows/{workflow}'
    runs = api(f'repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&per_page=100', token)['workflow_runs']
    runs = [run for run in runs if run['head_sha'] == sha and run['path'] == path
            and run['head_repository']['full_name'] == repo]
    if not runs:
        return 'wait', f'no push run of {workflow} for {sha[:12]} yet', None
    results = []
    for run in sorted(runs, key=lambda item: item['id'], reverse=True):
        state, reason = judge(workflow, jobs_of(repo, run['id'], token))
        results.append((state, f"run {run['id']} ({run['head_branch']}): {reason}", run['html_url']))
        if state == 'ok':
            return 'ok', results[-1][1], run['html_url']
    for state, reason, url in results:
        if state == 'wait':
            return state, reason, url
    return 'fail', '; '.join(reason for _, reason, _ in results), results[0][2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--sha', required=True)
    parser.add_argument('--timeout', type=int, default=1800, help='seconds to wait for runs that are still going')
    parser.add_argument('--interval', type=int, default=20)
    arguments = parser.parse_args()
    token = os.environ['GH_TOKEN']
    deadline = time.monotonic() + arguments.timeout
    pending = set(REQUIRED)
    while True:
        for workflow in sorted(pending):
            try:
                state, reason, url = check(arguments.repo, arguments.sha, workflow, token)
            except HTTPError as error:
                state, reason, url = 'wait', f'GitHub API returned {error.code}', None
            print(f'{workflow}: {state}: {reason} {url or ""}', flush=True)
            if state == 'fail':
                sys.exit(f'Gate failed for {workflow} at {arguments.sha}. Fix and rerun CI before publishing.')
            if state == 'ok':
                pending.discard(workflow)
        if not pending:
            print(f'All required checks passed for {arguments.sha}')
            return
        if time.monotonic() > deadline:
            sys.exit('Timed out waiting for required checks: ' + ', '.join(sorted(pending)))
        time.sleep(arguments.interval)


if __name__ == '__main__':
    main()
