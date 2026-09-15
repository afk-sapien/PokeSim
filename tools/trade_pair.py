"""Run one recoverable trusted trade for a configured pair of Docker instances."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write(path, value):
    atomic(path, json.dumps(value, indent=2).encode())


def request(peer, action=None):
    path = '/api/control' if action else '/api/state'
    data = json.dumps({'action': action}).encode() if action else None
    req = urllib.request.Request(peer['url'] + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.load(response)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120).stdout


def safe(state):
    game = state.get('game') or {}
    return bool(state.get('health', {}).get('ok') and game.get('party')
                and not game.get('in_battle') and not game.get('textbox') and not game.get('start_menu'))


class Coordinator:
    def __init__(self, root):
        self.root = root
        self.config = json.loads((root / 'policy.json').read_text())
        self.peers = self.config['peers']
        assert set(self.peers) == {'red', 'blue'}
        self.active_path = root / 'active.json'

    def worker(self, action, transaction):
        args = ['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--read-only',
                '--tmpfs', '/tmp:mode=1777', '-v', f'{self.root}:/trading',
                '-v', f"{self.config['game_data']}:/data/game-data:ro"]
        for name, peer in self.peers.items():
            args += ['-v', f"{peer['data']}:/pair/{name}", '-v', f"{peer['rom']}:/roms/{name}.gb:ro"]
        return run(*args, self.config['image'], 'python', '-m', 'pokesim.trade.pair', action, transaction)

    def result(self, transaction):
        return json.loads((self.root / 'transactions' / transaction / 'result.json').read_text())

    def finish(self, active):
        committed = active['phase'] == 'committed'
        if committed:
            self.worker('journal', active['id'])
        else:
            # Until the decision is durable neither output may remain eligible for restore.
            for path in active.get('targets', []):
                target = Path(path)
                target.unlink(missing_ok=True)
                fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        for name in active.get('stopped', []):
            run('docker', 'start', self.peers[name]['container'])
        for name in active.get('paused', []):
            if name not in active.get('stopped', []):
                request(self.peers[name], 'resume')
        for name in active.get('stopped', []):
            for _ in range(30):
                try:
                    if request(self.peers[name]).get('health', {}).get('ok'):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError(f'{name} has not recovered after the exchange')
        status_path = self.root / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {'history': [], 'completed': 0}
        if committed and not any(row['id'] == active['id'] for row in status['history']):
            result = self.result(active['id'])
            row = {'id': active['id'], 'ts': active['ts'], 'reason': result['reason'], 'moved': result['moved']}
            status['history'] = (status['history'] + [row])[-50:]
            status['completed'] += 1
            status['last_trade'] = active['ts']
        status.update(last_check=time.time(), state='ready', error=None)
        write(status_path, status)
        self.active_path.unlink(missing_ok=True)
        # Keep bounded recovery artifacts, without deleting the current transaction.
        directories = sorted((self.root / 'transactions').glob('[0-9]*'), key=lambda p: int(p.name))
        for directory in directories[:-20]:
            if directory.name != active['id']:
                shutil.rmtree(directory)

    def cycle(self):
        if self.active_path.exists():
            self.finish(json.loads(self.active_path.read_text()))
            return
        if not self.config.get('enabled', False):
            return
        status_path = self.root / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {'history': [], 'completed': 0}
        interval = max(300, self.config.get('interval_seconds', 900))
        if time.time() - status.get('last_trade', 0) < interval:
            return
        states = {name: request(peer) for name, peer in self.peers.items()}
        if any(s.get('paused') or not safe(s) for s in states.values()):
            status.update(last_check=time.time(), state='waiting_for_overworld', error=None)
            write(status_path, status)
            return
        for peer in self.peers.values():
            image = run('docker', 'inspect', '--format', '{{.Config.Image}}', peer['container']).strip()
            if image != self.config['image']:
                raise RuntimeError('Both peers must use the configured trading release')
        # Avoid stopping both games when the fresh proposal board has nothing useful.
        with urllib.request.urlopen(self.config['board_url'] + '/api/proposals', timeout=20) as response:
            opportunities = json.load(response).get('routine_proposals', [])
        if not opportunities:
            status.update(last_check=time.time(), state='waiting_for_opportunity', error=None)
            write(status_path, status)
            return
        active = {'id': str(time.time_ns()), 'ts': time.time(), 'phase': 'preparing', 'paused': [], 'stopped': [], 'targets': []}
        write(self.active_path, active)
        try:
            for name, peer in self.peers.items():
                active['paused'].append(name)
                write(self.active_path, active)
                request(peer, 'pause')
                for _ in range(30):
                    state = request(peer)
                    if state['paused']:
                        break
                    time.sleep(0.1)
                if not state['paused'] or not safe(state):
                    raise RuntimeError('A peer left the safe point before pausing')
            for name, peer in self.peers.items():
                active['stopped'].append(name)
                write(self.active_path, active)
                run('docker', 'stop', '-t', '30', peer['container'])
            self.worker('stage', active['id'])
            result = self.result(active['id'])
            if result['status'] == 'staged':
                pairs = []
                for name, peer in self.peers.items():
                    source = self.root / 'transactions' / active['id'] / 'after' / name / Path(result['states'][name]).name
                    assert hashlib.sha256(source.read_bytes()).hexdigest() == result['hashes'][name]
                    target = Path(peer['data']) / 'states' / source.name
                    pairs += [(source, target), (source.with_suffix('.json'), target.with_suffix('.json'))]
                active['targets'] = [str(target) for _, target in pairs]
                write(self.active_path, active)
                for source, target in pairs:
                    atomic(target, source.read_bytes())
                    owner = target.parent.stat()
                    os.chown(target, owner.st_uid, owner.st_gid)
                active['phase'] = 'committed'
                write(self.active_path, active)
            self.finish(active)
        except BaseException:
            # Recovery uses the durable decision, including after an interrupted write.
            self.finish(json.loads(self.active_path.read_text()))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            Coordinator(args.root).cycle()
        except Exception as error:
            path = args.root / 'status.json'
            status = json.loads(path.read_text()) if path.exists() else {'history': [], 'completed': 0}
            status.update(last_check=time.time(), state='retrying', error=str(error))
            write(path, status)
            raise


if __name__ == '__main__':
    main()
