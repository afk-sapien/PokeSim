"""Explicit child launch, bounded health checks and restart policy."""
from __future__ import annotations

from collections import deque
from contextlib import nullcontext
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

import httpx

from .registry import digest, identifier
from ..runtime.settings import validate_speed

log = logging.getLogger(__name__)


class Child:
    def __init__(self, bootstrap, command=None):
        self.bootstrap = bootstrap
        self.token = bootstrap['token']
        self.generation = bootstrap['generation']
        self.notified = None
        self.process = None
        self.url = None
        self.logs = deque(maxlen=100)
        self.command = command or ([sys.executable, '--worker'] if getattr(sys, 'frozen', False)
                                   else [sys.executable, '-m', 'pokesim.runtime.worker'])
        self.ready = queue.Queue(maxsize=1)
        self.log_path = Path(bootstrap['settings']['data_dir']) / 'logs' / 'worker.log'

    def start(self, timeout=45):
        env = os.environ.copy()
        if not getattr(sys, 'frozen', False):
            root = str(Path(__file__).resolve().parents[2])
            env['PYTHONPATH'] = root + os.pathsep + env.get('PYTHONPATH', '')
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
        threading.Thread(target=self._stdout, daemon=True, name='worker-readiness').start()
        threading.Thread(target=self._stderr, daemon=True, name='worker-logs').start()
        try:
            self.process.stdin.write(json.dumps(self.bootstrap) + '\n')
            self.process.stdin.flush()
            message = self.ready.get(timeout=timeout)
            if (message.get('event') != 'ready' or message.get('protocol') != 1
                    or message.get('adventure_id') != self.bootstrap['adventure_id']
                    or message.get('generation') != self.generation
                    or message.get('host') != '127.0.0.1'
                    or type(message.get('port')) is not int or not 1 <= message['port'] <= 65535):
                raise RuntimeError(message.get('error') or 'Invalid worker readiness response')
            self.url = f"http://127.0.0.1:{message['port']}"
            return self
        except BaseException:
            try:
                self.stop(timeout=5)
            except RuntimeError:
                # stop() has already terminated the child. Reporting its shutdown
                # deadline here would bury the reason the worker never came up.
                log.warning('Worker for %s ignored the shutdown request after a failed start',
                            self.bootstrap['adventure_id'])
            raise

    def _stdout(self):
        while line := self.process.stdout.readline(16385):
            if len(line) > 16384:
                continue
            try:
                message = json.loads(line)
                if isinstance(message, dict) and message.get('event') in {'ready', 'error'}:
                    try:
                        self.ready.put_nowait(message)
                    except queue.Full:
                        pass
            except ValueError:
                self.logs.append(line[-2000:].rstrip())
        try:
            self.ready.put_nowait({'event': 'error', 'error': 'Worker exited before becoming ready'})
        except queue.Full:
            pass

    def _stderr(self):
        while line := self.process.stderr.readline(4097):
            self.logs.append(line[-4000:].rstrip())
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.log_path.exists() and self.log_path.stat().st_size > 2 * 1024 * 1024:
                    self.log_path.replace(self.log_path.with_suffix('.previous.log'))
                with self.log_path.open('a') as output:
                    output.write(line[-4000:])
            except OSError:
                pass

    def request(self, method, path, data=None, timeout=20):
        if not self.url or self.process.poll() is not None:
            raise RuntimeError('Adventure worker is not running')
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            response = client.request(method, self.url + path, json=data,
                                      headers={'Authorization': 'Bearer ' + self.token})
            if response.is_error:
                try:
                    detail = response.json().get('detail', response.text[:300])
                except ValueError:
                    detail = response.text[:300]
                raise RuntimeError(str(detail))
            return response.json()

    def stop(self, timeout=50):
        if self.process is None:
            return
        if self.process.poll() is None:
            if self.url:
                try:
                    self.request('POST', '/internal/shutdown', {}, timeout=2)
                except (OSError, RuntimeError, httpx.HTTPError):
                    pass
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=max(0.1, timeout))
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
                raise RuntimeError('Worker exceeded the shutdown deadline. Its previous safe save was retained.')
        if self.process.returncode not in (None, 0):
            raise RuntimeError(f'Worker exited with code {self.process.returncode}. Inspect its diagnostics.')


class Supervisor:
    def __init__(self, registry, assets, public_url, child_factory=Child):
        self.registry = registry
        self.assets = assets
        self.public_url = public_url.rstrip('/')
        self.child_factory = child_factory
        self.children = {}
        self.guard = threading.RLock()
        self.admission = threading.RLock()
        self.locks = {}
        self.retries = {}
        self.unhealthy_since = {}
        self.notifications = None   # installed by the manager: adventure row -> worker notification settings
        self.closed = threading.Event()
        self.thread = None

    def _lock(self, aid):
        with self.guard:
            return self.locks.setdefault(aid, threading.RLock())

    def child(self, aid):
        with self.guard:
            child = self.children.get(aid)
        if child is None or not child.url or child.process.poll() is not None:
            raise RuntimeError('This adventure is stopped or still starting')
        return child

    def start(self, aid, recovery=False):
        with self.admission, self._lock(aid):
            adventure = self.registry.adventure(aid)
            if self.closed.is_set():
                raise RuntimeError('PokeSim is shutting down')
            if not recovery and adventure['desired_state'] != 'running':
                return adventure
            if adventure['archived']:
                raise ValueError('Restore this adventure from the archive before starting')
            with self.guard:
                existing = self.children.get(aid)
                if existing and existing.process and existing.process.poll() is None:
                    return self.registry.update(aid, state='running' if existing.url else 'starting', error=None)
                if len(self.children) >= self.registry.setting('max_running', 2) and not recovery:
                    raise ValueError('The running adventure limit has been reached. Stop a game or change Settings.')
                generation = identifier()
                settings = {**adventure['settings'],
                            'speed': self.registry.setting('speed', 1),
                            'rom_path': str(self.assets.rom_path(adventure['rom_id'])),
                            'data_dir': str(self.registry.root / 'adventures' / aid),
                            'game_data_dir': str(self.assets.game_data_dir),
                            'public_url': self.public_url + f'/games/{aid}'}
                settings.pop('auto_start', None)
                bootstrap = dict(protocol=1, adventure_id=aid, generation=generation,
                                 token=secrets.token_urlsafe(32), settings=settings, adventure_name=adventure['name'])
                child = self.child_factory(bootstrap)
                self.children[aid] = child
                self.registry.update(aid, state='starting', generation=generation, error=None)
            try:
                self.assets.prepare(lambda message: self.registry.update(aid, summary={'setup': message}))
                child.start()
                try:
                    self.sync_notifications(aid, child)
                except Exception:
                    log.warning('Adventure %s will receive notification settings when it reconnects', aid)
                return self.registry.update(aid, state='recovering' if recovery else 'running', error=None)
            except Exception as error:
                with self.guard:
                    self.children.pop(aid, None)
                self.registry.update(aid, state='failed', error=str(error))
                raise

    def stop(self, aid, preserve_desired=False):
        with (nullcontext() if self.closed.is_set() else self.admission), self._lock(aid):
            self.registry.adventure(aid)
            if not preserve_desired:
                self.registry.update(aid, desired_state='stopped')
            with self.guard:
                child = self.children.get(aid)
            if child is None:
                return self.registry.update(aid, state='stopped')
            self.registry.update(aid, state='stopping')
            try:
                child.stop()
            except Exception as error:
                self.registry.update(aid, state='failed', error=str(error))
                raise
            finally:
                with self.guard:
                    self.children.pop(aid, None)
            return self.registry.update(aid, state='stopped', error=None)

    def set_speed(self, speed):
        speed = validate_speed(speed)
        with self.admission:
            self.registry.set_setting('speed', speed)
            with self.guard:
                children = list(self.children.items())
            pending = []
            for aid, child in children:
                try:
                    self._apply_speed(child, speed)
                except (RuntimeError, OSError, httpx.HTTPError):
                    pending.append(aid)
                    log.warning('Adventure %s will receive the global pace when it reconnects', aid)
            return pending

    @staticmethod
    def _apply_speed(child, speed):
        result = child.request('POST', '/internal/speed', {'speed': speed}, timeout=5)
        if result.get('speed') != speed:
            raise RuntimeError('Worker did not acknowledge the global pace')

    def sync_speed(self, aid, child, actual):
        with self.admission:
            if self.closed.is_set() or self.children.get(aid) is not child:
                return
            speed = self.registry.setting('speed', 1)
            if actual != speed:
                self._apply_speed(child, speed)

    def push_notifications(self):
        """Apply the Library notification settings to running adventures without restarting them."""
        with self.guard:
            children = list(self.children.items())
        pending = []
        for aid, child in children:
            try:
                self.sync_notifications(aid, child)
            except (RuntimeError, OSError, KeyError, httpx.HTTPError):
                pending.append(aid)
                log.warning('Adventure %s will receive notification settings when it reconnects', aid)
        return pending

    def sync_notifications(self, aid, child):
        if self.notifications is None or not child.url:
            return
        settings = self.notifications(self.registry.adventure(aid))
        fingerprint = digest(settings)
        if getattr(child, 'notified', None) != fingerprint:
            child.request('POST', '/internal/notifications', settings, timeout=5)
            child.notified = fingerprint

    def run_monitor(self):
        self.thread = threading.Thread(target=self._monitor, name='adventure-supervisor', daemon=True)
        self.thread.start()

    def _monitor(self):
        while not self.closed.wait(3):
            with self.guard:
                children = list(self.children.items())
            for aid, child in children:
                if self.closed.is_set():
                    break
                if child.process is None or not child.url:
                    continue
                if child.process.poll() is not None:
                    with self.admission, self._lock(aid):
                        with self.guard:
                            if self.children.get(aid) is not child:
                                continue
                            self.children.pop(aid)
                        adventure = self.registry.update(aid, state='failed', error='Adventure worker exited unexpectedly')
                    recent = [t for t in self.retries.get(aid, []) if time.monotonic() - t < 300]
                    self.retries[aid] = recent
                    unresolved = any(aid in row['plan'].get('participants', []) for row in self.registry.transactions(True))
                    if adventure['desired_state'] == 'running' and len(recent) < 3 and not unresolved:
                        recent.append(time.monotonic())
                        try:
                            self.start(aid)
                        except Exception:
                            log.exception('Could not restart adventure %s', aid)
                    continue
                try:
                    child.request('GET', '/healthz', timeout=3)
                    status = child.request('GET', '/api/state', timeout=3)
                    self.sync_speed(aid, child, status.get('speed'))
                    self.unhealthy_since.pop(aid, None)
                    game = status.get('game') or {}
                    summary = {'activity': game.get('map_name') or 'Adventure in progress',
                               'paused': status.get('paused', False),
                               'frame': status.get('frame'), 'playtime': game.get('playtime'),
                               'last_response': time.time(), 'league_rewards': status.get('league_rewards'),
                               'stalled': (status.get('progress') or {}).get('state') == 'stalled'}
                    current = self.registry.adventure(aid)
                    if current['generation'] == child.generation:
                        self.registry.update(aid, summary=summary)
                    try:
                        self.sync_notifications(aid, child)
                    except (RuntimeError, OSError, KeyError, httpx.HTTPError):
                        # Undelivered notification settings never make a healthy game look stale.
                        log.warning('Adventure %s has not accepted its notification settings yet', aid)
                except (RuntimeError, OSError, httpx.HTTPError):
                    since = self.unhealthy_since.setdefault(aid, time.monotonic())
                    log.warning('Adventure %s is not responding', aid)
                    if time.monotonic() - since >= 60 and not self.closed.is_set():
                        with self.admission, self._lock(aid):
                            if self.children.get(aid) is child:
                                self.registry.update(aid, state='failed', error='Adventure health remained stale for 60 seconds')
                                try:
                                    child.stop(timeout=5)
                                except RuntimeError:
                                    pass
                        self.unhealthy_since.pop(aid, None)

    def close(self):
        self.closed.set()
        self.assets.cancelled.set()
        with self.guard:
            ids = list(self.children)
        errors = []
        def stop_one(aid):
            try:
                self.stop(aid, preserve_desired=True)
            except Exception as error:
                errors.append(str(error))
        threads = [threading.Thread(target=stop_one, args=(aid,)) for aid in ids]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 58
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if self.thread:
            self.thread.join(timeout=4)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError('Some workers have not stopped. Application ownership is retained.')
        if self.thread and self.thread.is_alive():
            raise RuntimeError('Supervisor is still finishing a request. Application ownership is retained.')
        return errors
