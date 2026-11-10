"""Ground truth for the progress replay, for both generations (docs/design/goal-system.md, section 12).

Each stall bundle, help request and restart writes one row to ``stall_truth`` in the adventure's own
pokesim.sqlite. A bundle folder is pruned to the newest few, but its row stays. A new game keeps every
row, since the replay reads the whole history of the adventure. Nothing reads the rows for a decision.

``kind`` is ``bundle``, ``help`` or ``restart``. ``source`` says who caused a restart: ``owner`` for an
action on a page, ``supervisor`` when a worker that exited is started again, and ``boot`` when the app
starts the adventures that were running. Other details go in ``detail_json``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import closing
from pathlib import Path

from . import progress_events
from .state import connect, journal, kv

log = logging.getLogger(__name__)

KINDS = frozenset({'bundle', 'help', 'restart'})
# Both generations ask for help with these words, so the start of the reason names the request.
LOOP = 'The run is caught in a loop'


def record(db, kind, *, frame=None, source='', **detail):
    """Write one row inside the caller's transaction. The table comes from the schema version
    (pokesim.state)."""
    if kind not in KINDS:
        raise ValueError(f'Unknown stall truth kind {kind!r}')
    journal.add_stall_truth(db, frame, time.time(), kind, source or '', json.dumps(detail, sort_keys=True, default=str))


def write(store, kind, *, source='', **detail):
    """Write one row in a transaction of its own, at the adventure's PlayClock frame."""
    try:
        with store.transaction() as db:
            record(db, kind, frame=progress_events.frame(store), source=source, **detail)
    except Exception:
        # A label for the replay must never cost the adventure its stall bundle or its status.
        log.exception('Cannot record the %s row for the progress replay', kind)


def bundle(store, folder, report):
    """The row for a stall bundle just written to ``folder``."""
    objective = report.get('objective') or {}
    goal = (objective.get('key') or objective.get('id') or '') if isinstance(objective, dict) else ''
    # A bundle from before captures named their trigger was kept by the quiet check of StallWatch.
    write(store, 'bundle', folder=Path(folder).name, reason=report.get('reason') or '',
          stall=report.get('kind') or report.get('rung') or 'quiet', goal=goal,
          quiet_game_minutes=report.get('quiet_game_minutes'), map=report.get('map') or '')


def help_kind(request):
    """What a help request is about, which stays the same while it lasts."""
    if not isinstance(request, dict):
        return None
    reason = str(request.get('reason') or '')
    from .pcvalue import BOXES_FULL
    return 'loop' if reason.startswith(LOOP) else 'boxes_full' if reason == BOXES_FULL else 'stall'


class HelpWatch:
    """Writes a ``help`` row when a request starts, or turns into another kind, between status polls."""

    def __init__(self):
        self.kind = None
        self.lock = threading.Lock()

    def observe(self, store, request):
        kind = help_kind(request)
        with self.lock:
            if kind == self.kind:
                return
            self.kind = kind
        if kind:
            write(store, 'help', request=kind, reason=request.get('reason') or '', action=request.get('action') or '')


def observe_help(emulator, request):
    """Note ``request`` from either generation's status and return it unchanged."""
    watch = emulator.__dict__.setdefault('help_watch', HelpWatch())
    store = getattr(emulator, 'store', None)
    if store is not None:
        watch.observe(store, request)
    return request


def lifecycle(folder, action, source, **detail):
    """A ``restart`` row written by the app while the adventure's worker is not running.

    The row goes in the adventure's own pokesim.sqlite, so a copy of the data folder holds all of its
    ground truth. An adventure that has never run has no database yet and nothing to label, so it is
    skipped rather than given an empty one. The frame is the PlayClock the worker last saved.
    """
    path = Path(folder) / 'pokesim.sqlite'
    if not path.is_file():
        return
    try:
        with closing(connect(path, timeout=5)) as db, db:
            clock = kv.get(db, 'play_clock')
            frame = clock.get('frames') if isinstance(clock, dict) else None
            record(db, 'restart', frame=frame, source=source, action=action, **detail)
    except Exception:
        log.exception('Cannot record the %s of %s for the progress replay', action, Path(folder).name)


def rows(db, kind=None):
    """Every row, oldest first, with its detail decoded, as the replay reads them."""
    return [{'id': r[0], 'frame': r[1], 'ts': r[2], 'kind': r[3], 'source': r[4], **json.loads(r[5])}
            for r in journal.stall_truth(db, kind)]
