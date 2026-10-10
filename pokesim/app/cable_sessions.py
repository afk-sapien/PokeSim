"""Manual Cable Club sessions: the owner holds both controllers of two linked adventures.

A session reuses the exchange transaction. Both adventures walk to the Cable Club and save
there exactly as for an automatic trade. A worker then links two disposable copies and ticks
them in lockstep while the owner's button presses reach either side. On Finish the worker
walks both trainers out, saves through the cartridges and checks that the cable only moved
Pokémon between the two parties. The coordinator checks that again from the manifest, stages
both results and commits. Anything else (Cancel, five idle minutes, a lost worker, a failed
check) aborts the transaction, which puts both adventures back on their Center saves.
"""
from __future__ import annotations

from collections import deque
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
KIND = 'cable_session'
GEN2 = {'gold', 'silver', 'crystal'}
IDLE_SECONDS = 300
BUTTONS = {'a', 'b', 'start', 'select', 'up', 'down', 'left', 'right'}
UNSUPPORTED = 'Manual Cable Club sessions support two Gold, Silver or Crystal adventures for now.'
NO_TRADE = 'Finished without a trade'
IDLE = 'No buttons were pressed for five minutes'
REASONS = {
    NO_TRADE: 'The session finished without a trade. Both adventures went back to their Pokémon Center saves.',
    IDLE: 'No buttons were pressed for five minutes, so the session ended. Both adventures went back to their Pokémon Center saves.',
    'Cancelled by the owner': 'The session was cancelled. Both adventures went back to their Pokémon Center saves.',
}


class CableSessions:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.registry = coordinator.registry
        self.guard = threading.Lock()
        self.live = {}
        self.idle_seconds = IDLE_SECONDS

    @staticmethod
    def is_session(row):
        return row['plan'].get('kind') == KIND

    def reason(self, game):
        """Why an adventure cannot join a session right now, or an empty string."""
        reason = self.coordinator.manual_game_reason(game)
        if reason:
            return reason
        if game['version'] not in GEN2:
            return UNSUPPORTED
        return ''

    def create(self, data):
        coordinator = self.coordinator
        names = {'left_id', 'right_id'}
        if not isinstance(data, dict) or not names <= set(data) or set(data) - names - {'request_id'}:
            raise ValueError('Choose two adventures for the Cable Club')
        tid = validate_id(data.get('request_id') or identifier())
        left, right = validate_id(data['left_id']), validate_id(data['right_id'])
        if left == right:
            raise ValueError('Choose two different adventures')
        with coordinator.manager.maintenance, coordinator.guard:
            try:
                existing = self.registry.transaction(tid)
            except KeyError:
                existing = None
            if existing:
                if not self.is_session(existing) or existing['plan']['participants'] != [left, right]:
                    raise ValueError('This request ID already belongs to another exchange')
                return self.status(tid)
            if coordinator.closed.is_set() or coordinator.manager.suspended:
                raise ValueError('Trading is paused for application maintenance')
            if self.registry.transactions(unresolved=True):
                raise ValueError('The Cable Club is busy with another exchange. Try again when it finishes')
            games = [self.registry.adventure(aid) for aid in (left, right)]
            for game in games:
                reason = self.reason(game)
                if reason:
                    raise ValueError(reason if reason == UNSUPPORTED else f'{game["name"]}: {reason}')
            plan = {'kind': KIND, 'manual': True, 'session': True, 'left_id': left, 'right_id': right,
                    'left_key': None, 'right_key': None, 'participants': [left, right],
                    'campaign_ids': {game['id']: game['campaign_id'] for game in games},
                    'attempt_id': identifier(), 'display_offers': {}}
            plan['plan_digest'] = digest(plan)
            self.registry.create_transaction(tid, plan)
            with self.guard:
                self.live[tid] = {'phase': 'preparing', 'trades': 0, 'last_input': time.monotonic(),
                                  'process': None, 'finishing': False, 'writer': threading.Lock()}
        return self.status(tid)

    def start(self, tid):
        """Run the session to its end on its own thread. A session can stay open for an hour."""
        def run():
            try:
                self.coordinator.execute(tid)
            except Exception:
                log.exception('Cable Club session %s failed', tid)
        thread = threading.Thread(target=run, daemon=True, name='cable-session')
        thread.start()
        return thread

    def for_adventure(self, aid):
        """The open or latest session of one adventure, for its Cable Club page."""
        game = self.registry.adventure(aid)
        rows = [row for row in self.registry.transactions(adventure_id=aid) if self.is_session(row)]
        latest = next((row for row in rows if row['phase'] not in {'completed', 'aborted'}), rows[0] if rows else None)
        return {'adventure': {key: game[key] for key in ('id', 'name', 'version', 'state')},
                'reason': self.reason(game), 'session': self.status(latest['id']) if latest else None}

    # The owner's commands.

    def _session(self, sid):
        row = self.registry.transaction(validate_id(sid))
        if not self.is_session(row):
            raise KeyError('Cable Club session not found')
        return row

    def _send(self, sid, command):
        with self.guard:
            live = self.live.get(sid)
        process = live and live.get('process')
        if not live or live['phase'] != 'in_session' or process is None or process.poll() is not None:
            raise ValueError('The controllers are not live yet')
        with live['writer']:
            try:
                process.stdin.write(json.dumps(command) + '\n')
                process.stdin.flush()
            except (OSError, ValueError) as error:
                raise ValueError('The Cable Club session is no longer running') from error
        return live

    def press(self, sid, data):
        row = self._session(sid)
        if row['decision'] is not None:
            raise ValueError('This session has already ended')
        if not isinstance(data, dict) or data.get('side') not in {'left', 'right'} or data.get('button') not in BUTTONS:
            raise ValueError('Choose a side and a Game Boy button')
        live = self._send(row['id'], {'side': data['side'], 'button': data['button']})
        live['last_input'] = time.monotonic()
        return self.status(row['id'])

    def finish(self, sid):
        row = self._session(sid)
        if row['decision'] is not None:
            raise ValueError('This session has already ended')
        live = self._send(row['id'], {'finish': True})
        live.update(finishing=True, phase='verifying')
        return self.status(row['id'])

    def cancel(self, sid):
        row = self._session(sid)
        if row['decision'] is None:
            self.coordinator.cancel(row['id'])
        return self.status(row['id'])

    # Status.

    def status(self, sid):
        row = self._session(sid)
        tid = row['id']
        with self.guard:
            live = dict(self.live.get(tid) or {})
        with self.coordinator.view_guard:
            sides = dict(self.coordinator.manual_progress.get(tid, {}))
        names = {}
        for aid in row['plan']['participants']:
            try:
                game = self.registry.adventure(aid)
                names[aid] = {'name': game['name'], 'version': game['version']}
            except KeyError:
                names[aid] = {'name': 'Another adventure', 'version': None}
        reason = None
        if row['phase'] == 'completed' and row['decision'] == 'COMMIT':
            phase = 'done'
        elif row['phase'] == 'aborted':
            phase = 'rolled_back'
            reason = self.failure_reason(row)
        elif row['decision'] == 'ABORT':
            phase = 'rolling_back'
            reason = self.failure_reason(row)
        elif row['decision'] == 'COMMIT' or row['phase'] in {'staging', 'committed', 'releasing'}:
            phase = 'verifying'
        elif row['phase'] == 'preparing':
            phase = 'ready' if sides and all(value == 'ready' for value in sides.values()) and len(sides) == 2 else (
                'travelling' if sides else 'preparing')
        else:
            phase = live.get('phase') or row['phase']
            if phase == 'connecting':
                phase = 'ready'
        idle = None
        if phase == 'in_session' and live.get('last_input') is not None:
            idle = max(0, round(self.idle_seconds - (time.monotonic() - live['last_input'])))
        display = self.coordinator._trade_display(row) if row['decision'] == 'COMMIT' else None
        return {'id': tid, 'kind': KIND, 'phase': phase, 'reason': reason, 'transaction_phase': row['phase'],
                'decision': row['decision'], 'left_id': row['plan']['participants'][0],
                'right_id': row['plan']['participants'][1], 'adventures': names,
                'preparation': sides if row['phase'] == 'preparing' else {},
                'trades': (row.get('result') or {}).get('trades', live.get('trades', 0)),
                'controls_live': phase == 'in_session', 'idle_seconds_left': idle,
                'display': display, 'updated_at': row['updated_at'],
                'cancellable': row['decision'] is None and row['phase'] not in {'completed', 'aborted'}}

    def failure_reason(self, row):
        return self.coordinator._failure_reason(row)

    def busy(self, aid):
        """The open session that holds this adventure, if any."""
        for row in self.registry.transactions(unresolved=True, adventure_id=aid):
            if self.is_session(row):
                return row['id']
        return None

    # The worker.

    def plan(self, row, prepared):
        from dataclasses import asdict
        from ..interactions.link_worker import CableParticipant, CableSessionPlan
        left, right = row['plan']['participants']
        return asdict(CableSessionPlan(interaction_id=row['id'], attempt_id=row['plan']['attempt_id'],
            speed=1, timeout_seconds=3600, max_steps=10000,
            left=CableParticipant(**prepared[left]['source']), right=CableParticipant(**prepared[right]['source'])))

    def run(self, row, session_plan):
        """Run the session worker until it publishes a verified manifest or the session ends."""
        coordinator = self.coordinator
        tid = row['id']
        with self.guard:
            live = self.live.setdefault(tid, {'phase': 'connecting', 'trades': 0, 'last_input': time.monotonic(),
                                              'process': None, 'finishing': False, 'writer': threading.Lock()})
            live['phase'] = 'connecting'
        directory = coordinator.manager.root / 'interactions' / tid / 'attempts' / row['plan']['attempt_id']
        directory.mkdir(parents=True, exist_ok=True)
        plan_path = directory / 'plan.json'
        CheckpointStore.atomic_write(plan_path, json.dumps(session_plan, sort_keys=True).encode())
        output = directory / 'outputs'
        if output.exists():
            raise ValueError('This cable attempt already has output. Recovery cannot run it a second time.')
        command = ([sys.executable, '--cable-session'] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'pokesim.gen2.manual_session'])
        command += ['--plan', str(plan_path), '--out', str(output)]
        env = os.environ.copy()
        env['GAME_DATA_DIR'] = str(coordinator.manager.assets.game_data_dir)
        if not getattr(sys, 'frozen', False):
            env['PYTHONPATH'] = str(Path(__file__).parents[2]) + os.pathsep + env.get('PYTHONPATH', '')
        messages = deque(maxlen=100)
        with coordinator.process_guard:
            if coordinator.closed.is_set():
                raise RuntimeError('PokeSim is shutting down')
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
            coordinator.process = process
        live['process'] = process

        def read():
            while line := process.stdout.readline(8193):
                if len(line) > 8192:
                    continue
                messages.append(line.strip())
                try:
                    progress = json.loads(line)
                    phase = progress.get('phase')
                except (ValueError, AttributeError):
                    continue
                if not isinstance(progress, dict):
                    continue
                for aid, preview in (progress.get('sides') or {}).items():
                    if aid in row['plan']['participants'] and isinstance(preview, dict):
                        with coordinator.view_guard:
                            coordinator.previews[aid] = {'side': preview.get('side'), 'frame': preview.get('frame'),
                                'interaction_id': tid, 'attempt_id': row['plan']['attempt_id'], 'phase': phase,
                                'preview_path': str(output / ('right.jpg' if preview.get('side') == 'right' else 'left.jpg')),
                                'updated_at': time.time()}
                if type(progress.get('trades')) is int:
                    live['trades'] = progress['trades']
                if phase == 'in_session' and live['phase'] != 'in_session' and not live['finishing']:
                    live.update(phase='in_session', last_input=time.monotonic())
                    with coordinator.guard:
                        if self.registry.transaction(tid)['decision'] is None:
                            self.registry.update_transaction(tid, phase='trading')
                elif phase in {'leaving', 'verifying', 'verified'}:
                    live['phase'] = 'verifying'
                    with coordinator.guard:
                        if self.registry.transaction(tid)['decision'] is None:
                            self.registry.update_transaction(tid, phase='verifying')

        reader = threading.Thread(target=read, daemon=True, name='cable-session-progress')
        reader.start()
        try:
            while process.poll() is None:
                if coordinator.closed.is_set() or self.registry.transaction(tid)['decision'] == 'ABORT':
                    raise RuntimeError('Cable Club session was cancelled')
                if (live['phase'] == 'in_session' and not live['finishing']
                        and time.monotonic() - live['last_input'] >= self.idle_seconds):
                    raise TimeoutError(IDLE)
                coordinator.closed.wait(0.2)
            reader.join(timeout=2)
            if process.returncode:
                last = messages[-1] if messages else str(process.returncode)
                raise RuntimeError(NO_TRADE if NO_TRADE in last else 'Cable Club session failed: ' + last)
            return json.loads((output / 'manifest.json').read_text())
        finally:
            live['phase'] = 'verifying' if live['finishing'] else live['phase']
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            reader.join(timeout=2)
            live['process'] = None
            CheckpointStore.atomic_write(directory / 'diagnostics.json', json.dumps(list(messages)).encode())
            with coordinator.process_guard:
                if coordinator.process is process:
                    coordinator.process = None

    def verify(self, row, manifest):
        """Check the published parties again in this process before either adventure stages them."""
        from ..gen2.manual_session import verify_parties
        from ..interactions.cable import CableError
        participants = manifest.get('participants') or {}
        rows = [participants.get(aid) or {} for aid in row['plan']['participants']]
        try:
            decode = lambda values: [{key: bytes.fromhex(value) for key, value in item.items()} for item in values]
            before = [decode(item['party_before']) for item in rows]
            after = [decode(item['party_after']) for item in rows]
            trades = [item['evidence']['trades'] for item in rows]
            if min(trades) < 1:
                raise ValueError(NO_TRADE)
            verify_parties(before, after, trades)
        except (CableError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(f'Cable session result failed verification: {error}') from error

    def forget(self, tid):
        with self.guard:
            self.live.pop(tid, None)
