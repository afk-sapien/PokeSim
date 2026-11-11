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
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import traceback

from . import progress_sweep
from .errors import Conflict
from .loops import Loop

log = logging.getLogger(__name__)

SETTING = 'watchdog'
# The current problems, kept in the data directory for a watch outside the app (tools/alert_watch.py).
PROBLEMS_FILE = 'watchdog-problems.json'
TRADE_WAITING = ('preparing', 'connecting')
# Failures the owner caused are not problems.
OWNER_FAILURES = ('Cancelled by the owner', 'Set aside for a trade you chose')


@dataclass(frozen=True)
class Limits:
    """Real seconds unless the name says otherwise. Each one reads POKESIM_WATCHDOG_<NAME> in minutes,
    except the count and the gigabytes, which read as they are."""
    interval: float = 60
    grace: float = 300
    down: float = 120
    stuck: float = 900
    # Seconds of play, from the worker's PlayClock, so the game's pace and a pause never count.
    no_progress: float = 3600
    # The one check on real time: how long PlayClock may stand still while the adventure runs.
    not_live: float = 900
    trade_waiting: float = 600
    failure_window: float = 7200
    failure_repeats: int = 3
    error_quiet: float = 3600
    cooldown: float = 3600
    sweep: float = 300
    disk_free_gb: float = 10

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
            values[item.name] = (int(number) if item.name == 'failure_repeats' else
                                 number if item.name == 'disk_free_gb' else number * 60)
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
    since: float     # real time, for the problem's date
    played: int      # PlayClock seconds, which the window counts
    maps: set = field(default_factory=set)


def played(status):
    """The PlayClock seconds a worker's status reports, or None without them."""
    seconds = ((status or {}).get('play_clock') or {}).get('seconds')
    return seconds if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else None


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
        self.readings = {}   # adventure id -> (read at, progress_sweep.Reading or None)
        self.held = {}       # adventure id -> the last check that found it stopped, down or held still
        self.moved = {}      # adventure id -> (PlayClock seconds, the real time they last changed)
        self.phases = {}
        self.guard = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None
        self.loop = None
        self.deliveries = deque(maxlen=20)   # recent sends, so tests can wait for them
        self.handler = None
        self.previous_hook = None
        self._published = None

    # Settings ---------------------------------------------------------------------------
    def enabled(self):
        saved = self.manager.registry.setting(SETTING)
        if isinstance(saved, dict) and type(saved.get('enabled')) is bool:
            return saved['enabled']
        return enabled_by_environment(self.environ)

    def set_enabled(self, value):
        if type(value) is not bool:
            raise Conflict('enabled must be a boolean')
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
        self.loop = Loop('library-watchdog', self.tick, self.limits.interval, self.stopped.wait, logger=log)
        self.thread = self.loop.start()

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
            self._publish()
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
        for table in (self.readings, self.held, self.moved):
            for aid in set(table) - set(names):
                table.pop(aid, None)
        self._trades(names, now, found)
        self._errors(names, now, found)
        self._disk(now, found)
        sent = self._reconcile(found, now)
        self._publish()
        return sent

    def _publish(self):
        """Write the problems the main page shows, only when they change, so a watch can read them
        without logging in."""
        root = getattr(self.manager, 'root', None)
        if root is None:
            return
        with self.guard:
            rows = sorted(self.problems.values(), key=lambda row: row.since)
            text = json.dumps([{'key': row.key, 'kind': row.kind, 'adventure_id': row.adventure_id,
                                'message': row.message, 'since': row.since} for row in rows], sort_keys=True)
        if text == self._published:
            return
        path = os.path.join(root, PROBLEMS_FILE)
        try:
            with open(path + '.tmp', 'w', encoding='utf-8') as handle:
                handle.write(text)
            os.replace(path + '.tmp', path)
            self._published = text
        except OSError:
            log.warning('The watchdog could not write %s', PROBLEMS_FILE)

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
            self.moved.pop(aid, None)
            self.held[aid] = now
            return
        reserved = self.manager.coordinator.reserved(aid)
        status, alive = self._child_status(aid, now)
        if not alive and not reserved and row['state'] in {'failed', 'stopped', 'running'}:
            since = self.down_since.setdefault(aid, now)
            if now - since >= self.limits.down:
                found[f'down:{aid}'] = Problem(
                    f'down:{aid}', 'down', f'{name} stopped unexpectedly and has not been running for {duration(now - since)}.',
                    since, aid, f'{name} is running again.')
            # A worker that is down is the down alert's, so the clock that it stands still starts again.
            self.progress.pop(aid, None)
            self.moved.pop(aid, None)
            self.held[aid] = now
            return
        self.down_since.pop(aid, None)
        summary = row.get('summary') or {}
        if status is None:
            # A worker that stops answering counts as standing still, unless a trade holds it.
            if reserved or summary.get('trading'):
                self.moved.pop(aid, None)
            else:
                self._live(row, None, now, found)
            return
        rating = status.get('rating_problem')
        if isinstance(rating, str) and rating:
            # Checked before a pause returns, since a paused game still cannot rate its PC.
            found[f'rating:{aid}'] = Problem(
                f'rating:{aid}', 'rating',
                f'{name} cannot rate its PC, so it releases nothing. {rating.rstrip(".")}. Restart it once the cartridge reads.',
                now, aid, f'{name} rates its PC again.')
        if reserved or status.get('paused') or status.get('manual_mode') or summary.get('trading'):
            # A pause, manual play or a trade holds the game still on purpose.
            self.progress.pop(aid, None)
            self.moved.pop(aid, None)
            self.held[aid] = now
            return
        self._live(row, status, now, found)
        self._stalled(row, now, found, status)
        game = status.get('game') or {}
        place = game.get('map_name') or 'the same place'
        stuck = status.get('stuck_seconds')
        stuck_now = isinstance(stuck, (int, float)) and stuck >= self.limits.stuck
        if stuck_now:
            found[f'stuck:{aid}'] = Problem(
                f'stuck:{aid}', 'stuck', f'{name} has been stuck in {place} for {duration(stuck)}.',
                now - stuck, aid, f'{name} is moving again.')
        if self._quiet(aid, status, now) and not stuck_now:
            window = self.progress[aid]
            found[f'progress:{aid}'] = Problem(
                f'progress:{aid}', 'no_progress',
                f'{name} has made no progress for {duration(played(status) - window.played)} of play. '
                f'It is still playing in {place}.',
                window.since, aid, f'{name} is making progress again.')
        help_request = status.get('help_request')
        if isinstance(help_request, dict):
            reason = str(help_request.get('reason') or 'It needs a hand').rstrip('.')
            # The worker already sends a Stuck notification at the same moment, so this only shows.
            found[f'help:{aid}'] = Problem(f'help:{aid}', 'help_request', f'{name} asked for help. {reason}.',
                                           now, aid, announce=False)

    def _live(self, row, status, now, found):
        """While an adventure runs, its PlayClock must advance. This is the one check on real time
        (goal system, section 6), since a hung worker plays no frames for any frame clock to count.
        A worker that stops answering counts as standing still. Not live is not a stall and climbs
        no reload ladder. A worker restart fixes it."""
        aid, name = row['id'], row['name']
        seconds = played(status)
        last = self.moved.get(aid)
        if last is None or (seconds is not None and seconds != last[0]):
            self.moved[aid] = last = (seconds, now)
        still = now - last[1]
        if still >= self.limits.not_live:
            found[f'live:{aid}'] = Problem(
                f'live:{aid}', 'not_live',
                f'{name} has stopped playing. Its game clock has not moved for {duration(still)}. Restart it.',
                last[1], aid, f'{name} is playing again.')

    def _quiet(self, aid, status, now):
        """True when the game played the whole window without doing anything new. The window counts
        PlayClock seconds, so the game's pace does not change it.

        Moving around does not count, because a game caught in a loop moves too. New events,
        Pokédex entries, badges, League wins, newly discovered areas and maps not seen during
        this window do.
        """
        seconds = played(status)
        if seconds is None:
            return False
        watch = status.get('watch') or {}
        achievement = (status.get('progress') or {}).get('last_achievement') or {}
        fingerprint = (achievement.get('id'), watch.get('owned'), watch.get('badges'), watch.get('hall_of_fame'),
                       (status.get('league_rewards') or {}).get('wins'), status.get('areas_discovered'))
        place = watch.get('map', (status.get('game') or {}).get('map_name'))
        current = self.progress.get(aid)
        if current is None or current.fingerprint != fingerprint:
            self.progress[aid] = Progress(fingerprint, now, seconds, {place})
            return False
        if place not in current.maps:
            current.maps.add(place)
            current.since, current.played = now, seconds
            return False
        return seconds - current.played >= self.limits.no_progress

    def _stalled(self, row, now, found, status=None):
        """Read the adventure's progress table and journal every few minutes (progress_sweep.py). Time
        spent stopped, down or held still never counts toward a stall. Two stall entries at one place
        within an hour count at once, and so does a day with every box full and nothing caught."""
        root = getattr(self.manager, 'root', None)
        if root is None:
            return
        aid, name = row['id'], row['name']
        cached = self.readings.get(aid)
        if cached is None or now - cached[0] >= self.limits.sweep:
            path = os.path.join(root, 'adventures', aid, 'pokesim.sqlite')
            try:
                reading = progress_sweep.read(path, progress_sweep.generation(row.get('version')))
            except sqlite3.Error:
                reading = cached[1] if cached else None
            self.readings[aid] = cached = (now, reading)
        reading = cached[1]
        if reading is None:
            return
        repeat = progress_sweep.repeated(reading.stalls, now)
        if repeat:
            place, first, count = repeat
            found[f'repeat_stall:{aid}'] = Problem(
                f'repeat_stall:{aid}', 'repeat_stall',
                f'{name} got stuck {count} times at {place} within {duration(now - first)}.',
                first, aid, f'{name} has not been stuck at {place} again for an hour.')
        watch = (status or {}).get('watch') or {}
        caught = max(reading.caught, self.held.get(aid, 0))
        if watch.get('boxes_full') and now - caught >= progress_sweep.CATCH_QUIET:
            found[f'boxes_full:{aid}'] = Problem(
                f'boxes_full:{aid}', 'boxes_full',
                f'{name} has full boxes and has caught nothing for {duration(now - caught)}.',
                caught, aid, f'{name} has room to catch again.')
        since = max(reading.last, self.held.get(aid, 0))
        if now - since < reading.limit:
            return
        if reading.postgame:
            missing = 'a League win, a Pokédex change or a level up'
        else:
            missing = f'a badge, a new area, a new Pokédex entry or a League win, at {reading.badges} badges'
        found[f'stalled:{aid}'] = Problem(
            f'stalled:{aid}', 'stalled', f'{name} has gone {duration(now - since)} without {missing}.',
            since, aid, f'{name} is making real progress again.')

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

    def _disk(self, now, found):
        """Saves, journals and backups stop being written once the data folder fills up."""
        root = getattr(self.manager, 'root', None)
        if root is None or not self.limits.disk_free_gb:
            return
        try:
            free = shutil.disk_usage(root).free / 1e9
        except OSError:
            return
        if free < self.limits.disk_free_gb:
            found['disk'] = Problem(
                'disk', 'disk', f'The data folder has {free:.1f} GB free, under {self.limits.disk_free_gb:g} GB. '
                'Free some space before saves and backups fail.', now, recovered='The data folder has room again.')

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
