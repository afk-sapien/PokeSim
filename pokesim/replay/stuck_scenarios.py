"""Replay stuck scenarios: saved moments the player once could not get out of.

  run   replay every scenario in parallel and report which ones still get stuck
  show  describe the party, bag and place a checkpoint holds, after the scenario's edits

python -m pokesim.replay capture keeps a stall bundle or a checkpoint as a scenario, with edits, and
lists it in scenarios/index.toml.

Red, Blue, Yellow, Gold, Silver and Crystal checkpoints all replay, each on the cartridge its manifest
names. The party and money edits work in all six games, and so does taking a species out of the Pokédex
(unowned). Red, Blue and Yellow scenarios can also edit the bag (items), hold the first badges (badges),
set story events by name (events) and name the legendaries that have come back (returned). Gold, Silver and Crystal scenarios can also run the clock forward
(clock), fill every box (boxes) and offer the Battle Tower again (tower), which scenario.json names, as
pokesim/scenarios.py describes.

Scenario folders hold private game data and must stay outside the checkout or under data/.
"""
import argparse
from functools import partial
import json
import os
from pathlib import Path
import time

from pokesim.replay.rung import PIPELINE_BAR, agreement, share

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'data' / 'scenarios'


# pokesim.ram and pokesim.scenarios read the game data as they load, so each command imports them
# when it runs and --help works on a machine without game data.

def show(args):
    from pokesim.ram import ITEM_NAMES, read_snapshot
    from pokesim.scenarios import Scenario, open_run
    scenario = Scenario.load(args.scenario)
    run, _ = open_run(scenario, args.rom)
    try:
        if run.generation == 2:
            snapshot = run.read()
            items = ', '.join(f'{run.data.item_names.get(item, item)} x{count}' for item, count in snapshot.items)
        else:
            snapshot = read_snapshot(run.pb.memory, run.frame)
            items = ', '.join(f'{ITEM_NAMES.get(item, item)} x{count}' for item, count in snapshot.items)
        goal = getattr(run.policy, 'goal', None)
        print(f'{scenario.name}: {snapshot.map_name} ({snapshot.x}, {snapshot.y}), '
              f'{bin(snapshot.badges).count("1")} badges, ${snapshot.money}, '
              f'{"in battle" if snapshot.in_battle else "in the field"}'
              + (f', goal "{goal.title}"' if goal else ''))
        for mon in snapshot.party:
            print(f'  {mon.name:<11} L{mon.level:<3} {mon.hp}/{mon.max_hp} status {mon.status} pp {list(mon.pp)}')
        print('  bag: ' + items)
    finally:
        run.stop()


def _play(folder, rom):
    from pokesim.scenarios import Scenario, play
    started = time.monotonic()
    result = play(Scenario.load(folder), rom)
    return {**result, 'wall_seconds': round(time.monotonic() - started)}


def run(args):
    from pokesim.scenarios import WorkerDied, discover, replay_all
    scenarios = [s for s in discover(args.root) if not args.only or any(word in s.name for word in args.only)]
    if not scenarios:
        raise SystemExit(f'No scenarios under {args.root}')
    names = {scenario.folder: scenario.name for scenario in scenarios}
    results = []

    def retrying(folders):
        print(f'RETRY a replay worker died during {", ".join(names[folder] for folder in folders)}, '
              f'playing them once more in a fresh pool', flush=True)

    for folder, result in replay_all(partial(_play, rom=args.rom), list(names), args.jobs, retrying):
        if isinstance(result, Exception):
            # A scenario that raises, or whose worker died twice, fails alone and the run goes on.
            label = 'DIED ' if isinstance(result, WorkerDied) else 'ERROR'
            results.append({'name': names[folder], 'passed': False, 'error': f'{type(result).__name__}: {result}'})
            print(f'{label} {names[folder]:<44}\n      {type(result).__name__}: {str(result)[-1000:]}', flush=True)
            continue
        results.append(result)
        verdict = 'ok   ' if result['passed'] else 'STUCK'
        pipeline = result.get('pipeline')
        agrees = (f', pipeline {share(pipeline["agreed"], pipeline["decisions"]):.0f}% of {pipeline["decisions"]}'
                  if pipeline else '')
        print(f'{verdict} {result["name"]:<44} {result["game_minutes"]:>4}m played, quiet {result["worst_quiet_minutes"]:>3}m, '
              f'{result["reloads"]} reloads, {result["wall_seconds"]}s{agrees}'
              + ('' if result['passed'] else f'\n      {result["failure"]} on {result["final_map"]}: '
                                             f'{result["objective"]} ({result["reason"]})'), flush=True)
    results.sort(key=lambda row: row['name'])
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    stuck = [row['name'] for row in results if not row['passed']]
    print(f'{len(results) - len(stuck)} of {len(results)} scenarios got going again')
    total, low = agreement(results)
    if total:
        print(f'decide pipeline: agrees on {share(total["agreed"], total["decisions"]):.1f}% of '
              f'{total["decisions"]} decisions and {share(total["frames_agreed"], total["frames"]):.1f}% of frames')
        if low:
            print(f'decide pipeline under {100 * PIPELINE_BAR:g}% of frames: {", ".join(low)}')
    return 1 if stuck else 0


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rom', type=Path, action='append',
                        help='a cartridge to replay with, repeatable. By default ROM_PATH, BLUE_ROM_PATH, '
                             'YELLOW_ROM_PATH and the cartridges in GEN2_CARTRIDGE_DIR, chosen by the checkpoint ROM hash')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('POKESIM_SCENARIOS', DEFAULT_ROOT)))
    commands = parser.add_subparsers(dest='command', required=True)
    showing = commands.add_parser('show', help='describe a scenario after its edits')
    showing.add_argument('scenario', type=Path)
    showing.set_defaults(action=show)
    running = commands.add_parser('run', help='replay the scenarios')
    running.add_argument('only', nargs='*', help='run scenarios whose name contains one of these words')
    running.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) // 2))
    running.add_argument('--output', type=Path, help='write the full results as JSON')
    running.set_defaults(action=run)
    args = parser.parse_args(argv)
    return args.action(args)


if __name__ == '__main__':
    raise SystemExit(main())
