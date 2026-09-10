"""Run an isolated campaign, keeping resumable checkpoints and concise progress logs."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyboy import PyBoy
from pokesim.policies.base import PolicyContext
from pokesim.policies.strategic import StrategicPolicy
from pokesim.policies.progression import milestones
from pokesim.ram import read_snapshot
from pokesim.screen import Screen, W_OPTIONS
from pokesim.strategy_data import event_set


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--rom', type=Path, default=Path('roms/pokered.gb'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=120000)
    parser.add_argument('--stop-event')
    parser.add_argument('--stop-position', type=int, nargs=3)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pb = PyBoy(str(args.rom), window='null', sound_emulated=False)
    pb.set_emulation_speed(0)
    with args.checkpoint.open('rb') as stream:
        pb.load_state(stream)
    policy = StrategicPolicy(args.seed)
    policy_path = args.checkpoint.with_suffix('.policy.json')
    if policy_path.exists():
        policy.load_state_dict(json.loads(policy_path.read_text()))
    frame = 0
    last = None
    last_report = -6000
    started = time.monotonic()
    def checkpoint(name):
        path = args.output / (name + '.state')
        with path.open('wb') as stream:
            pb.save_state(stream)
        path.with_suffix('.policy.json').write_text(json.dumps(policy.state_dict()))
        state = read_snapshot(pb.memory, frame)
        detail = {'frame': frame, 'elapsed': round(time.monotonic() - started, 2),
                  'game': state.to_dict(), 'strategy': policy.details(), 'screen': Screen(pb.memory).text,
                  'flags': list(state.event_flags)}
        path.with_suffix('.json').write_text(json.dumps(detail, indent=2))
        pb.screen.image.save(path.with_suffix('.png'))
        return detail
    try:
        while frame < args.frames:
            s = read_snapshot(pb.memory, frame)
            pb.memory[W_OPTIONS] = (pb.memory[W_OPTIONS] & ~7) | 129
            if args.stop_event and event_set(s.event_flags, args.stop_event):
                print('REACHED', args.stop_event, 'at', frame, flush=True)
                break
            if args.stop_position and (s.map, s.x, s.y) == tuple(args.stop_position):
                print('REACHED POSITION', args.stop_position, 'at', frame, flush=True)
                break
            if milestones(s)['champion'] and not args.stop_position and not args.stop_event:
                print('CHAMPION', frame, flush=True)
                break
            actions = policy.step(PolicyContext(s, 0, time.monotonic(), pb.memory))
            marker = (policy.goal.key, s.badges, s.items)
            if marker != last:
                checkpoint(f'{frame:08d}-{policy.goal.key}')
                print(frame, policy.goal.key, s.map_name, (s.x, s.y), 'badges', s.badges,
                      'levels', [p.level for p in s.party], flush=True)
                last = marker
            if frame - last_report >= 6000:
                detail = checkpoint('latest')
                print('STATE', frame, s.map_name, (s.x, s.y), policy.goal.key, policy.mode,
                      'battle', s.in_battle, 'recoveries', policy.recoveries,
                      repr(detail['screen'][-105:]), flush=True)
                last_report = frame
            for action in actions:
                if action.button:
                    pb.button_press(action.button)
                if action.hold:
                    pb.tick(action.hold, render=True)
                    frame += action.hold
                if action.button:
                    pb.button_release(action.button)
                if action.gap:
                    pb.tick(action.gap, render=True)
                    frame += action.gap
        checkpoint('latest')
    finally:
        pb.stop(save=False)


if __name__ == '__main__':
    main()
