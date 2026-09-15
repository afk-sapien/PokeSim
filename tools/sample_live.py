"""Record bounded health and adventure evidence from the homeserver."""
import argparse
import json
from pathlib import Path
import subprocess
import time


REMOTE = r'''
import json
from pathlib import Path
import shutil
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
            'speed': state.get('speed'), 'paused': state.get('paused'),
            'reloads': state['reloads'], 'frame': state['frame'],
            'owned': game['owned'], 'position': [game['map_name'], game['x'], game['y']],
            'bag_slots': len(game['items']), 'items': game['items'],
            'goal': strategy.get('objective'), 'activity': strategy.get('action'),
            'policy_recoveries': strategy.get('recoveries'),
            'progress': state.get('progress'), 'league_rewards': state.get('league_rewards'),
            'legendary_recovery': state.get('legendary_recovery'),
            'project': collection.get('hunt'),
            'project_remaining': collection.get('remaining_seconds'),
            'completed_projects': director.get('completed', {}),
            'recent_outcomes': director.get('outcomes', [])[-3:],
            'legendary_outcomes': [row for row in director.get('outcomes', [])
                                   if row.get('category') == 'legendary'][-4:],
            'pickups': strategy.get('pickups', {}).get('history', []),
            'pickup_state': {key: strategy.get('pickups', {}).get(key)
                             for key in ('active', 'retry', 'next_scan', 'completed')},
            'party': [{key: mon.get(key) for key in ('dex', 'nick', 'level', 'experience', 'hp', 'max_hp', 'status', 'pp')}
                      for mon in game['party']],
        }
    except Exception as error:
        sample['runs'][edition] = {'error': str(error)}
try:
    with urllib.request.urlopen('http://localhost:8950/api/proposals', timeout=10) as response:
        board = json.load(response)
    trading = board.get('trading', {})
    sample['trading'] = {key: trading.get(key) for key in
                         ('enabled', 'interval_seconds', 'completed', 'state', 'error',
                          'last_check', 'last_trade', 'last_operation')}
    coordinator = json.loads(subprocess.check_output(['docker', 'inspect', 'pokesim-trading'], timeout=8))[0]
    sample['trading'].update(image=coordinator['Config']['Image'],
                             started_at=coordinator['State']['StartedAt'],
                             restarts=coordinator['RestartCount'], running=coordinator['State']['Running'])
    sample['trading']['opportunities'] = len(board.get('routine_proposals', []))
    sample['trading']['recent_exchanges'] = [
        {key: row.get(key) for key in ('id', 'ts', 'reason')}
        for row in trading.get('history', [])[-3:]
    ]
except Exception as error:
    sample['trading'] = {'error': str(error)}
try:
    raw = subprocess.check_output(['docker', 'stats', '--no-stream', '--format', '{{json .}}',
                                   'pokesim', 'pokesim-blue'], text=True, timeout=10)
    sample['resources'] = [json.loads(line) for line in raw.splitlines()]
except Exception as error:
    sample['resource_error'] = str(error)
try:
    usage = shutil.disk_usage('/docker')
    sample['disk'] = {'total_bytes': usage.total, 'used_bytes': usage.used,
                      'free_bytes': usage.free, 'used_percent': round(100 * usage.used / usage.total, 2)}
    directories = [path for root in ('/docker/pokesim', '/docker/pokesim-blue')
                   for path in (root + '/data', root + '/backups') if Path(path).exists()]
    sizes = subprocess.check_output(['du', '-sk', *directories], text=True, timeout=15)
    sample['directory_bytes'] = {path: int(kib) * 1024 for kib, path in
                                 (line.split('\t', 1) for line in sizes.splitlines())}
except Exception as error:
    sample['disk_error'] = str(error)
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
