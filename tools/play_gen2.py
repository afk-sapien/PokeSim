"""Run an isolated Gen II policy scenario and retain failure evidence."""
import argparse
import io
import json
from pathlib import Path
import time

from pyboy import PyBoy

from pokesim.gen2.data import GameData
from pokesim.gen2.policy import Goal, Policy
from pokesim.gen2.ram import read_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('--game', required=True, choices=('gold', 'silver', 'crystal'))
    parser.add_argument('--data', type=Path, default=Path('.release-local/gen2-data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--load', type=Path)
    parser.add_argument('--frames', type=int, default=60000)
    parser.add_argument('--starter', default='cyndaquil')
    parser.add_argument('--until', default='')
    parser.add_argument('--focus', choices=('ruins', 'tower', 'celebi', 'contest', 'gifts', 'legends', 'stones', 'trade_items', 'breeding', 'encounter', 'headbutt', 'rock smash'))
    parser.add_argument('--species', type=int)
    parser.add_argument('--real-clock', action='store_true', help='Use the checkpoint real-time clock instead of freezing it')
    parser.add_argument('--stall-frames', type=int, default=12000)
    args = parser.parse_args()
    data = GameData.load(args.data, args.game)
    policy = Policy(data, seed=1, starter=args.starter)
    if args.focus:
        from pokesim.gen2 import breeding, collection, quests
        task = breeding.journey if args.focus == 'breeding' else getattr(quests, args.focus, None)
        if args.focus == 'ruins':
            from pokesim.gen2.ruins import journey
            task = lambda policy, snapshot, Goal: journey(policy, snapshot, Goal)
        if args.focus == 'contest':
            from pokesim.gen2.contest import journey
            task = lambda policy, snapshot, Goal: journey(policy, snapshot, Goal, force=True)
        if args.focus == 'celebi':
            from pokesim.gen2.celebi import journey
            task = lambda policy, snapshot, Goal: journey(policy, snapshot, Goal)
        if args.focus == 'tower':
            from pokesim.gen2.tower import journey
            task = lambda policy, snapshot, Goal: journey(policy, snapshot, Goal, force=True)

        def focused(snapshot, mem):
            if task:
                goal = task(policy, snapshot, Goal)
            else:
                species = args.species if args.focus == 'encounter' else 214 if args.focus == 'headbutt' else 213
                goal = None
                if species not in snapshot.owned:
                    target = policy.collection.get('target')
                    if target and target['species'] == species:
                        return collection.hunt(policy, snapshot, Goal)
                    options = []
                    for row in data.encounters:
                        current_time = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
                        if (row['species'] != species or args.focus != 'encounter' and row['method'] != args.focus
                                or not collection.matching_time(row['time'], current_time)):
                            continue
                        points = collection.encounter_points(policy, snapshot, row['map'], row['method'], rare=row['time'] == 'rare trees')
                        route = policy.nav.regions.route(snapshot, row['map'], [point[:2] for point in points], cut=True, surf=True)
                        if route is not None and points:
                            options.append((len(route), row['map'], row))
                    if not options:
                        return Goal('collection_wait', 'Wait for the field map to settle', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
                    policy.collection['target'] = dict(min(options, key=lambda row: row[:2])[-1], started=policy.decisions)
                    goal = collection.hunt(policy, snapshot, Goal)
            if goal is None:
                if not snapshot.in_battle and not mem.byte('wScriptRunning') and '┌' not in snapshot.tiles[12]:
                    policy.completed[args.focus] = snapshot.frame
                return Goal('collection_wait', 'Focused scenario complete', data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)
            return goal

        policy.journey = focused
    args.output.mkdir(parents=True, exist_ok=True)
    pb = PyBoy(str(args.rom), window='null', cgb=True, sound_emulated=True, ram_file=io.BytesIO(bytes(32768)))
    pb.set_emulation_speed(0)
    pb.rtc_lock_experimental(not args.real_clock)
    from pokesim.gen2.legendary import Recovery
    recovery = Recovery()
    frame, previous = 0, None
    last_progress, progress_frame, stopped = None, 0, None
    visited = set()
    start = time.monotonic()
    try:
        if args.load:
            with args.load.open('rb') as source:
                pb.load_state(source)
            metadata = args.load.with_suffix('.policy.json')
            if metadata.exists():
                policy.load_state_dict(json.loads(metadata.read_text()))
        if args.focus:
            policy.completed.pop(args.focus, None)
        with (args.output / 'trace.jsonl').open('w') as trace:
            while frame < args.frames:
                snapshot = read_snapshot(pb.memory, data, frame)
                recovery.observe(snapshot, pb.memory)
                visited.add((snapshot.map, snapshot.x, snapshot.y))
                progress = (len(visited), snapshot.badges, snapshot.money,
                            snapshot.owned, snapshot.event_flags,
                            tuple((mon.species, mon.level, mon.hp, mon.experience, mon.moves, mon.nick, mon.friendship)
                                  for mon in snapshot.party + tuple(mon for mon in snapshot.daycare if mon)))
                if progress != last_progress:
                    last_progress, progress_frame = progress, frame
                elif frame - progress_frame > args.stall_frames * (3 if snapshot.in_battle else 1):
                    stopped = 'No game progress within the scenario stall limit'
                    break
                action = policy.step(snapshot, pb.memory)
                summary = (snapshot.map, snapshot.x, snapshot.y, snapshot.in_battle, len(snapshot.party),
                           snapshot.badges, policy.mode)
                if summary != previous or policy.decisions % 100 == 0:
                    row = {'frame': frame, 'map': snapshot.map_name, 'x': snapshot.x, 'y': snapshot.y,
                           'battle': snapshot.in_battle, 'party': [(mon.name, mon.level, mon.hp) for mon in snapshot.party],
                           'mode': policy.mode, 'action': action.button, 'text': snapshot.tiles,
                           'menu': vars(policy.menu) if policy.menu else None}
                    trace.write(json.dumps(row) + '\n')
                    trace.flush()
                    print(frame, snapshot.map_name, snapshot.x, snapshot.y, policy.mode, action.button,
                          row['party'], flush=True)
                    previous = summary
                if args.until and args.until in policy.completed:
                    break
                if action.button:
                    pb.button_press(action.button)
                pb.tick(action.hold, True)
                if action.button:
                    pb.button_release(action.button)
                pb.tick(action.gap, True)
                frame += action.hold + action.gap
                if frame % 10000 < action.hold + action.gap:
                    pb.screen.image.save(args.output / 'latest.png')
                    with (args.output / 'latest.state').open('wb') as output:
                        pb.save_state(output)
                    (args.output / 'latest.policy.json').write_text(json.dumps(policy.state_dict()))
        snapshot = read_snapshot(pb.memory, data, frame)
        pb.screen.image.save(args.output / 'final.png')
        with (args.output / 'final.state').open('wb') as output:
            pb.save_state(output)
        (args.output / 'final.policy.json').write_text(json.dumps(policy.state_dict()))
        (args.output / 'final.json').write_text(json.dumps({'game': snapshot.to_dict(), 'policy': policy.state_dict(),
                                                         'seconds': time.monotonic() - start, 'stopped': stopped}, indent=2))
    finally:
        pb.stop(save=False)


if __name__ == '__main__':
    main()
