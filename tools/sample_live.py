"""Record bounded health and adventure evidence from the homeserver."""
import argparse
import json
from pathlib import Path
import subprocess
import time


REMOTE = r'''
import json
import subprocess
import time
import urllib.request
sample = {'ts': time.time(), 'runs': {}}
for edition, name, port in [('red', 'pokesim', 8930), ('blue', 'pokesim-blue', 8940)]:
    try:
        with urllib.request.urlopen(f'http://localhost:{port}/api/state', timeout=8) as response:
            state = json.load(response)
        game = state['game']
        strategy = state.get('strategy', {})
        collection = strategy.get('collection', {})
        director = collection.get('director', {})
        info = json.loads(subprocess.check_output(['docker', 'inspect', name], timeout=8))[0]
        sample['runs'][edition] = {
            'version': state['version'], 'image': info['Config']['Image'],
            'started_at': info['State']['StartedAt'], 'restarts': info['RestartCount'],
            'health': state['health'], 'uptime': state['uptime'],
            'reloads': state['reloads'], 'frame': state['frame'],
            'owned': game['owned'], 'position': [game['map_name'], game['x'], game['y']],
            'goal': strategy.get('objective'), 'activity': strategy.get('action'),
            'progress': state.get('progress'), 'project': collection.get('hunt'),
            'project_remaining': collection.get('remaining_seconds'),
            'completed_projects': director.get('completed', {}),
            'recent_outcomes': director.get('outcomes', [])[-3:],
            'pickups': strategy.get('pickups', {}).get('history', []),
            'party': [{key: mon.get(key) for key in ('dex', 'nick', 'level', 'experience')}
                      for mon in game['party']],
        }
    except Exception as error:
        sample['runs'][edition] = {'error': str(error)}
try:
    raw = subprocess.check_output(['docker', 'stats', '--no-stream', '--format', '{{json .}}',
                                   'pokesim', 'pokesim-blue'], text=True, timeout=10)
    sample['resources'] = [json.loads(line) for line in raw.splitlines()]
except Exception as error:
    sample['resource_error'] = str(error)
print(json.dumps(sample))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='servarr')
    parser.add_argument('--output', type=Path, default=Path('data/operations/live-samples.json'))
    args = parser.parse_args()
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.host, 'python3', '-'],
                                input=REMOTE, text=True, capture_output=True, timeout=50, check=True)
        sample = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as error:
        sample = {'ts': time.time(), 'error': str(error)}
    rows = json.loads(args.output.read_text()) if args.output.exists() else []
    rows = (rows + [sample])[-3360:]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(rows, indent=2) + '\n')
    temporary.replace(args.output)
    print(json.dumps(sample))


if __name__ == '__main__':
    main()
