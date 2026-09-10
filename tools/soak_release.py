"""Run bounded, isolated release endurance and fresh-campaign checks."""
import argparse
import json
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def campaign_completed(state):
    return bool(state.get('strategy', {}).get('milestones', {}).get('champion')
                or (state.get('game') or {}).get('hall_of_fame_count', 0) > 0)


class Viewer:
    def __init__(self, port):
        self.port = port
        self.bytes = 0
        self.errors = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.consume, daemon=True)
        self.thread.start()

    def consume(self):
        while not self.stop.is_set():
            try:
                with urlopen(f'http://127.0.0.1:{self.port}/stream', timeout=10) as response:
                    while not self.stop.is_set():
                        chunk = response.read(16384)
                        if not chunk:
                            break
                        self.bytes += len(chunk)
            except Exception:
                self.errors += 1
                self.stop.wait(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Immutable, locally loaded image ID')
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--hours', type=float, default=48)
    parser.add_argument('--name-prefix', default='pokesim-release', help='Unique prefix for the isolated test containers')
    parser.add_argument('--base-port', type=int, default=18950, help='Two consecutive localhost ports for soak and campaign')
    args = parser.parse_args()
    assert args.image.startswith('sha256:'), 'Use the immutable loaded image ID'
    assert 0 < args.hours <= 72
    assert 1024 <= args.base_port <= 65534
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.time()
    report = {'started_at': now(), 'deadline_epoch': started + args.hours * 3600,
              'image': args.image, 'platform': platform.platform(), 'status': 'starting',
              'configuration': {'hours': args.hours, 'cpus_per_container': 2, 'memory_limit': '1g',
                                'soak_seed': 13, 'campaign_seed': 7,
                                'viewers': '0 for 30 minutes, 1 for 30 minutes, 4 for 30 minutes, then 1'},
              'runs': {}, 'failures': []}
    viewers = []
    previous_bytes = 0
    containers = []
    sample = None
    active_label = None
    try:
        for label, port, speed, seed in [('soak', args.base_port, 1, 13), ('campaign', args.base_port + 1, 0, 7)]:
            data = root / label
            data.mkdir()
            docker('run', '--rm', '--user', '0', '-v', f'{data}:/target', '--entrypoint', 'chown', args.image, '10001:10001', '/target')
            docker('run', '--rm', '--network', 'none', '--read-only', '-v', f'{data}:/data',
                   '-v', f'{args.source.resolve()}:/source:ro', args.image, 'python', '-m', 'pokesim.prepare_data', '/source')
            name = f'{args.name_prefix}-{label}'
            docker('run', '-d', '--name', name, '--read-only', '--cap-drop', 'ALL',
                   '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=64m,mode=1777',
                   '--cpus', '2', '--memory', '1g', '--memory-swap', '1g',
                   '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
                   '-p', f'127.0.0.1:{port}:8000', '-v', f'{data}:/data',
                   '-v', f'{args.rom.resolve()}:/roms/pokered.gb:ro',
                   '-e', f'SPEED={speed}', '-e', f'SEED={seed}', '-e', 'VIEWER_ONLY=1',
                   '-e', 'AUTOSAVE_SECONDS=60', '-e', 'KEEP_AUTOSAVES=20', args.image)
            containers.append(name)
            report['runs'][label] = {'container': name, 'port': port, 'status': 'running', 'samples': 0}
        time.sleep(8)
        report['status'] = 'running'
        last_sample_at = time.time()
        while time.time() < report['deadline_epoch']:
            sampled_at = time.time()
            assert sampled_at - last_sample_at < 180, 'Monitoring gap exceeded three minutes, continuity is unproven'
            last_sample_at = sampled_at
            elapsed = sampled_at - started
            count = 0 if elapsed < 1800 else 1 if elapsed < 3600 else 4 if elapsed < 5400 else 1
            while len(viewers) < count:
                viewers.append(Viewer(args.base_port))
            while len(viewers) > count:
                viewer = viewers.pop()
                viewer.stop.set()
                viewer.thread.join(timeout=12)
                previous_bytes -= viewer.bytes
            sample = {'at': now(), 'elapsed_seconds': round(elapsed, 1), 'viewers': count, 'runs': {}}
            total_bytes = sum(viewer.bytes for viewer in viewers)
            sample['stream_bytes_since_previous_sample'] = total_bytes - previous_bytes
            previous_bytes = total_bytes
            for label, details in report['runs'].items():
                if details['status'] != 'running':
                    continue
                active_label = label
                name = details['container']
                inspect = json.loads(docker('inspect', name))[0]
                assert inspect['State']['Running'], f'{label} exited'
                assert inspect['RestartCount'] == 0, f'{label} restarted'
                assert not inspect['State']['OOMKilled'], f'{label} exceeded its memory limit'
                with urlopen(f'http://127.0.0.1:{details["port"]}/api/state', timeout=10) as response:
                    state = json.load(response)
                details['latest'] = {key: state[key] for key in ('frame', 'uptime', 'reloads', 'game', 'strategy', 'health')}
                details['latest']['container_health'] = inspect['State'].get('Health')
                sample['runs'][label] = details['latest']
                assert state['health']['ok'], f'{label} became unhealthy'
                stats = json.loads(docker('stats', '--no-stream', '--format', '{{json .}}', name))
                disk = sum(path.stat().st_size for path in (root / label).rglob('*') if path.is_file())
                details['samples'] += 1
                details['latest'].update({'cpu_percent': stats['CPUPerc'], 'memory': stats['MemUsage'], 'data_bytes': disk})
                sample['runs'][label] = details['latest']
                if label == 'campaign' and campaign_completed(state):
                    details['status'] = 'champion'
                    details['finished_at'] = now()
                    details['uninterrupted'] = state['reloads'] == 0
                    docker('stop', '--time', '20', name)
            active_label = None
            with (root / 'samples.jsonl').open('a') as output:
                output.write(json.dumps(sample) + '\n')
            assert shutil.disk_usage(root).free > 5 * 1024**3, 'Less than 5 GiB free disk space'
            assert sum(run['latest']['data_bytes'] for run in report['runs'].values()) < 10 * 1024**3, 'Test data exceeded 10 GiB'
            report['updated_at'] = now()
            write(root / 'status.json', report)
            time.sleep(min(60, max(0, report['deadline_epoch'] - time.time())))
        report['status'] = 'finished'
        report['runs']['soak']['status'] = 'duration_completed'
        if report['runs']['campaign']['status'] == 'running':
            report['runs']['campaign']['status'] = 'campaign_incomplete_at_deadline'
    except Exception as error:
        report['status'] = 'failed'
        report['failures'].append(str(error))
        if sample is not None:
            report['failed_sample'] = sample
        if active_label is not None:
            report['runs'][active_label]['status'] = 'failed'
        raise
    finally:
        for viewer in viewers:
            viewer.stop.set()
        for name in containers:
            try:
                docker('stop', '--time', '20', name)
                (root / f'{name}.log').write_text(docker('logs', '--tail', '1000', name))
            except subprocess.CalledProcessError:
                pass
        for details in report['runs'].values():
            if details['status'] == 'running':
                details['status'] = 'stopped_after_failure'
        report['finished_at'] = now()
        write(root / 'status.json', report)
        print(json.dumps({key: report[key] for key in ('status', 'started_at', 'finished_at', 'failures')}), flush=True)


if __name__ == '__main__':
    main()
