"""Keep a stall bundle at every trigger: the quiet check, a give-up, a loop, a ladder gate or a ladder stall.

A bundle holds the save kept from before the stall, the trace segments from that save on, the moment
the stall was noticed and a report. ``python -m pokesim.replay capture`` turns one into a scenario.
Keeping one never stops the game: a failure is logged. docs/design/replayable-bugs.md section 4.8.
"""
from __future__ import annotations

import logging
import time

from .. import config
from ..checkpoints import fresh_folder, write_bundle
from ..stalls import BEFORE_STALL_CHECKPOINT

log = logging.getLogger(__name__)
# What noticed the stall, as report.json and the progress replay's bundle row name it.
KINDS = ('quiet', 'give_up', 'loop', 'gate', 'ladder')


def before(store):
    """The save kept from before the stall, or None."""
    return store.state_path(BEFORE_STALL_CHECKPOINT)


def keep_before(host, path, snapshot):
    """Keep the autosave at ``path`` as the save from before any stall, when it is the first since progress.

    Autosaves rotate out long before a stall is noticed, so it is kept under its own name. A save inside
    a battle is never the one kept, since a reload would bring the battle back.
    """
    stall = getattr(host, 'stall', None)
    if not (stall and stall.fresh and config.KEEP_STALL_BUNDLES) or snapshot is not None and snapshot.in_battle:
        return
    try:
        host.store.keep_as(path, BEFORE_STALL_CHECKPOINT)
        stall.fresh = False
    except OSError:
        log.exception('cannot keep the save from before a stall')


def prune_trace(host):
    """Prune the host's trace with its autosaves, holding the segments from the save before a stall."""
    tracer = getattr(host, 'tracer', None)
    if tracer is not None:
        tracer.prune(host.store.autosaves(), hold=before(host.store))


def report(host, snapshot, kind, why='', now=None):
    """What the stall looked like when it was noticed."""
    stall, frame, policy = getattr(host, 'stall', None), getattr(host, 'frame', None), getattr(host, 'policy', None)
    details = policy.details() if hasattr(policy, 'details') else {}
    since = getattr(stall, 'since', None)
    real = None if since is None else int((time.time() if now is None else now) - since) // 60
    # The stall watch counts PlayClock frames. The emulator frame goes back with every reload.
    played = getattr(getattr(host, 'play_clock', None), 'frames', None)
    return {'kind': kind, 'why': why,
            'quiet_game_minutes': stall.game_minutes(played) if stall is not None else None,
            'quiet_real_minutes': real, 'frame': frame, 'map': snapshot.map_name,
            'position': [snapshot.x, snapshot.y], 'in_battle': bool(snapshot.in_battle),
            'objective': details.get('objective'), 'action': details.get('action'), 'reason': details.get('reason'),
            'recoveries': details.get('recoveries', getattr(policy, 'recoveries', 0)),
            'reloads': getattr(host, 'reloads', 0),
            'party': [[getattr(mon, 'name', None) or getattr(mon, 'nick', None), mon.level, mon.hp, mon.status]
                      for mon in snapshot.party]}


def _segments(tracer, state, manifest, held):
    """The closed segments a bundle links. A new segment from this moment first closes the open one, so
    the bundle's trace ends where its noticed state begins."""
    if tracer is None:
        return []
    if tracer.recording:
        tracer.begin(f'capture-{time.time_ns()}', state, manifest)
    return tracer.closed(held)


def keep(host, kind, why='', now=None):
    """Keep a bundle of the stall the running game just noticed, and return its folder.

    It returns None when ``KEEP_STALL_BUNDLES`` is 0, when the host has no store or snapshot, and when
    writing it fails."""
    store, snapshot = getattr(host, 'store', None), getattr(host, 'snapshot', None)
    if not config.KEEP_STALL_BUNDLES or snapshot is None or not hasattr(store, 'write_stall_bundle'):
        return None
    try:
        found = report(host, snapshot, kind, why, now)
        state, manifest = host._state_bytes(), host._manifest()
        held = before(store)
        segments = _segments(getattr(host, 'tracer', None), state, manifest, held)
        folder = store.write_stall_bundle(state, manifest, found, host._shot_png(), held, config.KEEP_STALL_BUNDLES,
                                          segments=segments)
    except Exception:
        log.exception('cannot keep the %s stall bundle', kind)
        return None
    log.warning('kept the %s stall, the save from before it and %d trace segments in %s', kind, len(segments), folder)
    return folder


def keep_run(run, folder, report, before=None, png=None, compress=False):
    """Keep a bundle of a headless run's stall in ``folder``, or ``folder-2`` and on when it exists, and
    return the folder. ``before`` is the save from before the stall."""
    state, manifest = run.state(), run.manifest()
    segments = _segments(getattr(run, 'tracer', None), state, manifest, before)
    return write_bundle(fresh_folder(folder), state, manifest, report, png, before, segments, compress=compress)
