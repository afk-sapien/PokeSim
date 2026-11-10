"""``python -m pokesim.replay``: record a rung at a commit, compare two runs, bisect a regression.

    python -m pokesim.replay record --rung silver/badges_6 --at main --roms ROMS [--twice]
    python -m pokesim.replay diverge A B --rung silver/badges_6 --roms ROMS [--a-pyboy own]
    python -m pokesim.replay bisect --rung silver/badges_6 --good A --bad B --suspects 344,346 --roms ROMS

Each run plays the rung as the ladder gate does, with the commit's own code and lock, and keeps
its trace. pyboy-rs is held at the running checkout's version unless ``--pyboy own`` asks for
each commit's own. Reports go beside the runs as JSON and Markdown.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import diverge
from .envs import CURRENT, DEFAULT_CACHE, OWN, ROOT, resolve
from .rung import GATE_FRAMES, GATE_WASTE_POINTS
from .search import BOTH, STALL, WASTE, Options, bisect, markdown, record


def _options(args):
    data_root = args.data_root
    if data_root is None and os.environ.get('GEN2_DATA_DIR'):
        data_root = Path(os.environ['GEN2_DATA_DIR'])
    data_dir = args.data_dir or Path(os.environ.get('DATA_DIR') or ROOT / 'data')
    return Options(roms=args.roms, ladders=args.ladders or data_dir / 'ladder', data_root=data_root, data_dir=data_dir,
                   cache=args.cache, out=args.out or data_dir / 'ladder' / 'replay', frames=args.frames, pyboy=args.pyboy)


def _folder(options, rung):
    ladder, _, name = rung.partition('/')
    return Path(options.out) / f'{ladder}-{name}'


def _write(base, report, text):
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix('.json').write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    base.with_suffix('.md').write_text(text, encoding='utf-8')
    print(text, end='')
    print(f'Written to {base.with_suffix(".md")}')


def cmd_record(args):
    options = _options(args)
    sha = resolve(args.at)
    runs = [record(options, args.rung, sha, n) for n in ((1, 2) if args.twice else (1,))]
    for run in runs:
        print(json.dumps(run.brief()))
    if not all(run.ok for run in runs):
        print('a run failed, see log.txt in its folder', file=sys.stderr)
        return 1
    if args.twice:
        same = runs[0].head == runs[1].head
        print(f'Same head twice: {"yes" if same else "no"}')
        if not same:
            report = diverge.compare(runs[0].folder, runs[1].folder)
            _write(_folder(options, args.rung) / f'self-{sha[:12]}', report,
                   diverge.markdown(report, f'{args.rung} at {sha[:12]} against itself'))
            return 1
    return 0


def cmd_diverge(args):
    options = _options(args)
    a, b = resolve(args.a), resolve(args.b)
    a_pyboy = args.a_pyboy or options.pyboy
    first, second = record(options, args.rung, a, pyboy=a_pyboy), record(options, args.rung, b)
    for run in (first, second):
        if not run.ok:
            print(f'the run at {run.commit[:12]} failed, see {run.folder / "log.txt"}', file=sys.stderr)
            return 2
    report = diverge.compare(first.folder, second.folder)
    label = f'{a[:12]}' + ('' if a_pyboy == options.pyboy else f'-pyboy-{a_pyboy}')
    _write(_folder(options, args.rung) / f'diverge-{label}-{b[:12]}', report,
           diverge.markdown(report, f'{args.rung}: {label} against {b[:12]}'))
    return 0


def cmd_bisect(args):
    options = _options(args)
    numbers = [int(item) for item in args.suspects.replace('#', '').split(',') if item.strip()]
    kinds = [WASTE, STALL] if args.predicate == BOTH else [args.predicate]
    report = bisect(options, args.rung, args.good, args.bad, numbers, kinds, args.jobs, args.stall_key,
                    not args.no_self_check, args.waste_points)
    _write(_folder(options, args.rung) / f'bisect-{report["good"][:12]}-{report["bad"][:12]}', report,
           markdown(report))
    return 2 if report.get('stopped') else 0


def parse(argv=None):
    parser = argparse.ArgumentParser(prog='python -m pokesim.replay', description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--rung', required=True, help='LADDER/RUNG, such as silver/badges_6')
    common.add_argument('--roms', type=Path, required=True, help='a folder holding the clean cartridges')
    common.add_argument('--data-dir', type=Path, help='the data folder with Gen I game data, by default DATA_DIR or data')
    common.add_argument('--ladders', type=Path, help='the ladders folder, by default ladder in the data folder')
    common.add_argument('--data-root', type=Path, help='Gen II game data, by default GEN2_DATA_DIR')
    common.add_argument('--cache', type=Path, default=DEFAULT_CACHE, help='where checkouts and environments go')
    common.add_argument('--out', type=Path, help='where runs go, by default ladder/replay in the data folder')
    common.add_argument('--frames', type=int, default=GATE_FRAMES, help='frames to play from the rung')
    common.add_argument('--pyboy', choices=(CURRENT, OWN), default=CURRENT,
                        help="pyboy-rs for every commit: this checkout's (current) or each commit's own")
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('record', parents=[common], help='play the rung at one commit')
    one.add_argument('--at', required=True, help='a commit or ref')
    one.add_argument('--twice', action='store_true', help='play it twice and check both traces match')
    one.set_defaults(action=cmd_record)
    two = commands.add_parser('diverge', parents=[common], help='where two commits part on the rung')
    two.add_argument('a')
    two.add_argument('b')
    two.add_argument('--a-pyboy', choices=(CURRENT, OWN), help='pyboy-rs for A alone, such as its own')
    two.set_defaults(action=cmd_diverge)
    search = commands.add_parser('bisect', parents=[common], help='the first bad pull request on the rung')
    search.add_argument('--good', required=True)
    search.add_argument('--bad', required=True)
    search.add_argument('--suspects', required=True, help='pull request numbers, such as 344,346')
    search.add_argument('--jobs', type=int, default=4, help='runs at once')
    search.add_argument('--predicate', choices=(WASTE, STALL, BOTH), default=WASTE)
    search.add_argument('--stall-key', help='a run is bad when its stall reason has this text')
    search.add_argument('--waste-points', type=float, default=GATE_WASTE_POINTS,
                        help='wasted share points over the good end that make a run bad')
    search.add_argument('--no-self-check', action='store_true', help='skip recording each end twice')
    search.set_defaults(action=cmd_bisect)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    return args.action(args)


if __name__ == '__main__':
    raise SystemExit(main())
