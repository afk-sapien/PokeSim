"""Coordinate scoped, authenticated exchanges without host or Docker access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from urllib.error import HTTPError
import urllib.request

from ..platform_io import lock_file, sync_directory
from ..rewards import mew_enabled


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
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
        from . import pair
        if action == 'stage':
            for peer in self.peers.values():
                with sqlite3.connect(Path(peer['data']) / 'pokesim.sqlite') as db:
                    row = db.execute("SELECT v FROM kv WHERE k='trade_hold'").fetchone()
                hold = json.loads(row[0]) if row else None
                if not hold or hold['id'] != transaction or hold['phase'] != 'prepared':
                    raise ValueError('Both games must hold this prepared transaction')
        kind = (json.loads(self.active_path.read_text()).get('kind') if action == 'stage'
                else self.result(transaction).get('kind'))
        if kind in ('mew_event', 'league_reward'):
            from . import event
            if action == 'stage':
                event.stage(self.root, transaction, league_rewards=kind == 'league_reward')
            else:
                event.journal(self.root, transaction)
        else:
            (pair.stage if action == 'stage' else pair.journal)(self.root, transaction)

    def control(self, name, action, transaction):
        peer = self.peers[name]
        data = json.dumps({'action': action, 'value': transaction}).encode()
        req = urllib.request.Request(peer['url'] + '/api/trade', data=data,
              headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + peer['token']})
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    def result(self, transaction):
        return json.loads((self.root / 'transactions' / transaction / 'result.json').read_text())

    def prepare(self, name, transaction, deadline):
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('The games did not reach a safe point in time')
            try:
                return self.control(name, 'prepare', transaction)
            except HTTPError as error:
                if error.code != 409:
                    raise
                try:
                    detail = json.load(error).get('detail')
                except (ValueError, AttributeError):
                    raise error
                if detail != 'Waiting for an unpaused overworld safe point':
                    raise
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.25, remaining))

    def finish(self, active):
        committed = active['phase'] == 'committed'
        if committed:
            self.worker('journal', active['id'])
        else:
            # Until the decision is durable neither output may remain eligible for restore.
            for path in active.get('targets', []):
                target = Path(path)
                target.unlink(missing_ok=True)
                sync_directory(target.parent)
        if committed:
            for name in self.peers:
                self.control(name, 'load', active['id'])
            for name in self.peers:
                self.control(name, 'release', active['id'])
        else:
            for name in active.get('prepared', []):
                self.control(name, 'abort', active['id'])
        status_path = self.root / 'public' / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {'history': [], 'completed': 0}
        if committed and active.get('kind') in ('mew_event', 'league_reward'):
            result = self.result(active['id'])
            events = status.get('events', [])
            if not any(row['id'] == active['id'] for row in events):
                events.append({'id': active['id'], 'ts': active['ts'], 'event': result['event'], 'gifts': result['gifts']})
                status['events'] = events[-10:]
                if active.get('kind') == 'mew_event':
                    status['mew_recipients'] = sorted(set(status.get('mew_recipients', []))
                                                    | {gift['instance'] for gift in result['gifts']})
                else:
                    totals = status.setdefault('league_rewards', {})
                    for gift in result['gifts']:
                        totals[gift['instance']] = max(totals.get(gift['instance'], 0), gift['ordinal'])
        elif committed and not any(row['id'] == active['id'] for row in status['history']):
            result = self.result(active['id'])
            row = {'id': active['id'], 'ts': active['ts'], 'reason': result['reason'], 'moved': result['moved']}
            status['history'] = (status['history'] + [row])[-50:]
            status['completed'] += 1
            status['last_trade'] = active['ts']
        # Persist the last attempted operation so backlogs alternate even after a
        # skipped proposal, interrupted attempt, or coordinator restart.
        status.update(last_check=time.time(), state='ready', error=None,
                      last_operation=active.get('kind', 'trade'))
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
        status_path = self.root / 'public' / 'status.json'
        status = json.loads(status_path.read_text()) if status_path.exists() else {'history': [], 'completed': 0}
        interval = max(300, self.config.get('interval_seconds', 900))
        trade_cooling = time.time() - status.get('last_trade', 0) < interval
        if trade_cooling and not mew_enabled(self.config):
            return
        states = {name: request(peer) for name, peer in self.peers.items()}
        reward_due = self.config.get('league_rewards', False) and any(
            state.get('league_rewards', {}).get('pending', 0) > 0
            and any(count < 20 for count in state.get('game', {}).get('storage', {}).get('box_counts', []))
            for state in states.values())
        event_due = mew_enabled(self.config) and any(
            name not in status.get('mew_recipients', [])
            and 151 not in state.get('game', {}).get('dex_owned', [])
            and state.get('strategy', {}).get('milestones', {}).get('champion')
            and any(count < 20 for count in state.get('game', {}).get('storage', {}).get('box_counts', []))
            for name, state in states.items())
        if trade_cooling and not reward_due and not event_due:
            return
        if any(s.get('paused') or not s.get('health', {}).get('ok')
               or not (s.get('game') or {}).get('party') for s in states.values()):
            status.update(last_check=time.time(), state='waiting_for_overworld', error=None)
            write(status_path, status)
            return
        # Avoid holding both games when the fresh proposal board has nothing useful.
        opportunities = []
        trade_turn = (reward_due and not trade_cooling
                      and status.get('last_operation') == 'league_reward')
        if not event_due and (not reward_due or trade_turn):
            try:
                with urllib.request.urlopen(self.config['board_url'] + '/api/proposals', timeout=20) as response:
                    opportunities = json.load(response).get('routine_proposals', [])
            except (OSError, ValueError):
                if not reward_due:
                    raise
                # An unavailable board must not prevent an earned reward delivery.
        if not opportunities and not event_due and not reward_due:
            status.update(last_check=time.time(), state='waiting_for_opportunity', error=None)
            write(status_path, status)
            return
        active = {'id': str(time.time_ns()), 'ts': time.time(), 'phase': 'preparing', 'prepared': [], 'targets': []}
        if event_due:
            active['kind'] = 'mew_event'
        elif reward_due and not opportunities:
            active['kind'] = 'league_reward'
        write(self.active_path, active)
        try:
            # Each game checks its own live state. Stale API samples need not share
            # an overworld instant. Retries share one deadline across both peers.
            deadline = time.monotonic() + 15
            for name in self.peers:
                active['prepared'].append(name)
                write(self.active_path, active)
                prepared = self.prepare(name, active['id'], deadline)
                if prepared['phase'] != 'prepared':
                    raise RuntimeError('The game has not reached a safe checkpoint')
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
                active['phase'] = 'committed'
                write(self.active_path, active)
            self.finish(active)
        except BaseException:
            # Recovery uses the durable decision, including after an interrupted write.
            self.finish(json.loads(self.active_path.read_text()))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/trading'))
    parser.add_argument('--loop', action='store_true')
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / 'lock').open('a+b') as lock:
        try:
            lock_file(lock)
        except BlockingIOError:
            return
        while True:
            try:
                Coordinator(args.root).cycle()
            except Exception as error:
                path = args.root / 'public' / 'status.json'
                status = json.loads(path.read_text()) if path.exists() else {'history': [], 'completed': 0}
                status.update(last_check=time.time(), state='retrying', error=type(error).__name__)
                write(path, status)
                print(f'Trading will retry after {type(error).__name__}', flush=True)
                if not args.loop:
                    raise
            if not args.loop:
                return
            time.sleep(60)


if __name__ == '__main__':
    main()
