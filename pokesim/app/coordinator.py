"""Durable orchestration of authentic, isolated two-cartridge exchanges."""
from __future__ import annotations

from collections import Counter, deque
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

from ..checkpoints import CheckpointStore
from .registry import digest, identifier, validate_id

log = logging.getLogger(__name__)
TERMINAL = {'completed', 'aborted'}
COOLDOWN_SECONDS = 300


def _display_number(value, maximum):
    return value if type(value) is int and 1 <= value <= maximum else None


def _display_text(value):
    return value[:100] if isinstance(value, str) and value else None


def _nickname(raw):
    # Decode the receipt directly without importing a worker's global game data.
    characters = {0x7f: ' ', 0xba: 'é', 0xe0: "'", 0xe3: '-', 0xe6: '?', 0xe7: '!',
                  0xe8: '.', 0xef: '♂', 0xf4: ',', 0xf5: '♀', 0xf2: '.', 0xf1: '×',
                  0xe1: 'PK', 0xe2: 'MN', 0xf0: '$'}
    result = []
    for value in raw:
        if value in (0, 0x50):
            break
        if 0x80 <= value <= 0x99:
            result.append(chr(ord('A') + value - 0x80))
        elif 0xa0 <= value <= 0xb9:
            result.append(chr(ord('a') + value - 0xa0))
        elif 0xf6 <= value <= 0xff:
            result.append(chr(ord('0') + value - 0xf6))
        elif value in characters:
            result.append(characters[value])
        elif value >= 0x60:
            result.append('?')
    return ''.join(result).strip() or None


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
        self.display_species = None
        self.display_cache = {}

    def _species(self, species):
        if self.display_species is None:
            from ..game_data import load
            try:
                data = load('strategy.json', directory=self.manager.assets.game_data_dir)
                names = load('tables.json', directory=self.manager.assets.game_data_dir)['dex']
                self.display_species = {key: {**value, 'name': names.get(str(value['dex']),
                    value['name'].replace('_', ' ').title())} for key, value in data['species'].items()}
            except (RuntimeError, KeyError):
                return {}
        return self.display_species.get(str(species), {})

    def _mon_display(self, offer):
        if not isinstance(offer, dict):
            return None
        species = _display_number(offer.get('species'), 255)
        data = self._species(species) if species else {}
        result = {'species': species, 'dex': _display_number(data.get('dex', offer.get('dex')), 151),
                  'name': _display_text(data.get('name') or offer.get('name')),
                  'nickname': _display_text(offer.get('nickname', offer.get('nick'))),
                  'level': _display_number(offer.get('level'), 100), 'evolved_from': None}
        return result if any(value is not None for value in result.values()) else None

    def _receipt_display(self, receipt):
        try:
            raw = bytes.fromhex(receipt['outgoing']['struct'])
            nick = bytes.fromhex(receipt['outgoing']['nickname'])
            if len(raw) != 44 or len(nick) != 11:
                return None
            return self._mon_display({'species': raw[0], 'level': raw[33], 'nickname': _nickname(nick)})
        except (KeyError, TypeError, ValueError):
            return None

    def _historical_receipt(self, row, aid):
        path = self.manager.root / 'adventures' / validate_id(aid) / 'pokesim.sqlite'
        if not path.is_file():
            return {}
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.1)) as connection:
                saved = connection.execute('SELECT v FROM kv WHERE k=?',
                                           ('managed_interaction:' + row['id'],)).fetchone()
            receipt = json.loads(saved[0]) if saved else {}
            if (receipt.get('id') == row['id'] and receipt.get('plan_digest') == row['plan']['plan_digest']):
                return receipt
        except (sqlite3.Error, ValueError, TypeError, AttributeError):
            pass
        return {}

    def _trade_display(self, row, receipts=None, manifest=None):
        result = manifest if manifest is not None else row.get('result') or {}
        with self.guard:
            cached = self.display_cache.get(row['id'])
        if receipts is None and cached and cached[0] == row['updated_at']:
            return cached[1]
        committed = row['decision'] == 'COMMIT' or manifest is not None
        stored = result.get('display', {}) if committed else {}
        offered = row['plan'].get('display_offers', {})
        participants = row['plan']['participants']
        receipts = receipts if receipts is not None else {
            aid: self._historical_receipt(row, aid) for aid in participants
            if not stored.get(aid) and not offered.get(aid)}
        sent = {aid: self._receipt_display(receipts.get(aid, {})) or self._mon_display(
            (stored.get(aid) or {}).get('sent') or offered.get(aid)) for aid in participants}
        if committed:
            for aid in participants:
                peer = next(other for other in participants if other != aid)
                evidence = (result.get('participants', {}).get(peer, {}).get('evidence')
                            or receipts.get(peer, {}).get('staged', {}).get('evidence') or {})
                source_species = _display_number(evidence.get('incoming_species'), 255)
                if sent[aid] is None and source_species:
                    sent[aid] = self._mon_display({'species': source_species})
        display = {}
        for aid in participants:
            peer = next(other for other in participants if other != aid)
            incoming = sent[peer]
            received = dict(incoming) if incoming else None
            if committed:
                evidence = (result.get('participants', {}).get(aid, {}).get('evidence')
                            or receipts.get(aid, {}).get('staged', {}).get('evidence') or {})
                actual = _display_number(evidence.get('received_species'), 255)
                if actual:
                    saved_received = (stored.get(aid) or {}).get('received') or {}
                    base = saved_received or incoming or {}
                    same_species = base.get('species') == actual
                    received = self._mon_display({**base, 'species': actual,
                        'name': base.get('name') if same_species else None,
                        'dex': base.get('dex') if same_species else None})
                    before = _display_number(evidence.get('incoming_species'), 255)
                    if before and before != actual:
                        origin = self._mon_display({**(saved_received.get('evolved_from') or incoming or {}),
                                                    'species': before})
                        received['evolved_from'] = {key: origin[key] for key in ('name', 'species', 'dex')}
                    if evidence.get('default_name_evolved'):
                        received['nickname'] = received['name'].upper() if received['name'] else None
                elif (stored.get(aid) or {}).get('received'):
                    received = self._mon_display(stored[aid]['received'])
                    origin = self._mon_display(stored[aid]['received'].get('evolved_from'))
                    if origin:
                        received['evolved_from'] = {key: origin[key] for key in ('name', 'species', 'dex')}
                else:
                    received = None
            display[aid] = {'sent': sent[aid], 'received': received}
        if row['phase'] in TERMINAL:
            with self.guard:
                if len(self.display_cache) >= 128:
                    self.display_cache.pop(next(iter(self.display_cache)))
                self.display_cache[row['id']] = (row['updated_at'], display)
        return display

    def reserved(self, aid):
        return any(aid in row['plan']['participants'] for row in self.registry.transactions(unresolved=True))

    @staticmethod
    def _failure_reason(row):
        error = row.get('error') or ''
        if 'No supported walking route to the Cable Club' in error:
            return 'An adventure could not reach the Cable Club from its current location.'
        if 'route to the Cable Club is blocked by an unresolved obstacle' in error:
            return 'An obstacle still blocks an adventure’s route to the Cable Club.'
        if 'Cable Club preparation exceeded its travel deadline' in error:
            return 'An adventure took too long to reach the Cable Club and prepare its Pokémon.'
        if 'Every PC box is full' in error:
            return 'An adventure needs a free PC slot to prepare its Pokémon for this trade.'
        if 'route to the Cable Club needs a partner with Strength' in error:
            return 'An adventure needs a partner with Strength to reach the Cable Club.'
        if 'Cable Club preparation stopped making progress' in error:
            return 'An adventure stopped making progress while preparing for the Cable Club.'
        if 'No safe unprotected reserve can leave the party' in error:
            return 'An adventure could not safely make room in its party for the selected Pokémon.'
        if 'cannot be identified uniquely' in error or 'no longer eligible' in error:
            return 'A selected Pokémon was no longer available for this exchange.'
        if 'safe overworld' in error:
            return 'An adventure did not reach a safe stopping point in time.'
        if 'Cancelled by the owner' in error:
            return 'This exchange was cancelled.'
        return 'The exchange could not finish safely. Both adventures kept their Pokémon.'

    def _attention(self, rows):
        failures = []
        for row in rows:
            if row['phase'] == 'completed' and row['decision'] == 'COMMIT':
                break
            if row['phase'] == 'aborted':
                failures.append(row)
        if not failures:
            return None
        latest = failures[0]
        count = len(failures)
        lead = 'The last trade attempt did not complete.' if count == 1 else f'{count} recent trade attempts did not complete.'
        reason = self._failure_reason(latest)
        return {'recent_failure_count': count, 'updated_at': latest['updated_at'], 'reason': reason,
                'message': f'{lead} {reason} Automatic trading will try again.'}

    def status(self):
        games = [game for game in self.registry.adventures() if not game['archived']]
        rows = self.registry.transactions()
        def public(row):
            return {**row, 'left_id': row['plan']['left_id'], 'right_id': row['plan']['right_id'],
                    'display': self._trade_display(row),
                    'failure_reason': self._failure_reason(row) if row['phase'] == 'aborted' else None,
                    'cancellable': row['decision'] is None and row['phase'] not in TERMINAL}
        attention = self._attention(rows)
        return {'enabled': True, 'participants': [game['id'] for game in games],
                'active': [public(row) for row in rows if row['phase'] not in TERMINAL],
                'history': [public(row) for row in rows if row['phase'] in TERMINAL][:100],
                'recent_failures': [public(row) for row in rows if row['phase'] == 'aborted'][:5],
                'attention': attention,
                'message': attention['message'] if attention else self.last_message}

    def adventure_status(self, aid):
        game = self.registry.adventure(aid)
        names = {row['id']: row['name'] for row in self.registry.adventures()}
        rows = self.registry.transactions(adventure_id=aid)
        def public(row):
            peer = next(pid for pid in row['plan']['participants'] if pid != aid)
            detail = self._trade_display(row)[aid]
            def mon(value):
                if value is None:
                    return None
                dex = value['dex']
                return {**value, 'sprite_url': f'/games/{aid}/sprites/{dex}.png' if dex else None}
            return {'id': row['id'], 'phase': row['phase'], 'decision': row['decision'],
                    'updated_at': row['updated_at'], 'peer_id': peer, 'peer_name': names.get(peer, 'Another adventure'),
                    'sent': mon(detail['sent']), 'received': mon(detail['received']),
                    'failure_reason': self._failure_reason(row) if row['phase'] == 'aborted' else None,
                    'recovering': bool(row['error']) or row['phase'] == 'recovering'}
        return {'adventure': {key: game[key] for key in ('id', 'name', 'version', 'state', 'archived')},
                'active': [public(row) for row in self.registry.transactions(unresolved=True, adventure_id=aid)],
                'attention': self._attention(rows),
                'recent_failures': [public(row) for row in [r for r in rows if r['phase'] == 'aborted'][:5]],
                'history': [public(row) for row in [r for r in rows
                            if r['phase'] == 'completed' and r['decision'] == 'COMMIT'][:20]]}

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
            display_offers = {}
            selected_inventories = []
            selected_offers = []
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
                selected_offer = next(mon for mon in inventory['offers'] if mon.get('trade_key') == selection[side + '_key'])
                selected_inventories.append(inventory)
                selected_offers.append(selected_offer)
                display_offers[aid] = self._mon_display(selected_offer)
                campaigns[aid] = game['campaign_id']
            left, right = selected_inventories
            give, take = selected_offers
            if not self._last_copies_useful(give, take, self._benefit(left, take), self._benefit(right, give)):
                raise ValueError('A last copy needs a new Pokédex entry for its recipient or its evolution for its owner')
            plan = {**selection, 'participants': participants, 'campaign_ids': campaigns,
                    'attempt_id': identifier(), 'kind': 'cable_trade', 'display_offers': display_offers}
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
            speed=self.registry.setting('speed', 1),
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
                manifest['display'] = self._trade_display(row, prepared, manifest)
                with self.guard:
                    if self.closed.is_set() or self.registry.transaction(tid)['decision'] == 'ABORT':
                        raise RuntimeError('Exchange was cancelled before commitment')
                    self.registry.update_transaction(tid, phase='staging')
                    for aid in row['plan']['participants']:
                        peer = next(other for other in row['plan']['participants'] if other != aid)
                        result = manifest['participants'][aid]
                        receipt = self._request(aid, 'stage', {'id': tid, 'attempt_id': row['plan']['attempt_id'],
                            'plan_digest': row['plan']['plan_digest'], 'result': result, 'incoming': prepared[peer]['outgoing'],
                            'incoming_league_record': prepared[peer].get('outgoing_league_record')})
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
            try:
                self.manager.notifications.trade_completed(row, manifest.get('display') or {})
            except Exception:
                log.exception('Could not announce trade %s', tid)
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

    @staticmethod
    def _last_copies_useful(give, take, mine, theirs):
        def allowed(outgoing, incoming, owner_gain, recipient_gain):
            if not outgoing.get('last_copy') or recipient_gain >= 100:
                return True
            evolved = outgoing.get('arrived_dex')
            # A third game can swap its Kadabra for an already evolved Alakazam.
            # Its partner may know both, while the sender completes its own entry.
            return (owner_gain >= 100 and evolved is not None and evolved != outgoing.get('dex')
                    and incoming.get('arrived_dex', incoming.get('dex')) == evolved)
        return allowed(give, take, mine, theirs) and allowed(take, give, theirs, mine)

    def _refresh_collection_demand(self, inventories):
        missing = {aid: set(range(1, 152)) - set(inv.get('owned', [])) for aid, inv in inventories}
        totals = Counter(dex for entries in missing.values() for dex in entries)
        for aid, inventory in inventories:
            requests = {str(dex): count - int(dex in missing[aid]) for dex, count in totals.items()
                        if count > int(dex in missing[aid])}
            try:
                self._request(aid, 'collection_demand', {'requests': requests})
            except (RuntimeError, OSError):
                log.debug('Collection requests could not reach adventure %s', aid)

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
        campaigns = {game['id']: game['campaign_id'] for game in games}
        visits = self.registry.completed_trade_visits()
        recent_species = Counter()
        recent_games = Counter()
        for row in sorted(history, key=lambda item: item['updated_at'], reverse=True):
            if row['phase'] != 'completed' or row['decision'] != 'COMMIT':
                continue
            plan = row['plan']
            display = (row.get('result') or {}).get('display', {})
            for aid in plan['participants']:
                if (plan.get('campaign_ids', {}).get(aid) != campaigns.get(aid)
                        or recent_games[aid] >= 8):
                    continue
                recent_games[aid] += 1
                peer = next(other for other in plan['participants'] if other != aid)
                details = display.get(aid) or {}
                offers = plan.get('display_offers', {})
                species = {(details.get('sent') or offers.get(aid) or {}).get('dex'),
                           (details.get('received') or offers.get(peer) or {}).get('dex')}
                recent_species.update((aid, dex) for dex in species if dex is not None)
        for game in games:
            aid = game['id']
            if (game['state'] != 'running' or game['desired_state'] != 'running' or game['archived']
                    or game['version'] not in {'red', 'blue'} or (game.get('provenance') or {}).get('trading_blocked')):
                continue
            try:
                inventory = self.inventory(aid)
                if not inventory.get('holding'):
                    inventories.append((aid, inventory))
            except (RuntimeError, OSError):
                continue
        self._refresh_collection_demand(inventories)
        inventories = [(aid, inv) for aid, inv in inventories
                       if time.time() - last.get(aid, 0) >= COOLDOWN_SECONDS]
        candidates = []
        for index, (left_id, left) in enumerate(inventories):
            for right_id, right in inventories[index + 1:]:
                for give in left.get('offers', []):
                    for take in right.get('offers', []):
                        mine, theirs = self._benefit(left, take), self._benefit(right, give)
                        if not mine + theirs or not self._last_copies_useful(give, take, mine, theirs):
                            continue
                        # Do not circulate the same individual for repeat quality gains.
                        # A newly available Pokédex entry still justifies its return.
                        if ((left_id, campaigns[left_id], take.get('trade_key')) in visits and mine < 100
                                or (right_id, campaigns[right_id], give.get('trade_key')) in visits and theirs < 100):
                            continue
                        repetition = sum(recent_species[aid, dex] for aid, dex in {
                            (left_id, give.get('dex')), (left_id, take.get('arrived_dex', take.get('dex'))),
                            (right_id, take.get('dex')), (right_id, give.get('arrived_dex', give.get('dex')))})
                        rank = (mine + theirs, bool(mine and theirs), -repetition,
                                -max(last.get(left_id, 0), last.get(right_id, 0)),
                                -(give.get('level', 0) + take.get('level', 0)),
                                give.get('trade_key') or '', take.get('trade_key') or '')
                        candidates.append((rank, left_id, right_id, give['trade_key'], take['trade_key']))
        if candidates:
            _, left_id, right_id, left_key, right_key = max(candidates, key=lambda item: item[0])
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
