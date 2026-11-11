"""Run the exact image a deploy will ship, as a container with the host's compose file, on a copy of a
cold backup of the host's app folder, before tools/deploy_host.sh may ship it.

  python3 tools/image_trial.py run --candidate <full sha> --backup <cold backup .tar.gz> --work <empty folder>
  python3 tools/image_trial.py check <full sha> <image tag>

The run builds the image the way tools/deploy_host.sh does and keeps it, so the deploy ships that very
image and never builds it again. It takes compose.yaml and the ./app folder from the backup. It never
extracts the backup's .env, auth.sqlite, cli.token or admin-initial-password.txt, and it reads no
environment from the host. The container runs the host's compose file unchanged, with an override that
puts it on an internal network with no route out, so it reaches no trade partner, notification service or
public name, and caps it at 12 CPUs, a CPU weight of 205 and 12 GB, as the sims slice caps the sims. Its
.env sets the image, PUBLIC_URL from the backup's manager.json, AUTH=accounts, a placeholder
AUTH_TRUSTED_PROXIES, the data folder and a free local port. It holds the heavy load gate throughout.

Known gaps against production: the trusted-proxy value is a placeholder, there is no reverse proxy, and it
boots in setup mode with no auth.sqlite. The session check right after the switch covers accounts mode.

It passes when, over at least 30 minutes:
- every adventure the backup wants running is running at every probe after a 5 minute boot,
- the container never restarts and its health check passes at every probe after the boot,
- the log has no line matching traceback, error, exception or critical, the rule the post-switch check
  reads the live log with, and no adventure restart or unhealthy line,
- the cable coordinator's summary lines show no failed pass, at least 3 passes that rated offers for Red,
  Blue or Yellow and at least 3 that rated offers for Gold, Silver or Crystal.
The report goes to LIVE_SOAK_REPORTS/image-trial/<sha>.json, by default data/live-soak/reports. The
container is removed at the end, and its log stays in the work folder beside the copied data.

`check` exits 0 and prints the sha256 of the trial's compose.yaml when a passing report under a day old
names the commit and the image id the tag has now. tools/deploy_host.sh runs it with no dependencies and
refuses the deploy when the host's compose.yaml has another sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'pokesim-trial'
MIN_SECONDS = 30 * 60
BOOT_SECONDS = 5 * 60
PROBE_SECONDS = 60
MIN_PASSES = 3
MAX_AGE_SECONDS = 24 * 3600
UP_TIMEOUT = 900
# Stands in for the reverse proxy's address, which the trial does not have. The app refuses a /0.
TRUSTED_PROXIES = '127.0.0.1/32'
# The caps of the sims slice, which Docker's own cgroups cannot join.
CAPS = {'cpus': 12, 'mem_limit': '12g', 'cpu_shares': 205}
# Docker settings this shell may hold. Nothing else reaches compose, so no shell setting changes the file.
DOCKER_ENV = ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONFIG', 'DOCKER_CONTEXT', 'XDG_RUNTIME_DIR')
# The rule the post-switch check reads the live log with.
ERROR = re.compile(r'traceback|error|exception|critical', re.IGNORECASE)
RESTART = re.compile(r'Adventure \S+ (?:restarts in \d+ seconds because|is unhealthy because)')
# pokesim.app.coordinator.SUMMARY, kept in step by tests/test_image_trial.py.
SUMMARY = re.compile(r'Automatic trading over (\d+) minutes: (\d+) passes, (\d+) failed, (\d+) rated Red, Blue or '
                     r'Yellow offers, (\d+) rated Gold, Silver or Crystal offers')
SECRETS = ('auth.sqlite', 'auth.sqlite-wal', 'auth.sqlite-shm', 'auth.sqlite-journal', 'cli.token',
           'admin-initial-password.txt')
# Runs in the candidate image as root, so the copy keeps the owner the container runs as. Arguments are
# the backup, the folder to fill and the names never extracted. It prints the public URL and how many
# adventures the copy wants running.
EXTRACT = '''
import json, sqlite3, sys, tarfile
backup, folder, secrets = sys.argv[1], sys.argv[2], set(sys.argv[3:])
def wanted(member):
    parts = member.name.removeprefix('./').split('/')
    if parts == ['compose.yaml']:
        return member.isfile()
    return parts[0] == 'app' and parts[-1] not in secrets
with tarfile.open(backup) as archive:
    archive.extractall(folder, members=[m for m in archive if wanted(m)], numeric_owner=True, filter='tar')
db = sqlite3.connect('file:' + folder + '/app/app.sqlite?mode=ro', uri=True)
wanted_running = db.execute("SELECT count(*) FROM adventures WHERE archived=0 AND desired_state='running'").fetchone()[0]
with open(folder + '/app/manager.json', encoding='utf-8') as stream:
    url = json.load(stream).get('url')
print(json.dumps({'url': url, 'wanted': wanted_running}))
'''
# Runs in the trial container. It prints how many adventures it wants running, how many run, and the
# exit code of the image's own health check.
PROBE = '''
import json, sqlite3, subprocess, sys
db = sqlite3.connect('file:/data/app.sqlite?mode=ro', uri=True)
rows = db.execute('SELECT desired_state, state FROM adventures WHERE archived=0').fetchall()
health = subprocess.run([sys.executable, '-m', 'pokesim.healthcheck', '--manager'], capture_output=True).returncode
print(json.dumps({'wanted': sum(d == 'running' for d, s in rows),
                  'running': sum(d == 'running' and s == 'running' for d, s in rows), 'health': health}))
'''


def soak_root():
    return Path(os.environ.get('LIVE_SOAK_ROOT') or ROOT / 'data' / 'live-soak')


def reports_dir():
    return Path(os.environ.get('LIVE_SOAK_REPORTS') or soak_root() / 'reports') / 'image-trial'


def git(*args, **kwargs):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True,
                          **kwargs).stdout


def image_tag(sha):
    """The tag tools/deploy_host.sh gives the commit's image, and the version and schema it builds with."""
    version = os.environ.get('VERSION') or re.search(r'(?m)^version = "(.*)"', git('show', f'{sha}:pyproject.toml'))[1]
    schema = re.search(r'(?m)^SCHEMA = (\d+)$', git('show', f'{sha}:pokesim/app/registry.py'))[1]
    return f'pokesim:{version}-local-{sha[:7]}', version, schema


def image_id(tag):
    done = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def build(sha, tag, version, schema):
    """Build the commit as tools/deploy_host.sh did before the trial took the build over, and return the image id."""
    with tempfile.TemporaryDirectory(prefix='image-trial-') as source:
        archive = subprocess.Popen(['git', '-C', str(ROOT), 'archive', sha], stdout=subprocess.PIPE)
        subprocess.run(['tar', 'x', '-C', source], stdin=archive.stdout, check=True)
        if archive.wait() != 0:
            raise SystemExit(f'image trial: git archive {sha[:7]} failed')
        subprocess.run(['docker', 'build', '-q', '--build-arg', f'VERSION={version}', '--build-arg', f'REVISION={sha}',
                        '--build-arg', f'SCHEMA={schema}', '-t', tag, source], check=True, stdout=subprocess.DEVNULL)
    return image_id(tag)


def extract(tag, backup, work):
    done = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
                           '-v', f'{backup.parent}:/in:ro', '-v', f'{work}:/w', tag, '-c', EXTRACT,
                           f'/in/{backup.name}', '/w', *SECRETS], check=True, capture_output=True, text=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def summaries(log):
    """The cable coordinator's summary lines, summed."""
    totals = {'lines': 0, 'passes': 0, 'failed': 0, 'gen1': 0, 'gen2': 0}
    for match in SUMMARY.finditer(log):
        totals['lines'] += 1
        for key, value in zip(('passes', 'failed', 'gen1', 'gen2'), match.groups()[1:]):
            totals[key] += int(value)
    return totals


def judge(probes, log, wanted, seconds):
    """The problems a finished trial shows, none when it passed. Each probe has its seconds since the start."""
    problems = []
    if seconds < MIN_SECONDS:
        problems.append(f'ran {seconds // 60} minutes, under {MIN_SECONDS // 60}')
    if wanted < 1:
        problems.append('the backup wants no adventure running')
    late = [probe for probe in probes if probe['seconds'] >= BOOT_SECONDS]
    if not late:
        problems.append('no probe after the boot')
    failed = [probe for probe in late if 'error' in probe]
    if failed:
        problems.append(f'{len(failed)} probes failed, first: {failed[0]["error"]}')
    short = [probe for probe in late if 'error' not in probe and (probe['wanted'] != wanted or probe['running'] != wanted)]
    if short:
        problems.append(f'{len(short)} probes saw under {wanted} adventures running, lowest '
                        f'{min(probe["running"] for probe in short)}')
    unhealthy = [probe for probe in late if 'error' not in probe and probe['health'] != 0]
    if unhealthy:
        problems.append(f'the health check failed at {len(unhealthy)} probes')
    restarts = max((probe.get('restarts', 0) for probe in probes), default=0)
    if restarts:
        problems.append(f'the container restarted {restarts} times')
    lines = log.splitlines()
    errors = [line for line in lines if ERROR.search(line)]
    if errors:
        problems.append(f'{len(errors)} error lines')
    restart_lines = [line for line in lines if RESTART.search(line)]
    if restart_lines:
        problems.append(f'{len(restart_lines)} adventure restart or unhealthy lines')
    totals = summaries(log)
    if not totals['lines']:
        problems.append('no trade summary line')
    if totals['failed']:
        problems.append(f'{totals["failed"]} trade scheduler passes failed')
    for key, games in (('gen1', 'Red, Blue or Yellow'), ('gen2', 'Gold, Silver or Crystal')):
        if totals[key] < MIN_PASSES:
            problems.append(f'{totals[key]} passes rated {games} offers, under {MIN_PASSES}')
    return problems, {'errors': errors[:20], 'restart_lines': restart_lines[:20], 'trades': totals}


def compose_command(trial):
    return ['docker', 'compose', '-p', PROJECT, '--project-directory', str(trial), '--env-file', str(trial / '.env'),
            '-f', str(trial / 'compose.yaml'), '-f', str(trial / 'trial.json')]


def probe(container):
    """One look at the container: its restart count and status, and the PROBE result or the error that stopped it."""
    look = {}
    inspect = subprocess.run(['docker', 'inspect', '--format', '{{.RestartCount}} {{.State.Status}}', container],
                             capture_output=True, text=True)
    if inspect.returncode != 0:
        return {'error': 'the container is gone'}
    restarts, status = inspect.stdout.split()
    look['restarts'] = int(restarts)
    if status != 'running':
        return {**look, 'error': f'the container is {status}'}
    done = subprocess.run(['docker', 'exec', container, 'python', '-c', PROBE], capture_output=True, text=True,
                          timeout=60)
    if done.returncode != 0:
        return {**look, 'error': (done.stderr.strip().splitlines() or ['the probe failed'])[-1][:200]}
    return {**look, **json.loads(done.stdout.strip().splitlines()[-1])}


def _under_heavy_gate(args):
    """Run this command again under the heavy load gate and return its exit code, or None once it holds the gate."""
    if os.environ.get('POKESIM_LOAD_GATE_HEAVY') == '1':
        return None
    command = ['sh', str(ROOT / 'tools' / 'load_gate.sh'), 'heavy', sys.executable, str(Path(__file__).resolve()),
               *args.argv]
    return subprocess.run(command, check=False).returncode


def run(args):
    gated = _under_heavy_gate(args)
    if gated is not None:
        return gated
    sha = git('rev-parse', '--verify', f'{args.candidate}^{{commit}}').strip()
    backup, work = args.backup.resolve(), args.work.resolve()
    if work.exists() and any(work.iterdir()):
        raise SystemExit(f'image trial: {work} is not empty')
    work.mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in DOCKER_ENV if key in os.environ}
    trial = work / 'trial'
    trial.mkdir()
    if subprocess.run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={PROJECT}'],
                      capture_output=True, text=True, env=env).stdout.strip():
        raise SystemExit(f'image trial: a {PROJECT} container is left from another trial, remove it with '
                         f'docker compose -p {PROJECT} down')
    tag, version, schema = image_tag(sha)
    print(f'image trial: building {tag}', file=sys.stderr)
    built = build(sha, tag, version, schema)
    print(f'image trial: copying ./app from {backup.name}', file=sys.stderr)
    copy = extract(tag, backup, work)
    compose = (work / 'compose.yaml').read_bytes()
    (trial / 'compose.yaml').write_bytes(compose)
    (trial / 'trial.json').write_text(json.dumps({
        'services': {'pokesim': {'networks': ['trial'], **CAPS}},
        'networks': {'trial': {'internal': True}},
    }, indent=2) + '\n', encoding='utf-8')
    (trial / '.env').write_text(''.join(f'{key}={value}\n' for key, value in (
        ('POKESIM_IMAGE', tag), ('PUBLIC_URL', copy['url']), ('AUTH', 'accounts'),
        ('AUTH_TRUSTED_PROXIES', TRUSTED_PROXIES), ('DATA_PATH', work / 'app'), ('BIND_ADDRESS', '127.0.0.1'),
        ('HTTP_PORT', free_port()))), encoding='utf-8')
    command = compose_command(trial)
    report = {'commit': sha, 'tag': tag, 'image_id': built, 'compose_sha256': hashlib.sha256(compose).hexdigest(),
              'backup': backup.name, 'wanted': copy['wanted'], 'started': time.time(), 'caps': CAPS,
              'trusted_proxies': TRUSTED_PROXIES}
    probes, log, seconds = [], '', 0
    print(f'image trial: starting {tag} on {copy["wanted"]} adventures for {args.minutes} minutes', file=sys.stderr)
    try:
        up = subprocess.run(command + ['up', '-d', '--wait', '--wait-timeout', str(UP_TIMEOUT)], env=env)
        container = subprocess.run(command + ['ps', '-aq', 'pokesim'], capture_output=True, text=True,
                                   env=env).stdout.strip()
        start = time.monotonic()
        if up.returncode != 0:
            probes.append({'seconds': 0, 'error': 'the container did not become healthy'})
        else:
            while (seconds := int(time.monotonic() - start)) < args.minutes * 60:
                time.sleep(min(PROBE_SECONDS, args.minutes * 60 - seconds))
                look = {'seconds': int(time.monotonic() - start), **probe(container)}
                probes.append(look)
                print(f'image trial: {look["seconds"] // 60} min {json.dumps(look)}', file=sys.stderr)
            seconds = int(time.monotonic() - start)
        if container:
            with (trial / 'container.log').open('w', encoding='utf-8') as stream:
                subprocess.run(['docker', 'logs', container], stdout=stream, stderr=subprocess.STDOUT)
            log = (trial / 'container.log').read_text(encoding='utf-8', errors='replace')
    finally:
        subprocess.run(command + ['down', '-t', '120'], env=env, check=False)
    problems, found = judge(probes, log, copy['wanted'], seconds)
    report.update({'finished': time.time(), 'seconds': seconds, 'probes': probes, **found, 'problems': problems,
                   'passed': not problems and built is not None and image_id(tag) == built})
    if built is None or image_id(tag) != built:
        report['problems'].append(f'{tag} changed during the trial')
    out = reports_dir() / f'{sha}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    trades = found['trades']
    print(f'image trial: {"passed" if report["passed"] else "failed"}, {seconds // 60} minutes, '
          f'{len(found["errors"])} error lines, {trades["passes"]} trade passes ({trades["gen1"]} rated Gen I, '
          f'{trades["gen2"]} rated Gen II, {trades["failed"]} failed), report {out}', file=sys.stderr)
    for problem in report['problems']:
        print(f'image trial:   {problem}', file=sys.stderr)
    return 0 if report['passed'] else 1


def check(args):
    path = reports_dir() / f'{args.sha}.json'
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        report = None
    short = args.sha[:7]
    if not isinstance(report, dict) or report.get('commit') != args.sha:
        print(f'image trial: no report for {short} in {path.parent}', file=sys.stderr)
        return 1
    if report.get('passed') is not True:
        print(f'image trial: the trial of {short} did not pass ({len(report.get("problems") or [])} problems), '
              f'see {path}', file=sys.stderr)
        return 1
    if time.time() - float(report.get('finished') or 0) > MAX_AGE_SECONDS:
        print(f'image trial: the trial of {short} is over a day old, run it again on a fresh cold backup',
              file=sys.stderr)
        return 1
    current = image_id(args.tag)
    if current is None or current != report.get('image_id'):
        print(f'image trial: {args.tag} is {current or "missing"}, not the image the trial of {short} ran',
              file=sys.stderr)
        return 1
    print(report['compose_sha256'])
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    running = commands.add_parser('run', help='play the image on a copy of a cold backup and write the report')
    running.add_argument('--candidate', required=True, help='the commit to build and deploy')
    running.add_argument('--backup', required=True, type=Path, help="a cold backup .tar.gz of the host's app folder")
    running.add_argument('--work', required=True, type=Path, help='an empty folder for the copy, kept afterwards')
    running.add_argument('--minutes', type=int, default=MIN_SECONDS // 60, help='how long to run, 30 to pass')
    checking = commands.add_parser('check', help='exit 0 and print the compose sha256 when a fresh trial passed')
    checking.add_argument('sha')
    checking.add_argument('tag')
    args = parser.parse_args(argv)
    args.argv = argv
    return run(args) if args.command == 'run' else check(args)


if __name__ == '__main__':
    sys.exit(main())
