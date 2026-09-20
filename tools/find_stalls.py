"""Play an isolated adventure at full speed and keep a replayable bundle for every stall.

Starts from a fresh cartridge or a copied checkpoint, never from live data. A stall is a
stretch of game time with no achievement. Each one leaves stall-NN/ in the output folder:
the moment it was noticed, the rolling checkpoint from before it began, a screenshot and
a report. Both checkpoints replay with tools/validate_progress.py. Outputs contain
private game data and must remain outside the checkout.
"""
import argparse
from collections import Counter, deque
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokesim.events import diff
from pokesim.headless import HeadlessRun
from pokesim.policies.progression import milestones
from pokesim.ram import read_snapshot
from pokesim.screen import Screen
from pokesim.stalls import FRAMES_PER_GAME_MINUTE as MINUTE, PROGRESS_EVENTS, advanced
from pokesim.strategy_data import MAPS

LEAGUE = {MAPS[name] for name in ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM', 'HALL_OF_FAME')}


def clock(frames):
    return f'{frames // (60 * MINUTE)}:{frames // MINUTE % 60:02d}'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, help='copied checkpoint to continue, fresh cartridge if omitted')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hours', type=float, default=60, help='game hours to play')
    parser.add_argument('--stall-minutes', type=int, default=90, help='game minutes without an achievement')
    parser.add_argument('--give-up-minutes', type=int, default=360,
                        help='stop after this many game minutes in one stall, 0 to keep playing')
    parser.add_argument('--until-champion', action='store_true', help='stop at the first Hall of Fame entry')
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    if args.hours <= 0 or args.stall_minutes <= 0 or args.give_up_minutes < 0:
        parser.error('--hours and --stall-minutes must be positive')
    root = Path(__file__).resolve().parents[1]
    if args.output.resolve().is_relative_to(root) and not args.output.resolve().is_relative_to(root / 'data'):
        parser.error('Outputs contain private game data. Choose a folder outside the checkout.')
    args.output.mkdir(parents=True, exist_ok=True)
    rolling = args.output / 'rolling'
    rolling.mkdir(exist_ok=True)

    run = HeadlessRun(args.rom, args.checkpoint, args.seed)
    start = progress_frame = run.frame
    budget = int(args.hours * 60 * MINUTE)
    recent = deque(maxlen=8)                      # rolling checkpoints, oldest first
    next_roll = next_report = run.frame
    stalls, timeline, modes = [], [], Counter()
    open_stall = None
    escapes, league_entry = 0, args.output / 'league-entry.state'
    previous, pending, outcome = None, [], 'budget reached'
    wall = time.monotonic()

    def report(snapshot):
        details = run.policy.details()
        return {'frame': run.frame, 'game_clock': clock(run.frame - start), 'map': snapshot.map_name,
                'position': [snapshot.x, snapshot.y], 'badges': bin(snapshot.badges).count('1'),
                'money': snapshot.money, 'owned': len(snapshot.owned),
                'party': [[mon.name, mon.level, mon.hp] for mon in snapshot.party],
                'objective': details.get('objective'), 'action': details.get('action'),
                'reason': details.get('reason'), 'recoveries': run.policy.recoveries,
                'recent_failures': details.get('history', [])[-5:], 'screen': Screen(run.pb.memory).text}

    try:
        while run.frame - start < budget:
            snapshot = read_snapshot(run.pb.memory, run.frame)
            events = [event for event in pending if event.still(snapshot)]
            if (previous is not None and snapshot.valid and snapshot.map == MAPS['LORELEIS_ROOM']
                    and previous.map not in LEAGUE and not snapshot.in_battle):
                run.save(league_entry)          # the application keeps the same save to restart a lost attempt
            new = diff(previous, snapshot, run.memory)
            pending = [event for event in new if event.still is not None]
            events += [event for event in new if event.still is None]
            caught = previous is not None and previous.valid and snapshot.valid and advanced(previous, snapshot)
            previous = snapshot
            gained = [event for event in events if event.type in PROGRESS_EVENTS]
            if caught and not gained:
                progress_frame, escapes = run.frame, 0      # a repeat catch or earned experience is still progress
            if gained:
                progress_frame, escapes = run.frame, 0
                if open_stall:
                    open_stall['ended_after_minutes'] = (run.frame - open_stall['noticed_frame']) // MINUTE
                    open_stall['ended_by'] = gained[0].title
                    print(f'  recovered after {open_stall["ended_after_minutes"]} more minutes: {gained[0].title}', flush=True)
                    open_stall = None
                for event in gained:
                    if event.type in ('badge', 'champion', 'item', 'trainer'):
                        timeline.append({'game_clock': clock(run.frame - start), 'type': event.type, 'title': event.title})
                        print(f'{clock(run.frame - start)} {event.title}', flush=True)
            if args.until_champion and snapshot.started and milestones(snapshot)['champion']:
                outcome = 'champion'
                break
            quiet = run.frame - progress_frame
            if snapshot.started and snapshot.valid and not open_stall and quiet >= args.stall_minutes * MINUTE:
                folder = args.output / f'stall-{len(stalls) + 1:02d}'
                folder.mkdir(exist_ok=True)
                run.save(folder / 'noticed.state')
                run.pb.screen.image.save(folder / 'noticed.png')
                before = next((path for frame, path, _ in recent if frame <= progress_frame), recent[0][1] if recent else None)
                # A checkpoint inside a battle that cannot end is no way out of it.
                calm = next((path for _, path, fighting in reversed(recent) if not fighting), None)
                if before:
                    for suffix in ('.state', '.json'):
                        (folder / f'before{suffix}').write_bytes(before.with_suffix(suffix).read_bytes())
                open_stall = {'folder': folder.name, 'noticed_frame': run.frame, 'quiet_minutes': quiet // MINUTE,
                              'has_before': bool(before), **report(snapshot)}
                (folder / 'report.json').write_text(json.dumps(open_stall, indent=2))
                stalls.append(open_stall)
                objective = (open_stall['objective'] or {}).get('title')
                print(f'{clock(run.frame - start)} STALL {folder.name}: {quiet // MINUTE} quiet minutes on '
                      f'{snapshot.map_name}, objective "{objective}", money {snapshot.money}', flush=True)
                if snapshot.in_battle and (calm or before):
                    # Some original-game battles cannot end, such as a frozen last partner against a
                    # foe that only uses Agility. The application reloads a save from before the battle,
                    # and restarts the League attempt if that did not help.
                    escapes += 1
                    restart = escapes >= 2 and snapshot.map in LEAGUE and league_entry.exists()
                    run.reload(league_entry if restart else calm or folder / 'before.state')
                    open_stall['escape'] = 'restarted the League attempt' if restart else 'reloaded a checkpoint from before the battle'
                    (folder / 'report.json').write_text(json.dumps(open_stall, indent=2))
                    print(f'  battle could not end, {open_stall["escape"]}', flush=True)
                    # Watch again from here, so a second dead end is noticed instead of waited out.
                    previous, pending, open_stall, progress_frame = None, [], None, run.frame
                    recent.clear()
            if open_stall and args.give_up_minutes and run.frame - open_stall['noticed_frame'] >= args.give_up_minutes * MINUTE:
                outcome = f'gave up in {open_stall["folder"]}'
                break
            # Prefer a moment outside battle, but never go a whole hour without a checkpoint.
            if (run.frame >= next_roll and snapshot.started and snapshot.valid
                    and (not snapshot.in_battle or run.frame >= next_roll + 30 * MINUTE)):
                path = rolling / f'{run.frame:010d}.state'
                run.save(path)
                if len(recent) == recent.maxlen:
                    for suffix in ('.state', '.json'):
                        recent[0][1].with_suffix(suffix).unlink(missing_ok=True)
                recent.append((run.frame, path, bool(snapshot.in_battle)))
                next_roll = run.frame + 30 * MINUTE
            if run.frame >= next_report:
                print(f'{clock(run.frame - start)} {snapshot.map_name} badges {bin(snapshot.badges).count("1")} '
                      f'owned {len(snapshot.owned)} money {snapshot.money} · {run.policy.goal.title}', flush=True)
                next_report = run.frame + 120 * MINUTE
            before_step = run.frame
            run.step(snapshot)
            modes[run.policy.mode] += run.frame - before_step
        final = read_snapshot(run.pb.memory, run.frame)
        run.save(args.output / 'final.state')
        summary = {'outcome': outcome, 'edition': run.policy.collection.version, 'seed': args.seed,
                   'started_from': str(args.checkpoint) if args.checkpoint else 'fresh cartridge',
                   'game_hours': round((run.frame - start) / (60 * MINUTE), 2),
                   'wall_minutes': round((time.monotonic() - wall) / 60, 1),
                   'stall_minutes': args.stall_minutes, 'stalls': stalls, 'timeline': timeline,
                   'mode_frames': dict(modes.most_common(12)), 'final': report(final),
                   'pyboy': version('pyboy')}
        (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps({'outcome': outcome, 'game_hours': summary['game_hours'], 'wall_minutes': summary['wall_minutes'],
                          'stalls': [(row['folder'], row['map'], (row['objective'] or {}).get('title'),
                                      row.get('ended_after_minutes')) for row in stalls],
                          'badges': summary['final']['badges'], 'owned': summary['final']['owned']}))
    finally:
        run.stop()
    return 1 if stalls else 0


if __name__ == '__main__':
    raise SystemExit(main())
