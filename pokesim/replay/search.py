"""Record a rung at a commit, and bisect a rung's regression across merged pull requests.

A recorded run is the gate's run of one rung, played by the commit's own ``gate-rung`` in the
commit's own environment, with a trace recorder attached by ``shim.py``. Runs are kept under
``<out>/<ladder>-<rung>/<sha12>[-pyboy-own]/<n>/`` and a finished one is used again.

A bisect first records each end twice. The two traces of one end must have the same head, or
the rung does not replay the same way twice and nothing after that could be trusted. It then
tests the suspect pull requests in merge order, several at once, and finds the first bad one.
When that commit's parent is bad too, the cause sits in a commit between the last good suspect
and that parent, and those commits are searched in turn.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import diverge
from .envs import CURRENT, DEFAULT_CACHE, OWN, ROOT, environment, git, python, resolve, tree
from .rung import GATE_FRAMES, GATE_QUIET, GATE_WASTE_POINTS

SHIM = Path(__file__).with_name('shim.py')
RUN_TIMEOUT = 3600
# Variables that pick a cartridge, a share code or partners, or another environment. The rung sets its own.
DROPPED = ('RANDOMIZER', 'ROM_PATH', 'POKESIM_GEN1_VARIANT', 'AUDIT_PARTNERS', 'VIRTUAL_ENV', 'PYTHONPATH',
           'PYTHONHOME')
WASTE, STALL, BOTH = 'waste', 'stall', 'both'
PULL = re.compile(r'\(#(\d+)\)\s*$')


@dataclass
class Options:
    roms: Path
    ladders: Path = ROOT / 'data' / 'ladder'
    data_root: Path | None = None
    # The data folder the gate reads from the checkout it runs in, such as Gen I game data.
    data_dir: Path = ROOT / 'data'
    cache: Path = DEFAULT_CACHE
    out: Path = ROOT / 'data' / 'ladder' / 'replay'
    frames: int = GATE_FRAMES
    pyboy: str = CURRENT
    root: Path = ROOT
    log: object = print


@dataclass
class Run:
    commit: str
    folder: Path
    shim: dict | None = None
    summary: dict | None = None
    replay: dict = field(default_factory=dict)

    @property
    def ok(self):
        return bool(self.shim and self.shim.get('code') == 0 and self.shim.get('attached') and self.summary)

    @property
    def head(self):
        return (self.shim or {}).get('head')

    @property
    def waste(self):
        return (self.summary or {}).get('waste')

    @property
    def stall(self):
        return (self.summary or {}).get('stall')

    def brief(self):
        return {'commit': self.commit, 'folder': str(self.folder), 'ok': self.ok, 'head': self.head,
                'waste': self.waste, 'stall': self.stall, 'pyboy': self.replay.get('pyboy'),
                'seconds': self.replay.get('seconds')}


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _split(rung):
    ladder, _, name = rung.partition('/')
    if not ladder or not name or '/' in name:
        raise ValueError(f'name a rung as LADDER/RUNG, such as silver/badges_6, not {rung}')
    return ladder, name


def run_folder(options, rung, sha, pyboy, n):
    ladder, name = _split(rung)
    suffix = '' if pyboy == CURRENT else f'-pyboy-{pyboy}'
    return Path(options.out) / f'{ladder}-{name}' / f'{sha[:12]}{suffix}' / str(n)


def load(folder, sha):
    folder = Path(folder)
    return Run(sha, folder, _json(folder / 'shim.json'), _json(folder / 'summary.json'),
               _json(folder / 'replay.json') or {})


def _trace_module():
    return importlib.util.find_spec('pokecore.trace').origin


def record(options, rung, sha, n=1, pyboy=None):
    """Play ``rung`` at commit ``sha`` with a recorder attached. Returns the Run, a finished one if kept."""
    pyboy = pyboy or options.pyboy
    if pyboy not in (CURRENT, OWN):
        raise ValueError(f'pyboy is {CURRENT} or {OWN}, not {pyboy}')
    folder = run_folder(options, rung, sha, pyboy, n)
    kept = load(folder, sha)
    if kept.ok:
        return kept
    ladder, name = _split(rung)
    ladder_folder = Path(options.ladders) / ladder
    info = json.loads((ladder_folder / 'ladder.json').read_text(encoding='utf-8'))
    if not (ladder_folder / name / 'start.state').exists():
        raise FileNotFoundError(f'{rung} has no start state in {options.ladders}')
    checkout = tree(sha, options.cache, options.root)
    env, version = environment(sha, checkout, pyboy, options.cache, options.root, log=options.log)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    fields = {'commit': sha, 'rung': rung, 'pyboy': pyboy, 'seed': 7, 'generation': info.get('generation')}
    command = ['nice', '-n', '10', str(python(env)), str(SHIM), _trace_module(), str(folder), json.dumps(fields),
               str(checkout / 'tools' / 'stage_ladder.py'), '--', 'gate-rung', str(ladder_folder), name, str(folder),
               str(options.roms), '--frames', str(options.frames), '--quiet', str(GATE_QUIET),
               '--battle-minutes', str(GATE_QUIET)]
    variables = {key: value for key, value in os.environ.items() if key not in DROPPED}
    # The hash seed fixes set and dict orders that depend on string hashes, so two runs replay alike.
    variables.update(PYTHONPATH=str(checkout), PYTHONHASHSEED='0', DATA_DIR=str(Path(options.data_dir).resolve()))
    if options.data_root:
        command += ['--data-root', str(options.data_root)]
        variables['GEN2_DATA_DIR'] = str(options.data_root)
    options.log(f'recording {rung} at {sha[:12]} with pyboy-rs {version}, run {n}')
    started = time.monotonic()
    with open(folder / 'log.txt', 'wb') as log:
        try:
            code = subprocess.run(command, cwd=checkout, env=variables, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=RUN_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    replay = {'commit': sha, 'rung': rung, 'pyboy_choice': pyboy, 'pyboy': version, 'run': n, 'exit': code,
              'seconds': round(time.monotonic() - started, 1), 'frames': options.frames}
    (folder / 'replay.json').write_text(json.dumps(replay, indent=1) + '\n', encoding='utf-8')
    return load(folder, sha)


def suspects(good, bad, numbers, root=ROOT):
    """The first-parent commits after ``good`` up to ``bad`` that merged one of pull requests ``numbers``,
    as (pull request, commit) in merge order."""
    wanted = {int(number) for number in numbers}
    out = []
    for line in git('log', '--first-parent', '--reverse', '--format=%H%x09%s', f'{good}..{bad}', root=root).splitlines():
        sha, _, subject = line.partition('\t')
        found = PULL.search(subject)
        if found and int(found.group(1)) in wanted:
            out.append((int(found.group(1)), sha))
    return out


def first_parent_range(after, upto, root=ROOT):
    """The first-parent commits after ``after`` up to and with ``upto``, oldest first."""
    lines = git('log', '--first-parent', '--reverse', '--format=%H', f'{after}..{upto}', root=root).splitlines()
    return [line for line in lines if line]


def _probes(lo, hi, jobs):
    count = min(jobs, hi - lo - 1)
    points = sorted({lo + max(1, round((k + 1) * (hi - lo) / (count + 1))) for k in range(count)})
    return [point for point in points if lo < point < hi]


def first_bad(items, is_bad, jobs=1, pool=None):
    """The index of the first bad item, when the item before the first is good and the last is bad.

    Each round tests up to ``jobs`` items spread evenly over the open range, at once. Returns
    (index, results, inversions) where results maps index to bad and inversions lists good
    results found after a bad one, which mean the regression comes and goes.
    """
    lo, hi = -1, len(items) - 1
    results, inversions = {}, []
    while hi - lo > 1:
        points = _probes(lo, hi, jobs)
        if pool is None:
            found = [is_bad(items[point]) for point in points]
        else:
            found = list(pool.map(lambda point: is_bad(items[point]), points))
        results.update(zip(points, found))
        bad = [point for point, verdict in zip(points, found) if verdict]
        new_hi = bad[0] if bad else hi
        good = [point for point, verdict in zip(points, found) if not verdict and point < new_hi]
        inversions += [point for point, verdict in zip(points, found) if not verdict and point > new_hi]
        lo, hi = (good[-1] if good else lo), new_hi
    return hi, results, inversions


def twice(first, second):
    """Whether two runs of one commit played the same way, with why.

    The same head passes. So do two traces whose records differ only in the time their clock
    inputs read, since commits before the frame clock work read the wall clock in Gen II.
    """
    out = {'same_head': first.ok and second.ok and first.head == second.head}
    if out['same_head']:
        return out | {'same': True, 'reason': 'same head'}
    if not (first.ok and second.ok):
        return out | {'same': False, 'reason': 'a run failed'}
    out['diverge'] = diverge.compare(first.folder, second.folder)
    if out['diverge']['clock_only']:
        return out | {'same': True, 'reason': 'only wall-clock readings differ'}
    return out | {'same': False, 'reason': 'heads differ'}


def predicate(kind, base, stall_key=None, points=GATE_WASTE_POINTS):
    """Whether a run is bad against the good end's run ``base``. A failed run is bad under each kind."""
    if kind == WASTE:
        return lambda run: not run.ok or run.waste - base.waste > points
    if kind == STALL:
        if stall_key:
            return lambda run: not run.ok or stall_key in ((run.stall or {}).get('reason') or '')
        return lambda run: not run.ok or (bool(run.stall) and not base.stall)
    raise ValueError(f'a predicate is {WASTE} or {STALL}, not {kind}')


class Bisect:
    """One rung's search between a good and a bad commit. Runs are shared across predicates."""

    def __init__(self, options, rung, good, bad, numbers, jobs=4, stall_key=None, points=GATE_WASTE_POINTS):
        self.options, self.rung, self.jobs = options, rung, jobs
        self.good, self.bad = resolve(good, options.root), resolve(bad, options.root)
        self.numbers, self.stall_key, self.points = list(numbers), stall_key, points
        self.runs = {}
        self.pool = ThreadPoolExecutor(max_workers=max(1, jobs))

    def run(self, sha, n=1):
        key = (sha, n)
        if key not in self.runs:
            self.runs[key] = record(self.options, self.rung, sha, n)
        return self.runs[key]

    def self_check(self):
        """Record each end twice. Returns (passed, details)."""
        pairs = [(sha, n) for sha in (self.good, self.bad) for n in (1, 2)]
        list(self.pool.map(lambda pair: self.run(*pair), pairs))
        details = {}
        passed = True
        for name, sha in (('good', self.good), ('bad', self.bad)):
            first, second = self.run(sha, 1), self.run(sha, 2)
            details[name] = {'commit': sha, 'runs': [first.brief(), second.brief()]} | twice(first, second)
            passed = passed and details[name]['same']
        return passed, details

    def search(self, kind):
        """The first bad commit under predicate ``kind``, with how it was found."""
        base, worst = self.run(self.good), self.run(self.bad)
        is_bad = predicate(kind, base, self.stall_key, self.points)
        found = {'predicate': kind, 'good': base.brief(), 'bad': worst.brief()}
        if not base.ok:
            return found | {'stopped': 'the good end failed to run'}
        if is_bad(base):
            return found | {'stopped': 'the good end is already bad under this predicate'}
        if not is_bad(worst):
            return found | {'stopped': 'the bad end is not bad under this predicate'}
        listed = suspects(self.good, self.bad, self.numbers, self.options.root)
        items = [sha for _, sha in listed]
        if not items or items[-1] != self.bad:
            items.append(self.bad)
        names = {sha: number for number, sha in listed}

        def test(sha):
            return is_bad(self.run(sha))

        index, results, inversions = first_bad(items, test, self.jobs, self.pool)
        found['suspects'] = [{'pull': names.get(sha), 'commit': sha, 'bad': results.get(i)}
                             for i, sha in enumerate(items)]
        found['inversions'] = [items[i] for i in inversions]
        culprit = items[index]
        parent = resolve(f'{culprit}^1', self.options.root)
        last_good = items[index - 1] if index else self.good
        found['parent'] = {'commit': parent, 'bad': None}
        if parent == last_good:
            found['parent']['bad'] = False
        else:
            found['parent']['bad'] = test(parent)
        if found['parent']['bad']:
            # The cause came in a commit that is not a suspect. Search those, between the last good item and the parent.
            between = first_parent_range(last_good, parent, self.options.root)
            index, results, more = first_bad(between, test, self.jobs, self.pool)
            found['between'] = [{'commit': sha, 'bad': results.get(i)} for i, sha in enumerate(between)]
            found['inversions'] += [between[i] for i in more]
            culprit = between[index]
            parent = resolve(f'{culprit}^1', self.options.root)
        found['first_bad'] = {'commit': culprit, 'pull': names.get(culprit),
                              'subject': git('log', '-1', '--format=%s', culprit, root=self.options.root),
                              'run': self.run(culprit).brief()}
        before = self.run(parent)
        found['before'] = before.brief()
        if before.ok and self.run(culprit).ok:
            found['diverge'] = diverge.compare(before.folder, self.run(culprit).folder)
        return found

    def close(self):
        self.pool.shutdown(wait=True)


def bisect(options, rung, good, bad, numbers, kinds, jobs=4, stall_key=None, self_check=True,
           points=GATE_WASTE_POINTS):
    """The bisect report of ``rung``: the self check and one search per predicate in ``kinds``."""
    search = Bisect(options, rung, good, bad, numbers, jobs, stall_key, points)
    try:
        report = {'rung': rung, 'good': search.good, 'bad': search.bad, 'pyboy': options.pyboy,
                  'frames': options.frames, 'stall_key': stall_key, 'points': points, 'searches': []}
        baseline = _json(Path(options.root) / 'tools' / 'ladder' / 'gate-baseline.json') or {}
        report['gate_baseline'] = (baseline.get('rungs') or {}).get(rung)
        if self_check:
            passed, report['self_check'] = search.self_check()
            if not passed:
                report['stopped'] = 'an end did not replay the same way twice'
                return report
        for kind in kinds:
            report['searches'].append(search.search(kind))
        return report
    finally:
        search.close()


def _run_line(name, brief):
    if not brief:
        return f'- {name}: no run.'
    stall = brief['stall']['reason'] if brief.get('stall') else 'none'
    state = 'ran' if brief['ok'] else 'failed'
    return f'- {name}: {brief["commit"][:12]} {state}, {brief["waste"]}% wasted, stall {stall}.'


def _check_line(check):
    if check.get('same_head'):
        return 'same head twice'
    if check.get('same'):
        count = check['diverge']['clock_readings']
        return f'same play twice, only wall-clock readings differ in {count} clock inputs'
    return check.get('reason') or 'heads differ'


def markdown(report):
    lines = [f'# Bisect {report["rung"]}', '',
             f'- Good {report["good"][:12]}, bad {report["bad"][:12]}, pyboy-rs held at {report["pyboy"]}, '
             f'{report["frames"]} frames per run.']
    if report.get('gate_baseline'):
        base = report['gate_baseline']
        lines.append(f'- Gate baseline: {base.get("waste")}% wasted, stall {"yes" if base.get("stall") else "none"}.')
    check = report.get('self_check')
    if check:
        for name in ('good', 'bad'):
            lines.append(f'- Self check, {name} end: {_check_line(check[name])}.')
    if report.get('stopped'):
        lines.append(f'- Stopped: {report["stopped"]}.')
        for name in ('good', 'bad'):
            if check and 'diverge' in check[name] and not check[name].get('same'):
                lines += ['', diverge.markdown(check[name]['diverge'], f'The {name} end against itself')]
        return '\n'.join(lines) + '\n'
    for found in report['searches']:
        lines += ['', f'## Predicate {found["predicate"]}', '', _run_line('Good end', found['good']),
                  _run_line('Bad end', found['bad'])]
        if found.get('stopped'):
            lines.append(f'- Stopped: {found["stopped"]}.')
            continue
        tested = ', '.join(f'#{item["pull"]} {"bad" if item["bad"] else "good"}'
                           for item in found['suspects'] if item['bad'] is not None and item['pull'])
        lines.append(f'- Suspects tested: {tested or "none"}.')
        first = found['first_bad']
        name = f'#{first["pull"]}' if first['pull'] else 'a commit outside the suspects'
        lines.append(f'- First bad: {name}, {first["commit"][:12]} {first["subject"]}.')
        lines.append(_run_line('Its parent', found['before']))
        if found['inversions']:
            lines.append(f'- Good after bad at: {", ".join(sha[:12] for sha in found["inversions"])}. '
                         'The regression comes and goes, so read the first bad with care.')
        if found.get('diverge'):
            lines += ['', diverge.markdown(found['diverge'], f'First bad against its parent, {found["predicate"]}')]
    return '\n'.join(lines) + '\n'
