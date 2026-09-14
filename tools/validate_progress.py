"""Replay a copied checkpoint without rewinds and report concrete adventure progress."""
import argparse
from collections import Counter
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyboy import PyBoy
from pokesim.benchmark import policy_fingerprint
from pokesim.checkpoints import CheckpointStore
from pokesim.events import RunMemory, diff
from pokesim.policies.base import PolicyContext
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import read_snapshot


def run(rom, checkpoint, frames):
    metadata = CheckpointStore(checkpoint.parent).checkpoint_metadata(checkpoint)
    if not metadata:
        raise ValueError('A checkpoint manifest is required for a faithful replay')
    rom_sha1 = hashlib.sha1(rom.read_bytes()).hexdigest()
    if metadata['rom_sha1'] != rom_sha1 or metadata['pyboy_version'] != version('pyboy'):
        raise ValueError('ROM or emulator version does not match the checkpoint')
    if metadata['policy'] != 'strategic':
        raise ValueError('This replay requires a strategic checkpoint')
    pb = PyBoy(str(rom), window='null', sound_emulated=False)
    pb.set_emulation_speed(0)
    policy = StrategicPolicy(42)
    policy.load_state_dict(metadata['policy_state'])
    policy.collection.version = 'blue' if rom_sha1 == 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2' else 'red'
    memory = RunMemory.from_dict(metadata['run_memory'])
    frame = start = metadata.get('frame', 0)
    wall = time.monotonic()
    fingerprint = policy_fingerprint()
    counts = Counter()
    achievements = []
    pending = []
    try:
        with checkpoint.open('rb') as stream:
            pb.load_state(stream)
        first = previous = read_snapshot(pb.memory, frame)
        while frame - start < frames:
            snapshot = read_snapshot(pb.memory, frame)
            events = [event for event in pending if event.still(snapshot)]
            new = diff(previous, snapshot, memory)
            pending = [event for event in new if event.still is not None]
            events += [event for event in new if event.still is None]
            achievements.extend({'frame': frame - start, 'type': event.type, 'title': event.title}
                                for event in events if event.type not in ('playtime', 'release', 'blackout', 'seen'))
            previous = snapshot
            for action in policy.step(PolicyContext(snapshot, 0, 0, pb.memory)):
                if action.button:
                    pb.button_press(action.button)
                if action.hold:
                    pb.tick(action.hold, render=False)
                if action.button:
                    pb.button_release(action.button)
                if action.gap:
                    pb.tick(action.gap, render=False)
                frame += action.hold + action.gap
                counts[policy.mode] += action.hold + action.gap
        final = read_snapshot(pb.memory, frame)
        return {'edition': policy.collection.version, 'frames': frame - start,
                'wall_seconds': round(time.monotonic() - wall, 2), 'rewinds': 0,
                'initial_owned': len(first.owned), 'final_owned': len(final.owned),
                'new_owned': sorted(final.owned - first.owned),
                'initial_party': [(mon.name, mon.level, mon.experience) for mon in first.party],
                'final_party': [(mon.name, mon.level, mon.experience) for mon in final.party],
                'initial_items': list(first.items), 'final_items': list(final.items),
                'achievements': achievements, 'mode_frames': counts,
                'history': policy.collection.history,
                'director': policy.collection.director.state_dict(),
                'active_project': policy.collection.project,
                'pickups': policy.pickups.state_dict(),
                'policy_recoveries': policy.recoveries - metadata['policy_state'].get('recoveries', 0),
                'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'policy_fingerprint': fingerprint, 'pyboy': version('pyboy'),
                'final_goal': policy.goal.title, 'final_map': final.map_name}
    finally:
        pb.stop(save=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=432000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error('--frames must be positive')
    if args.output.resolve() in (args.rom.resolve(), args.checkpoint.resolve(), args.checkpoint.with_suffix('.json').resolve()):
        parser.error('Output must not overwrite a replay input')
    result = run(args.rom, args.checkpoint, args.frames)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('edition', 'frames', 'initial_owned', 'final_owned', 'policy_recoveries', 'final_map')}))
