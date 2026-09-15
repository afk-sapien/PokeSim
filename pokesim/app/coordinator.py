"""Durable orchestration of authentic, isolated two-cartridge exchanges."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from ..checkpoints import CheckpointStore
from .registry import digest, identifier, validate_id

log = logging.getLogger(__name__)
TERMINAL = {'completed', 'aborted'}
COOLDOWN_SECONDS = 300


class Coordinator:
    def __init__(self, manager):
        self.manager = manager
        self.registry = manager.registry
        self.guard = threading.RLock()
        self.execution = threading.Lock()
        self.closed = threading.Event()
        self.scheduler = None
        self.process = None
        self.process_guard = threading.Lock()
        self.previews = {}
        self.last_message = 'Your adventures will trade automatically when a useful exchange is ready.'
        self.next_recovery_at = 0
        self.prepare_timeout = 900
        self.prepare_poll = 1
        self.session_timeout = 960

    def reserved(self, aid):
        return any(aid in row['plan']['participants'] for row in self.registry.transactions(unresolved=True))

    def status(self):
        games = [game for game in self.registry.adventures() if not game['archived']]
        rows = self.registry.transactions()
        def public(row):
            return {**row, 'left_id': row['plan']['left_id'], 'right_id': row['plan']['right_id'],
                    'cancellable': row['decision'] is None and row['phase'] not in TERMINAL}
        return {'enabled': True, 'participants': [game['id'] for game in games],
                'active': [public(row) for row in rows if row['phase'] not in TERMINAL],
                'history': [public(row) for row in rows if row['phase'] in TERMINAL][:100],
                'message': self.last_message}

    def _request(self, aid, operation, data=None, recovery=False):
        if self.closed.is_set():
            raise RuntimeError('PokeSim is shutting down. The durable exchange will recover on startup.')
        if recovery:
            self.manager.supervisor.start(aid, recovery=True)
        child = self.manager.supervisor.child(aid)
        return child.request('GET' if data is None else 'POST', '/internal/participant/' + operation,
                             data, timeout=55)

    def inventory(self, aid):
        return self._request(aid, 'inventory')

    def propose(self, data):
        required = {'left_id', 'right_id', 'left_key', 'right_key'}
        if not isinstance(data, dict) or not required <= set(data) or set(data) - required - {'request_id'}:
            raise ValueError('Choose two adventures and their Pokémon')
        tid = validate_id(data.get('request_id') or identifier())
        selection = {name: data[name] for name in required}
        for name in ('left_id', 'right_id'):
            validate_id(selection[name])
        for name in ('left_key', 'right_key'):
            if not isinstance(selection[name], str) or not 1 <= len(selection[name]) <= 256:
                raise ValueError('Select an eligible individual Pokémon')
        if selection['left_id'] == selection['right_id']:
            raise ValueError('Choose two different adventures')
        with self.manager.maintenance, self.guard:
            try:
                existing = self.registry.transaction(tid)
            except KeyError:
                existing = None
            if existing:
                if any(existing['plan'][name] != value for name, value in selection.items()):
                    raise ValueError('This request ID already belongs to another exchange')
                return existing
            if self.closed.is_set() or self.manager.suspended:
                raise ValueError('Trading is paused for application maintenance')
            if self.registry.transactions(unresolved=True):
                raise ValueError('Resolve the current Cable Club exchange before starting another')
            participants = [selection['left_id'], selection['right_id']]
            campaigns = {}
            for side, aid in zip(('left', 'right'), participants):
                game = self.registry.adventure(aid)
                if game['archived'] or game['state'] != 'running' or game['desired_state'] != 'running':
                    raise ValueError('Both adventures must be running before an exchange')
                if (game.get('provenance') or {}).get('trading_blocked'):
                    raise ValueError(game['provenance'].get('reason') or 'This imported adventure needs its legacy peers reconciled before trading')
                if game['version'] not in {'red', 'blue'}:
                    raise ValueError('This Cable Club adapter supports Red and Blue')
                inventory = self.inventory(aid)
                if inventory.get('holding'):
                    raise ValueError('An adventure is already held for an exchange')
                eligible = {mon.get('trade_key') for mon in inventory.get('offers', [])}
                if selection[side + '_key'] not in eligible:
                    raise ValueError('This Pokémon is no longer eligible. Check its locks and trade preferences.')
                campaigns[aid] = game['campaign_id']
            plan = {**selection, 'participants': participants, 'campaign_ids': campaigns,
                    'attempt_id': identifier(), 'kind': 'cable_trade'}
            plan['plan_digest'] = digest(plan)
            return self.registry.create_transaction(tid, plan)

    def _prepare(self, row):
        deadline = time.monotonic() + self.prepare_timeout
        prepared = {}
        plan = row['plan']
        while len(prepared) != 2:
            if self.closed.is_set() or self.registry.transaction(row['id'])['decision'] == 'ABORT':
                raise RuntimeError('Cable Club preparation was cancelled')
            for side, aid in zip(('left', 'right'), plan['participants']):
                if aid in prepared:
                    continue
                receipt = self._request(aid, 'prepare', {'id': row['id'], 'plan_digest': plan['plan_digest'],
                                                        'selected_key': plan[side + '_key']})
                if receipt.get('phase') == 'prepared':
                    if receipt.get('plan_digest') != plan['plan_digest'] or receipt.get('selected_key') != plan[side + '_key']:
                        raise ValueError('Preparation receipt does not match the selected exchange')
                    prepared[aid] = receipt
                elif receipt.get('phase') != 'preparing':
                    raise ValueError('Unexpected participant preparation state')
            if len(prepared) == 2:
                return prepared
            if time.monotonic() >= deadline:
                raise TimeoutError('The adventures did not reach a safe Cable Club rendezvous in time')
            self.closed.wait(self.prepare_poll)
        return prepared

    def _session_plan(self, row, prepared):
        from ..interactions.link_worker import CableParticipant, CableSessionPlan
        left, right = row['plan']['participants']
        return asdict(CableSessionPlan(interaction_id=row['id'], attempt_id=row['plan']['attempt_id'],
            left=CableParticipant(**prepared[left]['source']), right=CableParticipant(**prepared[right]['source'])))

    def _run_cable(self, row, session_plan):
        directory = self.manager.root / 'interactions' / row['id'] / 'attempts' / row['plan']['attempt_id']
        directory.mkdir(parents=True, exist_ok=True)
        plan_path = directory / 'plan.json'
        CheckpointStore.atomic_write(plan_path, json.dumps(session_plan, sort_keys=True).encode())
        output = directory / 'outputs'
        if output.exists():
            raise ValueError('This cable attempt already has output. Recovery cannot run it a second time.')
        command = ([sys.executable, '--link-session'] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'pokesim.interactions.link_worker'])
        command += ['--plan', str(plan_path), '--out', str(output), '--watch-parent']
        env = os.environ.copy()
        env['GAME_DATA_DIR'] = str(self.manager.assets.game_data_dir)
        if not getattr(sys, 'frozen', False):
            env['PYTHONPATH'] = str(Path(__file__).parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
        messages = deque(maxlen=100)
        with self.process_guard:
            if self.closed.is_set():
                raise RuntimeError('PokeSim is shutting down')
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
            self.process = process
        def read():
            while line := process.stdout.readline(8193):
                if len(line) > 8192:
                    continue
                messages.append(line.strip())
                try:
                    progress = json.loads(line)
                    phase = progress.get('phase')
                    for aid, preview in (progress.get('sides') or {}).items():
                        if aid not in row['plan']['participants'] or not isinstance(preview, dict) or 'preview_path' not in preview:
                            continue
                        index = row['plan']['participants'].index(aid)
                        expected = output / ('left.jpg' if index == 0 else 'right.jpg')
                        if Path(preview['preview_path']).resolve() == expected.resolve():
                            with self.guard:
                                self.previews[aid] = {key: preview.get(key) for key in ('frame', 'map', 'x', 'y', 'side')}
                                self.previews[aid].update(interaction_id=row['id'], attempt_id=row['plan']['attempt_id'],
                                                         phase=phase, preview_path=str(expected), updated_at=time.time())
                    if phase in {'connecting', 'trading', 'saving', 'leaving', 'resuming', 'returning', 'verifying'}:
                        with self.guard:
                            current = self.registry.transaction(row['id'])
                            if current['decision'] is None:
                                self.registry.update_transaction(row['id'], phase=phase)
                except (ValueError, AttributeError):
                    pass
        reader = threading.Thread(target=read, daemon=True, name='cable-progress')
        reader.start()
        deadline = time.monotonic() + self.session_timeout
        try:
            while process.poll() is None:
                if self.closed.is_set() or self.registry.transaction(row['id'])['decision'] == 'ABORT':
                    raise RuntimeError('Cable Club session was cancelled')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Cable Club session exceeded its deadline')
                self.closed.wait(0.2)
            reader.join(timeout=2)
            if process.returncode:
                raise RuntimeError('Cable Club session failed: ' + (messages[-1] if messages else str(process.returncode)))
            return json.loads((output / 'manifest.json').read_text())
        finally:
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            reader.join(timeout=2)
            CheckpointStore.atomic_write(directory / 'diagnostics.json', json.dumps(list(messages)).encode())
            with self.process_guard:
                if self.process is process:
                    self.process = None

    def _verify_manifest(self, row, session_plan, manifest):
        from ..interactions.cable_metadata import ADAPTER_ID
        expected = hashlib.sha256(json.dumps(session_plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if (manifest.get('adapter_id') != ADAPTER_ID or manifest.get('status') != 'verified' or manifest.get('schema_version') != 1
                or manifest.get('interaction_id') != row['id'] or manifest.get('attempt_id') != row['plan']['attempt_id']
                or manifest.get('plan_sha256') != expected or set(manifest.get('participants', {})) != set(row['plan']['participants'])):
            raise ValueError('Cable output does not match this exact paired attempt')

    def execute(self, tid):
        if not self.execution.acquire(blocking=False):
            return self.registry.transaction(tid)
        try:
            row = self.registry.transaction(tid)
            if row['phase'] in TERMINAL:
                return row
            if row['decision']:
                return self._recover(row)
            try:
                prepared = self._prepare(row)
                session_plan = self._session_plan(row, prepared)
                self.registry.update_transaction(tid, phase='connecting')
                manifest = self._run_cable(row, session_plan)
                self._verify_manifest(row, session_plan, manifest)
                with self.guard:
                    if self.closed.is_set() or self.registry.transaction(tid)['decision'] == 'ABORT':
                        raise RuntimeError('Exchange was cancelled before commitment')
                    self.registry.update_transaction(tid, phase='staging')
                    for aid in row['plan']['participants']:
                        peer = next(other for other in row['plan']['participants'] if other != aid)
                        result = manifest['participants'][aid]
                        receipt = self._request(aid, 'stage', {'id': tid, 'attempt_id': row['plan']['attempt_id'],
                            'plan_digest': row['plan']['plan_digest'], 'result': result, 'incoming': prepared[peer]['outgoing']})
                        if (receipt.get('phase') != 'staged' or receipt.get('attempt_id') != row['plan']['attempt_id']
                                or receipt.get('plan_digest') != row['plan']['plan_digest']
                                or receipt.get('staged', {}).get('checkpoint_sha256') != result['checkpoint_sha256']):
                            raise ValueError('Participant did not durably stage the negotiated result')
                    row = self.registry.update_transaction(tid, decision='COMMIT', phase='committed', result=manifest, error=None)
                return self._recover(row)
            except Exception as error:
                row = self.registry.transaction(tid)
                if row['decision'] is None:
                    row = self.registry.update_transaction(tid, decision='ABORT', phase='aborting', error=str(error))
                else:
                    self.registry.update_transaction(tid, error=str(error))
                try:
                    return self._recover(row)
                except Exception as recovery_error:
                    return self.registry.update_transaction(tid, phase='recovering', error=str(recovery_error))
        finally:
            self.execution.release()

    def _recover(self, row):
        tid, plan = row['id'], row['plan']
        if row['phase'] in TERMINAL:
            return row
        if row['decision'] is None:
            row = self.registry.update_transaction(tid, decision='ABORT', phase='aborting')
        if row['decision'] == 'ABORT':
            for aid in plan['participants']:
                receipt = self._request(aid, 'abort', {'id': tid}, recovery=True)
                if receipt.get('phase') != 'aborted':
                    raise ValueError('Participant did not acknowledge abort')
            row = self.registry.update_transaction(tid, phase='aborted')
        else:
            manifest = row['result']
            if not manifest:
                raise ValueError('Committed result manifest is unavailable')
            for aid in plan['participants']:
                receipt = self._request(aid, 'apply', {'id': tid, 'attempt_id': plan['attempt_id'],
                    'plan_digest': plan['plan_digest'], 'checkpoint_sha256': manifest['participants'][aid]['checkpoint_sha256']}, recovery=True)
                if receipt.get('phase') not in {'applied', 'released'} or receipt.get('decision') != 'COMMIT':
                    raise ValueError('Participant did not acknowledge committed application')
            self.registry.update_transaction(tid, phase='releasing', error=None)
            for aid in plan['participants']:
                receipt = self._request(aid, 'release', {'id': tid})
                if receipt.get('phase') != 'released':
                    raise ValueError('Participant did not acknowledge release')
            row = self.registry.update_transaction(tid, phase='completed', error=None)
        for aid in plan['participants']:
            self.previews.pop(aid, None)
            if self.registry.adventure(aid)['desired_state'] == 'stopped':
                self.manager.supervisor.stop(aid)
            else:
                self.registry.update(aid, state='running', error=None)
        return row

    def recover_one(self, tid):
        with self.execution:
            row = self.registry.transaction(tid)
            try:
                return self._recover(row)
            except Exception as error:
                return self.registry.update_transaction(tid, phase='recovering', error=str(error))

    def recover(self):
        for row in self.registry.transactions(unresolved=True):
            self.recover_one(row['id'])

    def cancel(self, tid):
        with self.guard:
            row = self.registry.transaction(tid)
            if row['decision'] == 'COMMIT':
                raise ValueError('This exchange is committed and must finish recovery')
            if row['phase'] in TERMINAL:
                return row
            self.registry.update_transaction(tid, decision='ABORT', phase='aborting', error='Cancelled by the owner')
        with self.process_guard:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return self.recover_one(tid)

    @staticmethod
    def _benefit(inventory, mon):
        owned = set(inventory.get('owned', []))
        dex = mon.get('arrived_dex', mon.get('dex'))
        gain = len({mon.get('dex'), dex} - owned - {None})
        if gain:
            return 100 * gain
        copies = [entry for entry in list(inventory.get('party') or [])
                  + list((inventory.get('storage') or {}).get('pokemon') or []) if entry.get('dex') == dex]
        if not copies:
            return 20
        best_level = max(entry.get('level', 0) for entry in copies)
        if mon.get('level', 0) >= best_level + 5:
            return 10
        for field, improvement in [('dvs', 4), ('stat_exp', 20000)]:
            values = mon.get(field) or []
            known = [sum(entry[field]) for entry in copies if len(entry.get(field) or []) == 5]
            level_floor = best_level - 5 if field == 'dvs' else best_level
            if (len(values) == 5 and len(known) == len(copies) and mon.get('level', 0) >= level_floor
                    and sum(values) >= max(known) + improvement):
                return 5
        return 0

    def schedule_once(self):
        if self.closed.is_set() or self.manager.suspended or self.execution.locked():
            return None
        pending = self.registry.transactions(unresolved=True)
        if pending:
            if pending[0]['phase'] != 'recovering':
                return None
            if time.monotonic() >= self.next_recovery_at:
                self.next_recovery_at = time.monotonic() + 30
                self.last_message = 'Finishing an interrupted trade. Your progress is saved.'
                return self.recover_one(pending[0]['id'])
            return None
        history = self.registry.transactions()
        last = {}
        for row in history:
            for aid in row['plan']['participants']:
                last[aid] = max(last.get(aid, 0), row['updated_at'])
        inventories = []
        games = sorted(self.registry.adventures(), key=lambda game: (last.get(game['id'], 0), game['id']))
        for game in games:
            aid = game['id']
            if (game['state'] != 'running' or game['desired_state'] != 'running' or game['archived']
                    or game['version'] not in {'red', 'blue'} or (game.get('provenance') or {}).get('trading_blocked')
                    or time.time() - last.get(aid, 0) < COOLDOWN_SECONDS):
                continue
            try:
                inventory = self.inventory(aid)
                if not inventory.get('holding'):
                    inventories.append((aid, inventory))
            except (RuntimeError, OSError):
                continue
        for index, (left_id, left) in enumerate(inventories):
            for right_id, right in inventories[index + 1:]:
                candidates = []
                for give in left.get('offers', []):
                    for take in right.get('offers', []):
                        score = self._benefit(left, take) + self._benefit(right, give)
                        if score:
                            candidates.append((score, give.get('trade_key'), take.get('trade_key')))
                if candidates:
                    _, left_key, right_key = max(candidates, key=lambda item: (item[0], item[1] or '', item[2] or ''))
                    row = self.propose({'left_id': left_id, 'right_id': right_id,
                                        'left_key': left_key, 'right_key': right_key, 'request_id': identifier()})
                    self.last_message = 'A useful exchange is preparing at the Cable Club.'
                    return self.execute(row['id'])
        self.last_message = 'Your adventures are playing. They will trade when a useful exchange is ready.'
        return None

    def start_scheduler(self):
        if self.scheduler and self.scheduler.is_alive():
            return
        def run():
            while not self.closed.wait(10):
                try:
                    self.schedule_once()
                except Exception as error:
                    self.last_message = 'Trading is waiting and will try again. Your adventures keep their progress.'
                    log.warning('Automatic Cable Club scheduling failed: %s', error)
        self.scheduler = threading.Thread(target=run, daemon=True, name='cable-coordinator')
        self.scheduler.start()

    def preview(self, aid):
        with self.guard:
            preview = self.previews.get(aid)
            if preview and self.registry.transaction(preview['interaction_id'])['phase'] not in TERMINAL:
                return dict(preview)
            return None

    def close(self):
        self.closed.set()
        with self.process_guard:
            process = self.process
            if process and process.poll() is None:
                process.terminate()
        if process:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if self.scheduler and self.scheduler is not threading.current_thread():
            self.scheduler.join(timeout=60)
            if self.scheduler.is_alive():
                raise RuntimeError('Trading shutdown exceeded its deadline. Keep the registry open until its worker exits.')
