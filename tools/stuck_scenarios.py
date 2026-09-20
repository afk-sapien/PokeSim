"""Keep and replay stuck scenarios: saved moments the player once could not get out of.

  add   copy a checkpoint (or a stall bundle's before.state) into a scenario folder, with edits
  run   replay every scenario in parallel and report which ones still get stuck
  show  describe the party, bag and place a checkpoint holds, after the scenario's edits

Scenario folders hold private game data and must stay outside the checkout or under data/.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokesim.headless import HeadlessRun
from pokesim.ram import ITEM_NAMES, read_snapshot
from pokesim.scenarios import STATUS, Scenario, apply_edits, discover, play

DEFAULT_ROOT = ROOT / 'data' / 'scenarios'


def private(path):
    path = path.resolve()
    return not path.is_relative_to(ROOT) or path.is_relative_to(ROOT / 'data')


def parse_party(values):
    """slot:key=value,key=value, for example 0:status=frozen,hp=12 or all:pp=0."""
    changes = []
    for value in values or ():
        slot, _, fields = value.partition(':')
        change = {'slot': 'all' if slot == 'all' else int(slot)}
        for pair in fields.split(','):
            key, _, raw = pair.partition('=')
            if key == 'status':
                if raw not in STATUS:
                    raise SystemExit(f'Unknown status {raw}. Choose from {", ".join(STATUS)}.')
                change[key] = raw
            elif key == 'hp':
                change[key] = float(raw) if '.' in raw else int(raw)
            elif key == 'pp':
                change[key] = int(raw)
            else:
                raise SystemExit(f'Unknown party field {key}. Use status, hp or pp.')
        changes.append(change)
    return changes


def add(args):
    folder = args.root / args.name
    if not private(folder):
        raise SystemExit('Scenarios contain private game data. Choose a folder outside the checkout or under data/.')
    source = args.checkpoint / 'before.state' if args.checkpoint.is_dir() else args.checkpoint
    if not source.with_suffix('.json').exists():
        raise SystemExit(f'{source} has no manifest beside it')
    folder.mkdir(parents=True, exist_ok=args.force)
    for suffix in ('.state', '.json'):
        shutil.copyfile(source.with_suffix(suffix), folder / f'start{suffix}')
    edits = {}
    if args.party:
        edits['party'] = parse_party(args.party)
    if args.item:
        edits['items'] = {name: int(quantity) for name, _, quantity in (value.partition('=') for value in args.item)}
    if args.money is not None:
        edits['money'] = args.money
    scenario = {'name': args.name, 'description': args.description, 'checkpoint': 'start.state', 'edits': edits,
                'budget_game_minutes': args.budget, 'max_quiet_game_minutes': args.quiet, 'seed': args.seed}
    if args.until:
        scenario['until'] = args.until
    if args.fallback:
        for suffix in ('.state', '.json'):
            shutil.copyfile(args.fallback.with_suffix(suffix), folder / f'fallback{suffix}')
        scenario['fallback'] = 'fallback.state'
    (folder / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n')
    print(f'wrote {folder}')
    show(argparse.Namespace(rom=args.rom, scenario=folder))


def show(args):
    scenario = Scenario.load(args.scenario)
    run = HeadlessRun(args.rom, scenario.checkpoint, scenario.seed)
    try:
        apply_edits(run.pb.memory, scenario.edits)
        snapshot = read_snapshot(run.pb.memory, run.frame)
        print(f'{scenario.name}: {snapshot.map_name} ({snapshot.x}, {snapshot.y}), '
              f'{bin(snapshot.badges).count("1")} badges, ${snapshot.money}, '
              f'{"in battle" if snapshot.in_battle else "in the field"}, goal "{run.policy.goal.title}"')
        for mon in snapshot.party:
            print(f'  {mon.name:<11} L{mon.level:<3} {mon.hp}/{mon.max_hp} status {mon.status} pp {list(mon.pp)}')
        print('  bag: ' + ', '.join(f'{ITEM_NAMES.get(item, item)} x{count}' for item, count in snapshot.items))
    finally:
        run.stop()


def _play(folder, rom):
    started = time.monotonic()
    result = play(Scenario.load(folder), rom)
    return {**result, 'wall_seconds': round(time.monotonic() - started)}


def run(args):
    scenarios = [s for s in discover(args.root) if not args.only or any(word in s.name for word in args.only)]
    if not scenarios:
        raise SystemExit(f'No scenarios under {args.root}')
    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        jobs = {pool.submit(_play, scenario.folder, args.rom): scenario for scenario in scenarios}
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            verdict = 'ok   ' if result['passed'] else 'STUCK'
            print(f'{verdict} {result["name"]:<44} {result["game_minutes"]:>4}m played, quiet {result["worst_quiet_minutes"]:>3}m, '
                  f'{result["reloads"]} reloads, {result["wall_seconds"]}s'
                  + ('' if result['passed'] else f'\n      {result["failure"]} on {result["final_map"]}: '
                                                 f'{result["objective"]} ({result["reason"]})'), flush=True)
    results.sort(key=lambda row: row['name'])
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + '\n')
    stuck = [row['name'] for row in results if not row['passed']]
    print(f'{len(results) - len(stuck)} of {len(results)} scenarios got going again')
    return 1 if stuck else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rom', type=Path, default=Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb')))
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('POKESIM_SCENARIOS', DEFAULT_ROOT)))
    commands = parser.add_subparsers(dest='command', required=True)
    adding = commands.add_parser('add', help='keep a checkpoint as a scenario')
    adding.add_argument('name')
    adding.add_argument('checkpoint', type=Path, help='a .state file with its manifest, or a stall bundle folder')
    adding.add_argument('--description', default='')
    adding.add_argument('--party', action='append', help='slot:status=frozen,hp=12,pp=0 (slot may be all)')
    adding.add_argument('--item', action='append', help='FULL_HEAL=0 removes an item, REVIVE=3 sets its quantity')
    adding.add_argument('--money', type=int)
    adding.add_argument('--until', help='an event type that must happen, such as badge, trainer or champion')
    adding.add_argument('--fallback', type=Path, help='unedited save the second reload goes to, such as league-entry.state')
    adding.add_argument('--budget', type=int, default=240, help='game minutes to play')
    adding.add_argument('--quiet', type=int, default=90, help='game minutes without an achievement that count as stuck')
    adding.add_argument('--seed', type=int, default=7)
    adding.add_argument('--force', action='store_true', help='replace an existing scenario')
    adding.set_defaults(action=add)
    showing = commands.add_parser('show', help='describe a scenario after its edits')
    showing.add_argument('scenario', type=Path)
    showing.set_defaults(action=show)
    running = commands.add_parser('run', help='replay the scenarios')
    running.add_argument('only', nargs='*', help='run scenarios whose name contains one of these words')
    running.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    running.add_argument('--output', type=Path, help='write the full results as JSON')
    running.set_defaults(action=run)
    args = parser.parse_args()
    return args.action(args)


if __name__ == '__main__':
    raise SystemExit(main())
