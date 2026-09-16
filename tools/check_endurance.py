"""Compare bounded private checkpoint replays without writing to their inputs."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokesim.build_info import source_info
from pokesim.game_data import directory

COMPARABLE = ('frames', 'rewinds', 'initial_owned', 'final_owned', 'new_owned',
              'initial_party', 'final_party', 'initial_items', 'final_items',
              'achievements', 'mode_frames', 'history', 'director', 'active_project',
              'policy_recoveries', 'final_goal', 'final_map')


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def summarize(result):
    useful = [row for row in result['achievements'] if row['type'] in {
        'badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level'}]
    milestones = [0, *(row['frame'] for row in useful), result['frames']]
    return {
        'frames': result['frames'], 'game_hours': round(result['frames'] / 216000, 3),
        'new_registrations': result['new_owned'], 'rewinds': result['rewinds'],
        'policy_recoveries': result['policy_recoveries'],
        'useful_events': dict(Counter(row['type'] for row in useful)),
        'longest_useful_event_gap_frames': max(b - a for a, b in zip(milestones, milestones[1:])),
        'progress_samples': result.get('progress_samples', []),
        'final_project_gains': (result.get('active_project') or {}).get('gains', {}),
        'final_map': result['final_map'], 'policy_fingerprint': result['policy_fingerprint'],
    }


def compare(baseline, candidate):
    return [key for key in COMPARABLE if baseline.get(key) != candidate.get(key)]


def run_replay(root, rom, checkpoint, frames, output, timeout):
    command = [sys.executable, str(root / 'tools' / 'validate_progress.py'),
               '--rom', str(rom), '--checkpoint', str(checkpoint), '--frames', str(frames),
               '--output', str(output)]
    env = {**os.environ, 'GAME_DATA_DIR': str(directory().resolve())}
    with output.with_suffix('.log').open('w') as log:
        subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)
    return json.loads(output.read_text())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private result directory')
    parser.add_argument('--frames', type=int, default=432000, help='Default: two hours of game time')
    parser.add_argument('--timeout', type=int, default=1800, help='Maximum wall seconds per replay')
    parser.add_argument('--baseline', type=Path, help='Separate source checkout for comparison')
    parser.add_argument('--require-equivalent', action='store_true')
    args = parser.parse_args(argv)
    if args.frames <= 0 or args.timeout <= 0:
        parser.error('Frame budget and timeout must be positive')
    if args.require_equivalent and not args.baseline:
        parser.error('--require-equivalent needs --baseline')
    rom, checkpoint = args.rom.resolve(), args.checkpoint.resolve()
    inputs = [rom, checkpoint, checkpoint.with_suffix('.json')]
    before = {str(path): checksum(path) for path in inputs}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'build': source_info(), 'frame_budget': args.frames, 'status': 'running',
              'runs': {}, 'input_checksums': before,
              'limits': 'Game-time replay with no rewinds. This does not prove wall-clock endurance. Event gaps can include productive XP gains.'}
    try:
        results = {}
        roots = [('baseline', args.baseline.resolve())] if args.baseline else []
        roots.append(('candidate', ROOT))
        for label, root in roots:
            results[label] = run_replay(root, rom, checkpoint, args.frames, output / f'{label}.json', args.timeout)
            report['runs'][label] = summarize(results[label])
        report['changed_fields'] = compare(results['baseline'], results['candidate']) if args.baseline else []
        report['status'] = 'changed' if report['changed_fields'] else 'completed'
        if args.require_equivalent and report['changed_fields']:
            raise RuntimeError('Replay behavior changed: ' + ', '.join(report['changed_fields']))
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        report['inputs_unchanged'] = all(path.is_file() and checksum(path) == before[str(path)] for path in inputs)
        if not report['inputs_unchanged']:
            report['status'] = 'failed'
            report['input_error'] = 'A replay input changed during validation'
        (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['inputs_unchanged']:
        raise RuntimeError(report['input_error'])
    print(json.dumps({'status': report['status'], 'summary': str(output / 'summary.json')}))


if __name__ == '__main__':
    main()
