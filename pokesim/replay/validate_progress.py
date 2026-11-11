"""Replay a copied checkpoint without rewinds and report concrete adventure progress."""
import argparse
from collections import Counter
import hashlib
from pokecore.emulator_state import runtime_provenance, validate_runtime
import json
from pathlib import Path
import time
from types import SimpleNamespace

from pokecore.emulator import Emulator as PyBoy
from pokesim.checkpoints import CheckpointStore
from pokesim.runtime.game_loop import Decider, GameLoop, write_gen1_options


def run(rom, checkpoint, frames):
    # These modules read the game data as they load, so --help works on a machine without game data.
    from pokesim.benchmark import policy_fingerprint
    from pokesim.events import RunMemory, diff
    from pokesim.policies.strategic import StrategicPolicy
    from pokesim.ram import read_snapshot
    metadata = CheckpointStore(checkpoint.parent).checkpoint_metadata(checkpoint)
    if not metadata:
        raise ValueError('A checkpoint manifest is required for a faithful replay')
    rom_sha1 = hashlib.sha1(rom.read_bytes()).hexdigest()
    validate_runtime(metadata)
    if metadata['rom_sha1'] != rom_sha1:
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
    full_recovery = None
    pending = []
    progress_samples = []
    next_sample = 36000
    host = SimpleNamespace(pb=pb, policy=policy, frame=frame)

    def tick(count):
        if count > 0:
            pb.tick(count, render=False)
            host.frame += count
            counts[policy.mode] += count

    loop = GameLoop(host, Decider(lambda: host.frame, write_gen1_options), tick)
    try:
        with checkpoint.open('rb') as stream:
            pb.load_state(stream)
        first = previous = read_snapshot(pb.memory, frame)
        while frame - start < frames:
            snapshot = read_snapshot(pb.memory, frame)
            if full_recovery is None and snapshot.party and all(
                    mon.hp == mon.max_hp and not mon.status and mon.pp == mon.max_pp
                    for mon in snapshot.party):
                full_recovery = {'frame': frame - start, 'map': snapshot.map_name}
            events = [event for event in pending if event.still(snapshot)]
            new = diff(previous, snapshot, memory)
            pending = [event for event in new if event.still is not None]
            events += [event for event in new if event.still is None]
            achievements.extend({'frame': frame - start, 'type': event.type, 'title': event.title}
                                for event in events if event.type not in ('playtime', 'release', 'blackout', 'seen'))
            previous = snapshot
            loop.step(snapshot)
            frame = host.frame
            if frame - start >= next_sample:
                project = policy.collection.project or {}
                progress_samples.append({
                    'frame': frame - start, 'owned': len(snapshot.owned),
                    'policy_recoveries': policy.recoveries - metadata['policy_state'].get('recoveries', 0),
                    'achievement_count': len(achievements), 'project': project.get('key'),
                    'gains': dict(project.get('gains', {})),
                    'training': {key: value for key, value in project.get('training_session', {}).items()
                                 if key != 'routes'},
                })
                next_sample += 36000
        final = read_snapshot(pb.memory, frame)
        return {'edition': policy.collection.version, 'frames': frame - start,
                'wall_seconds': round(time.monotonic() - wall, 2), 'rewinds': 0,
                'initial_owned': len(first.owned), 'final_owned': len(final.owned),
                'new_owned': sorted(final.owned - first.owned),
                'first_fully_restored_party': full_recovery,
                'initial_party': [(mon.name, mon.level, mon.experience) for mon in first.party],
                'final_party': [(mon.name, mon.level, mon.experience) for mon in final.party],
                'initial_items': list(first.items), 'final_items': list(final.items),
                'achievements': achievements, 'mode_frames': counts,
                'progress_samples': progress_samples,
                'history': policy.collection.history,
                'director': policy.collection.director.state_dict(),
                'active_project': policy.collection.project,
                'pickups': policy.pickups.state_dict(),
                'policy_recoveries': policy.recoveries - metadata['policy_state'].get('recoveries', 0),
                'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'policy_fingerprint': fingerprint, 'emulator': runtime_provenance(),
                'final_goal': policy.goal.title, 'final_map': final.map_name}
    finally:
        pb.stop(save=False)


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=432000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error('--frames must be positive')
    if args.output.resolve() in (args.rom.resolve(), args.checkpoint.resolve(), args.checkpoint.with_suffix('.json').resolve()):
        parser.error('Output must not overwrite a replay input')
    result = run(args.rom, args.checkpoint, args.frames)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('edition', 'frames', 'initial_owned', 'final_owned', 'policy_recoveries', 'final_map')}))


if __name__ == '__main__':
    main()
