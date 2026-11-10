"""Background loops in the manager that log every failure and say when they stop.

A loop runs its body every few seconds on a daemon thread. A body that raises is logged with its
traceback and the loop goes on. The same failure in the same place is logged again at most once a
minute, with the number of times it failed in between. Each loop keeps a heartbeat, the time it
last made progress, so /health/ready can name a loop whose thread died or that stopped moving.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import threading
import time

log = logging.getLogger(__name__)

REPEAT_SECONDS = 60   # a failure that keeps happening is logged once a minute


class Throttle:
    """Log a failure with its traceback, and the same failure in the same place at most once a minute."""

    def __init__(self, logger=log, clock=time.monotonic, every=REPEAT_SECONDS):
        self.logger = logger
        self.clock = clock
        self.every = every
        self.lock = threading.Lock()
        self.seen = {}   # (place, error type) -> [time last logged, failures not logged since]

    def failed(self, place, error):
        """Log `error` raised in `place` unless the same failure was logged under a minute ago.
        Returns True when it wrote a log line."""
        key = (place, type(error).__qualname__)
        now = self.clock()
        with self.lock:
            entry = self.seen.get(key)
            if entry is not None and now - entry[0] < self.every:
                entry[1] += 1
                return False
            hidden = entry[1] if entry is not None else 0
            # Failures that stopped happening drop out, so the table stays small.
            for old in [old for old, (logged, count) in self.seen.items()
                        if not count and now - logged >= self.every]:
                del self.seen[old]
            self.seen[key] = [now, 0]
        more = f', and {hidden} more times since the last report' if hidden else ''
        self.logger.error('%s failed%s', place, more, exc_info=(type(error), error, error.__traceback__))
        return True


class Loop:
    """Run `body` every `interval` seconds on a daemon thread until `wait` says to stop.

    `interval` is a number of seconds, or a function that returns one and is read before each
    wait. `wait(seconds)` works like Event.wait and returns True when the loop should end. With
    `first` the body runs once before the first wait. `stale` is how many seconds may pass without
    a heartbeat before readiness names the loop. Bodies that do long work call `beat` as they go.
    """

    def __init__(self, name, body, interval, wait, *, first=False, stale=None, logger=log,
                 clock=time.monotonic):
        self.name = name
        self.body = body
        self.interval = interval
        self.wait = wait
        self.first = first
        self.stale = stale
        self.logger = logger
        self.clock = clock
        self.failures = Throttle(logger, clock)
        self.thread = None
        self.heartbeat = None
        self.finished = False   # the loop ended because it was told to

    def start(self):
        """Start the thread once. A second call while it runs returns the same thread."""
        if self.thread is not None and self.thread.is_alive():
            return self.thread
        self.finished = False
        self.beat()
        self.thread = threading.Thread(target=self.run, name=self.name, daemon=True)
        self.thread.start()
        return self.thread

    def run(self):
        try:
            if self.first:
                self.once()
            while not self.wait(self.interval() if callable(self.interval) else self.interval):
                self.once()
            self.finished = True
        except BaseException:
            # Only an error from wait itself or one that is not an Exception gets here.
            self.logger.critical('The %s loop stopped', self.name, exc_info=True)
            raise

    def once(self):
        with self.guard(self.name):
            self.body()
        self.beat()

    def beat(self):
        self.heartbeat = self.clock()

    @contextmanager
    def guard(self, place):
        """Log and swallow an Exception raised inside, so one failing step never ends the loop."""
        try:
            yield
        except Exception as error:  # noqa: BLE001
            self.failures.failed(place, error)

    def problem(self, now=None):
        """Why readiness fails because of this loop, or None. A loop that never started or that
        was told to stop is not a problem."""
        thread = self.thread
        if thread is None or self.finished:
            return None
        if not thread.is_alive():
            return f'{self.name} stopped'
        if self.stale is not None and self.heartbeat is not None:
            age = (self.clock() if now is None else now) - self.heartbeat
            if age > self.stale:
                return f'{self.name} has made no progress for {age:.0f} seconds'
        return None


def problems(loops, now=None):
    """Readiness problems of the loops given, in order."""
    found = (loop.problem(now) for loop in loops if loop is not None)
    return [problem for problem in found if problem]
