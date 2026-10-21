"""Watch the library for problems an adventure cannot fix by itself, and tell the owner once.

The supervisor already polls every worker's /api/summary and keeps the latest one on the
child. The watchdog reads that copy, the registry and the trade records once a minute in its
own thread, so it never adds requests to a worker or work to the event loop.

Each problem has a key. The owner hears about a key when it starts and again when it clears,
and a key that comes back within the cooldown stays quiet. Problems found during the startup
grace period are tracked but never announced, so a restart does not repeat old alerts.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, fields
import logging
import os
import re
import threading
import time
import traceback

log = logging.getLogger(__name__)

SETTING = 'watchdog'
TRADE_WAITING = ('preparing', 'connecting')
# Failures the owner caused are not problems.
OWNER_FAILURES = ('Cancelled by the owner', 'Set aside for a trade you chose')


@dataclass(frozen=True)
class Limits:
    """Seconds unless the name says otherwise. Each one reads POKESIM_WATCHDOG_<NAME> in minutes."""
    interval: float = 60
    grace: float = 300
    down: float = 120
    stuck: float = 900
    no_progress: float = 3600
    trade_waiting: float = 600
    failure_window: float = 7200
    failure_repeats: int = 3
    error_quiet: float = 3600
    cooldown: float = 3600

    @classmethod
    def from_environment(cls, environ=None):
        environ = os.environ if environ is None else environ
        values = {}
        for item in fields(cls):
            raw = environ.get('POKESIM_WATCHDOG_' + item.name.upper(), '').strip()
            if not raw:
                continue
            try:
                number = float(raw)
            except ValueError:
                log.warning('Ignoring POKESIM_WATCHDOG_%s, which is not a number', item.name.upper())
                continue
            if number < 0 or (item.name == 'interval' and number <= 0):
                log.warning('Ignoring POKESIM_WATCHDOG_%s, which must be positive', item.name.upper())
                continue
            values[item.name] = int(number) if item.name == 'failure_repeats' else number * 60
        return cls(**values)


def enabled_by_environment(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get('POKESIM_WATCHDOG', '1').strip().lower() not in {'0', 'false', 'no', 'off'}


def duration(seconds):
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        return 'less than a minute'
    if minutes < 120:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    text = f'{hours} hours'
    return text + (f" and {rest} minute{'s' if rest != 1 else ''}" if rest else '')


def normalise_failure(error):
    """Compare trade errors without the ids, numbers and spacing that differ between attempts."""
    text = re.sub(r'\(adventure [0-9a-f]{32}\)', '', error or '')
    text = re.sub(r'[0-9a-f]{32}', '', text)
    text = re.sub(r'\d+(?:\.\d+)?', 'N', text)
    return re.sub(r'\s+', ' ', text).strip(' .').lower()


PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace('\\', '/') + '/'


def _ours(filename):
    return filename.replace('\\', '/').startswith(PACKAGE)


def _short_path(filename):
    path = filename.replace('\\', '/')
    return 'pokesim/' + path[len(PACKAGE):] if path.startswith(PACKAGE) else path.rsplit('/', 1)[-1]


def error_signature(kind, frames):
    """Group an exception by its type and where it was raised, preferring PokeSim's own code."""
    ours = [frame for frame in frames if _ours(frame[0])]
    filename, line, function = (ours or frames or [('unknown', 0, '?')])[-1]
    return f'{kind} in {_short_path(filename)} line {line} ({function})'


class TracebackReader:
    """Find Python tracebacks in a worker's stderr, one line at a time."""
    FRAME = re.compile(r'\s+File "(.+)", line (\d+), in (.+)')
    END = re.compile(r'([A-Za-z_][\w.]*)(?::|$)')

    def __init__(self, report):
        self.report = report
        self.frames = None

    def feed(self, line):
        text = line.rstrip('\r\n')
        if text.strip() == 'Traceback (most recent call last):':
            self.frames = []
            return
        if self.frames is None:
            return
        frame = self.FRAME.match(text)
        if frame:
            self.frames.append((frame[1], int(frame[2]), frame[3].strip()))
            return
        if not text.strip() or text[:1].isspace():
            return
        if text.startswith(('During handling of', 'The above exception')):
            self.frames = None
            return
        end = self.END.match(text)
        frames, self.frames = self.frames, None
        if end and frames:
            self.report(end[1].rsplit('.', 1)[-1], frames)


class ErrorLog:
    """Unhandled errors from the manager's own logs, its threads and every worker's stderr."""

    def __init__(self, clock=time.time, keep=500):
        self.clock = clock
        self.rows = deque(maxlen=keep)
        self.guard = threading.Lock()
        self.readers = {}

    def record(self, signature, source=None):
        with self.guard:
            self.rows.append((self.clock(), signature, source))

    def record_exception(self, kind, tb, source=None):
        frames = [(frame.filename, frame.lineno, frame.name) for frame in traceback.extract_tb(tb)]
        self.record(error_signature(kind, frames), source)

    def worker_line(self, aid, line):
        with self.guard:
            reader = self.readers.get(aid)
            if reader is None:
                reader = self.readers[aid] = TracebackReader(
                    lambda kind, frames: self.rows.append((self.clock(), error_signature(kind, frames), aid)))
            reader.feed(line)

    def since(self, moment):
        with self.guard:
            return [row for row in self.rows if row[0] >= moment]


class _LogHandler(logging.Handler):
    def __init__(self, errors):
        super().__init__(logging.ERROR)
        self.errors = errors

    def emit(self, record):
        # The root logger and Uvicorn's own logger can both see one record.
        if not record.exc_info or not record.exc_info[2] or getattr(record, '_watchdog_seen', False):
            return
        if record.name.startswith(__name__):
            return
        record._watchdog_seen = True
        try:
            self.errors.record_exception(record.exc_info[0].__name__, record.exc_info[2])
        except Exception:  # noqa: BLE001
            pass


@dataclass
class Problem:
    key: str
    kind: str
    message: str
    since: float
    adventure_id: str | None = None
    recovered: str = ''
    announce: bool = True
    alerted: bool = False
    adopted: bool = False   # first seen during the startup grace period


@dataclass
class Progress:
    fingerprint: tuple
    since: float
    maps: set = field(default_factory=set)


class Watchdog:
    def __init__(self, manager, *, clock=time.time, limits=None, environ=None):
        self.manager = manager
        self.clock = clock
        self.limits = limits or Limits.from_environment(environ)
        self.environ = environ
        self.started = clock()
        self.errors = ErrorLog(clock)
        self.problems = {}
        self.alerted_at = {}
        self.down_since = {}
        self.progress = {}
        self.phases = {}
        self.guard = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None
        self.deliveries = deque(maxlen=20)   # recent sends, so tests can wait for them
        self.handler = None
        self.previous_hook = None

    # Settings ---------------------------------------------------------------------------
    def enabled(self):
        saved = self.manager.registry.setting(SETTING)
        if isinstance(saved, dict) and type(saved.get('enabled')) is bool:
            return saved['enabled']
        return enabled_by_environment(self.environ)

    def set_enabled(self, value):
        if type(value) is not bool:
            raise ValueError('enabled must be a boolean')
        self.manager.registry.set_setting(SETTING, {'enabled': value})
        if not value:
            with self.guard:
                self.problems.clear()
        return self.public()

    def public(self):
        enabled = self.enabled()
        with self.guard:
            rows = sorted(self.problems.values(), key=lambda row: row.since) if enabled else []
            return {'enabled': enabled,
                    'problems': [{'kind': row.kind, 'adventure_id': row.adventure_id, 'message': row.message,
                                  'since': row.since} for row in rows]}

    # Lifecycle ----------------------------------------------------------------------------
    def install(self):
        """Collect unhandled errors from the manager. Only a running application does this."""
        self.handler = _LogHandler(self.errors)
        logging.getLogger().addHandler(self.handler)
        uvicorn = logging.getLogger('uvicorn')
        if not uvicorn.propagate:
            uvicorn.addHandler(self.handler)
        self.previous_hook = threading.excepthook

        def hook(args, previous=self.previous_hook):
            if args.exc_type is not None and args.exc_traceback is not None and not issubclass(args.exc_type, SystemExit):
                self.errors.record_exception(args.exc_type.__name__, args.exc_traceback)
            previous(args)
        threading.excepthook = hook
        self.manager.supervisor.worker_output = self.errors.worker_line

    def uninstall(self):
        if self.handler is not None:
            logging.getLogger().removeHandler(self.handler)
            logging.getLogger('uvicorn').removeHandler(self.handler)
            self.handler = None
        if self.previous_hook is not None:
            threading.excepthook = self.previous_hook
            self.previous_hook = None

    def run(self):
        self.started = self.clock()
        self.thread = threading.Thread(target=self._loop, name='library-watchdog', daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopped.wait(self.limits.interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception('The watchdog check failed')

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.uninstall()

    # Checks -------------------------------------------------------------------------------
    def tick(self, now=None):
        now = self.clock() if now is None else now
        manager = self.manager
        if manager.closing or manager.suspended:
            return []
        if not self.enabled():
            with self.guard:
                self.problems.clear()
            return []
        found = {}
        names = {}
        for row in manager.registry.adventures():
            names[row['id']] = row['name']
            if not row['archived'] and row['state'] != 'deleting':
                self._adventure(row, now, found)
        for aid in set(self.down_since) - set(names):
            self.down_since.pop(aid, None)
        for aid in set(self.progress) - set(names):
            self.progress.pop(aid, None)
        self._trades(names, now, found)
        self._errors(names, now, found)
        return self._reconcile(found, now)

    def _child_status(self, aid, now):
        children = self.manager.supervisor.children
        child = children.get(aid)
        if child is None or child.process is None or child.process.poll() is not None:
            return None, False
        seen = getattr(child, 'watch', None)
        if not seen or now - seen[0] > max(180, 3 * self.limits.interval):
            return None, True
        return seen[1], True

    def _adventure(self, row, now, found):
        aid, name = row['id'], row['name']
        if row['desired_state'] != 'running':
            # The owner stopped it. Nothing about it is a problem until they start it again.
            self.down_since.pop(aid, None)
            self.progress.pop(aid, None)
            return
        reserved = self.manager.coordinator.reserved(aid)
        status, alive = self._child_status(aid, now)
        if not alive and not reserved and row['state'] in {'failed', 'stopped', 'running'}:
            since = self.down_since.setdefault(aid, now)
            if now - since >= self.limits.down:
                found[f'down:{aid}'] = Problem(
                    f'down:{aid}', 'down', f'{name} stopped unexpectedly and has not been running for {duration(now - since)}.',
                    since, aid, f'{name} is running again.')
            self.progress.pop(aid, None)
            return
        self.down_since.pop(aid, None)
        if status is None:
            return
        summary = row.get('summary') or {}
        if reserved or status.get('paused') or status.get('manual_mode') or summary.get('trading'):
            # A pause, manual play or a trade holds the game still on purpose.
            self.progress.pop(aid, None)
            return
        game = status.get('game') or {}
        place = game.get('map_name') or 'the same place'
        stuck = status.get('stuck_seconds')
        stuck_now = isinstance(stuck, (int, float)) and stuck >= self.limits.stuck
        if stuck_now:
            found[f'stuck:{aid}'] = Problem(
                f'stuck:{aid}', 'stuck', f'{name} has been stuck in {place} for {duration(stuck)}.',
                now - stuck, aid, f'{name} is moving again.')
        if self._quiet(aid, status, now) and not stuck_now:
            since = self.progress[aid].since
            found[f'progress:{aid}'] = Problem(
                f'progress:{aid}', 'no_progress',
                f'{name} has made no progress for {duration(now - since)}. It is still playing in {place}.',
                since, aid, f'{name} is making progress again.')
        help_request = status.get('help_request')
        if isinstance(help_request, dict):
            reason = str(help_request.get('reason') or 'It needs a hand').rstrip('.')
            # The worker already sends a Stuck notification at the same moment, so this only shows.
            found[f'help:{aid}'] = Problem(f'help:{aid}', 'help_request', f'{name} asked for help. {reason}.',
                                           now, aid, announce=False)

    def _quiet(self, aid, status, now):
        """True when the game kept running for the whole window without doing anything new.

        Moving around does not count, because a game caught in a loop moves too. New events,
        Pokédex entries, badges, League wins, newly discovered areas and maps not seen during
        this window do.
        """
        watch = status.get('watch') or {}
        achievement = (status.get('progress') or {}).get('last_achievement') or {}
        fingerprint = (achievement.get('id'), watch.get('owned'), watch.get('badges'), watch.get('hall_of_fame'),
                       (status.get('league_rewards') or {}).get('wins'), status.get('areas_discovered'))
        place = watch.get('map', (status.get('game') or {}).get('map_name'))
        current = self.progress.get(aid)
        if current is None or current.fingerprint != fingerprint:
            self.progress[aid] = Progress(fingerprint, now, {place})
            return False
        if place not in current.maps:
            current.maps.add(place)
            current.since = now
            return False
        return now - current.since >= self.limits.no_progress

    def _trades(self, names, now, found):
        registry = self.manager.registry
        live = set()
        for row in registry.transactions(unresolved=True):
            tid, phase = row['id'], row['phase']
            live.add(tid)
            previous = self.phases.get(tid)
            if previous is None or previous[0] != phase:
                # The record changes updated_at with each phase, so it dates the first sighting.
                self.phases[tid] = previous = (phase, row['updated_at'] if previous is None else now)
            if phase in TRADE_WAITING and now - previous[1] >= self.limits.trade_waiting:
                pair = ' and '.join(names.get(aid, 'another adventure') for aid in row['plan'].get('participants', ()))
                found[f'trade:{tid}'] = Problem(
                    f'trade:{tid}', 'trade_waiting',
                    f'The trade between {pair} has been {phase} for {duration(now - previous[1])}.',
                    previous[1], None, f'The trade between {pair} moved on.')
        for tid in set(self.phases) - live:
            self.phases.pop(tid)
        from .coordinator import Coordinator
        groups = {}
        for row in registry.transactions():
            if row['phase'] != 'aborted' or row['updated_at'] < now - self.limits.failure_window:
                continue
            error = row.get('error') or ''
            if any(text in error for text in OWNER_FAILURES):
                continue
            groups.setdefault(normalise_failure(error), []).append(row)
        for signature, rows in groups.items():
            if len(rows) < max(1, self.limits.failure_repeats):
                continue
            reason = Coordinator._generic_failure_reason(rows[0])
            key = 'trade-failure:' + signature
            found[key] = Problem(
                key, 'trade_failures',
                f'Trades failed the same way {len(rows)} times in the last {duration(self.limits.failure_window)}. {reason}',
                min(row['updated_at'] for row in rows), None, 'Trades stopped failing the same way.')

    def _errors(self, names, now, found):
        rows = self.errors.since(now - self.limits.error_quiet)
        groups = {}
        for moment, signature, source in rows:
            groups.setdefault(signature, []).append((moment, source))
        for signature, seen in groups.items():
            sources = {source for _, source in seen}
            where = ' and '.join(sorted(names.get(source, 'an adventure') for source in sources if source))
            origin = f'{where} logged' if where and None not in sources else 'PokeSim logged'
            count = f" It happened {len(seen)} times in the last {duration(self.limits.error_quiet)}." if len(seen) > 1 else ''
            key = 'error:' + signature
            found[key] = Problem(key, 'error', f'{origin} an unexpected error: {signature}.{count}',
                                 min(moment for moment, _ in seen), recovered='', announce=True)

    # Alerts -------------------------------------------------------------------------------
    def _reconcile(self, found, now):
        sent = []
        in_grace = now - self.started < self.limits.grace
        with self.guard:
            for key, problem in found.items():
                current = self.problems.get(key)
                if current is not None:
                    problem.alerted, problem.adopted = current.alerted, current.adopted
                    problem.since = min(problem.since, current.since)
                else:
                    problem.adopted = in_grace
                # A problem older than this start was most likely announced before the restart.
                inherited = problem.adopted and problem.since < self.started
                if problem.announce and not problem.alerted and not in_grace and not inherited:
                    last = self.alerted_at.get(key)
                    if last is None or now - last >= self.limits.cooldown:
                        problem.alerted = True
                        self.alerted_at[key] = now
                        sent.append((problem, False))
                self.problems[key] = problem
            for key in [key for key in self.problems if key not in found]:
                problem = self.problems.pop(key)
                if problem.alerted and problem.recovered:
                    sent.append((problem, True))
        for problem, recovered in sent:
            self._send(problem, recovered)
        return sent

    def _send(self, problem, recovered):
        center = self.manager.notifications
        title = 'Recovered' if recovered else 'Needs attention'
        try:
            thread = center.alert(title, problem.recovered if recovered else problem.message,
                                  adventure_id=problem.adventure_id)
            if thread is not None:
                self.deliveries.append(thread)
        except Exception:  # noqa: BLE001
            log.warning('The watchdog could not send its %s note', title.lower())
