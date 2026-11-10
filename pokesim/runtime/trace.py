"""Record everything that changes a running game, one segment per autosave.

Each autosave begins a segment in the adventure's ``states/trace/<autosave name>/`` folder. The
segment keeps its start state as ``<sha256>.state``, a link to the autosave when it can, and every
press, tick, write, load, owner command and policy step until the next autosave. A run that has
not saved yet begins a ``start-<time>`` segment. Segments older than the oldest kept autosave are
removed with it, so the traces hold about as much game time as the autosaves do.

A failure to write a segment is logged and never stops the game. ``pokecore.trace.verify`` plays a
segment again from its start state. docs/design/replayable-bugs.md section 4.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path

try:
    from pokecore import trace as core
except ImportError:
    # A released pokecore older than its trace module. The game then plays with no trace.
    core = None

from .. import config, fair_dvs, rewards, seeds
from ..build_info import build_info

log = logging.getLogger(__name__)
FOLDER = 'trace'
SEGMENT = 'segment.jsonl.gz'
# After a segment cannot begin, wait this long before a start segment tries again.
RETRY_SECONDS = 600
# The most segments kept for the save from before a stall, about two and a half game hours at the
# default autosave pace. A stall is noticed after two.
HELD_SEGMENTS = 30


def stamp(name):
    """The time in a segment's or autosave's name, so old segments sort before new ones."""
    tail = str(name).rsplit('-', 1)[-1]
    return int(tail) if tail.isdecimal() else 0


def segments(folder):
    """The segment folders under ``folder``, oldest first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted((path for path in folder.iterdir() if path.is_dir()), key=lambda path: (stamp(path.name), path.name))


def held_segment(folder, save):
    """The oldest segment under ``folder`` that starts from the save state at ``save``, or None. A gzipped
    save, as a ladder rung keeps, is unpacked first, since a segment names its start by the unpacked bytes."""
    if save is None:
        return None
    try:
        raw = Path(save).read_bytes()
        sha = hashlib.sha256(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw).hexdigest()
    except (OSError, EOFError, gzip.BadGzipFile):
        return None
    return next((segment for segment in segments(folder) if (segment / f'{sha}.state').exists()), None)


def digest(value):
    """The SHA-256 of a value's JSON, so a header names a seed without holding it."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def seed_digests(store):
    """Digests of the seeds this adventure's choices come from. A missing seed is None."""
    adventure = config.SEED if config.SEED is not None else store.get(seeds.KEY)
    found = {'adventure': adventure, 'fair_dvs': store.get(fair_dvs.KEY), 'league_ledger': store.get(rewards.KEY)}
    return {name: None if value is None else digest(value) for name, value in found.items()}


def _plain(value, depth=0):
    """A JSON-safe copy of a command argument, with anything else named by its type."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if depth < 4 and isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    if depth < 4 and isinstance(value, dict):
        return {str(key): _plain(item, depth + 1) for key, item in value.items()}
    return type(value).__qualname__


def command(name, arg):
    """The payload of an owner command's input record."""
    if name == 'runtime_call' and isinstance(arg, tuple) and arg:
        # The rest of the tuple is the caller's reply slot. A call with inputs of its own logs them.
        return {'command': name, 'call': getattr(arg[0], '__qualname__', type(arg[0]).__qualname__)}
    if name in ('trade', 'trade_preference') and isinstance(arg, tuple):
        return {'command': name, 'args': _plain(arg[:2])}
    return {'command': name, 'arg': _plain(arg)}


class _Segment(object if core is None else core.Segment):
    """A segment that stops writing after a disk error instead of stopping the game."""

    broken = False

    def _guard(self, action, *args):
        if self.broken:
            return None
        try:
            return action(*args)
        except OSError:
            self.broken = True
            log.exception('cannot write the trace segment %s, so it stops here', self.path.parent.name)
            with contextlib.suppress(OSError):
                super().close()
            return None

    def record(self, record):
        self._guard(super().record, record)

    def keep_state(self, data):
        return self._guard(super().keep_state, data) or core.digest(data)

    def flush(self):
        self._guard(super().flush)

    def close(self):
        try:
            super().close()
        except OSError:
            self._file = None
            log.exception('cannot close the trace segment %s', self.path.parent.name)


class Tracer:
    """Keeps one recorder on the game's emulator and begins its segments in ``folder``.

    ``seeds`` is the header's seed digests, or a function that reads them as each segment begins.
    """

    def __init__(self, folder, generation, seeds=None):
        self.folder = Path(folder)
        self.generation = generation
        self.seeds = seeds or {}
        self.recorder = None
        self.name = None
        self._previous = None
        self._failed = None

    def attach(self, pb):
        """Follow a new emulator. Attach before anything registers a hook, so every hook is known."""
        if self.recorder is not None:
            self._previous = self.recorder.head or self._previous
            self.recorder.detach()
        self.recorder = core.Recorder(pb)
        self.name = None

    @property
    def recording(self):
        return self.recorder is not None and self.recorder.sink is not None

    def begin(self, name, state, manifest, kept=None):
        """Begin a segment named ``name`` from ``state``. ``kept`` is a file holding those bytes, linked
        in as the start state instead of a second copy. Returns whether the segment began."""
        recorder = self.recorder
        if recorder is None:
            return False
        folder = self.folder / name
        previous = recorder.head or self._previous
        try:
            folder.mkdir(parents=True, exist_ok=True)
            sha = core.digest(state)
            start = folder / f'{sha}.state'
            linked = start.exists()
            if not linked and kept is not None:
                with contextlib.suppress(OSError):
                    if Path(kept).stat().st_size == len(state):
                        os.link(kept, start)
                        linked = True
            found = self.seeds() if callable(self.seeds) else self.seeds
            recorder.begin(_Segment(folder / SEGMENT, keep_start=not linked), state, previous_head=previous,
                           generation=self.generation, build=build_info(), seeds=found, manifest=manifest)
        except Exception:
            # A begin that fails part way must not leave records going to a half-made segment.
            recorder.close()
            self._failed = time.monotonic()
            log.exception('cannot begin the trace segment %s', name)
            return False
        self.name, self._failed = name, None
        return True

    def ensure(self, manifest):
        """Begin a start segment when none is open, as after power-on or a reboot. ``manifest`` builds the
        header's manifest, only when one is needed."""
        if self.recording or self.recorder is None:
            return False
        if self._failed is not None and time.monotonic() - self._failed < RETRY_SECONDS:
            return False
        return self.begin(f'start-{time.time_ns()}', self.recorder.emulator.save(), manifest())

    def decide(self, policy, snapshot):
        """Log one policy step before the inputs it chose."""
        if not self.recording:
            return
        goal = getattr(policy, 'goal', None)
        key = None if goal is None else getattr(goal, 'key', None)
        if goal is not None and not isinstance(key, str):
            key = type(goal).__name__
        self.recorder.decide(key, getattr(snapshot, 'map', None), getattr(snapshot, 'x', None),
                             getattr(snapshot, 'y', None))

    def input(self, source, payload=None):
        if self.recording:
            self.recorder.input(source, payload)

    def reason(self, why):
        """Name the reason loads inside this block are logged with."""
        return self.recorder.reason(why) if self.recorder is not None else contextlib.nullcontext()

    def close(self):
        if self.recorder is not None:
            self.recorder.close()

    def prune(self, autosaves, hold=None):
        """Remove segments that began before the oldest of ``autosaves``, never the open one.

        ``hold`` is the save kept from before a stall. The segments from the one that starts at it stay
        too, up to the newest HELD_SEGMENTS, so a stall noticed after its autosaves rotate out still has
        the trace that led to it."""
        if not autosaves:
            return
        oldest = min(stamp(Path(path).stem) for path in autosaves)
        found = segments(self.folder)
        held = held_segment(self.folder, hold)
        if held is not None:
            oldest = min(oldest, max(stamp(held.name), stamp(found[-HELD_SEGMENTS:][0].name)))
        for folder in found:
            if stamp(folder.name) < oldest and folder.name != self.name:
                shutil.rmtree(folder, ignore_errors=True)

    def closed(self, hold=None):
        """The closed segments from the one that starts at the save ``hold`` on, or every closed segment
        when none starts there, at most the newest HELD_SEGMENTS."""
        found = [folder for folder in segments(self.folder) if not (self.recording and folder.name == self.name)]
        held = held_segment(self.folder, hold)
        if held is not None:
            found = [folder for folder in found if stamp(folder.name) >= stamp(held.name)]
        return found[-HELD_SEGMENTS:]


def for_store(store, generation):
    """The tracer for an adventure's store, or None when ``TRACE`` is off, the store keeps no states or
    the installed pokecore cannot trace."""
    states = getattr(store, 'states', None)
    if not config.TRACE or not isinstance(states, (str, os.PathLike)):
        return None
    if core is None:
        log.warning('the installed pokecore has no trace module, so this adventure keeps no trace')
        return None
    return Tracer(Path(states) / FOLDER, generation, lambda: seed_digests(store))


def for_run(folder, generation, pb, seed):
    """The tracer for a headless run that keeps its segments in ``folder``, attached to ``pb``, or
    None when ``folder`` is None. Attach it before anything registers a hook on ``pb``."""
    if folder is None:
        return None
    if core is None:
        raise RuntimeError('this run asks for a trace, and the installed pokecore has no trace module')
    tracer = Tracer(folder, generation, {'adventure': digest(seed)})
    tracer.attach(pb)
    return tracer


def reason(host, why):
    """The host's tracer's reason block, or nothing when the host keeps no trace."""
    tracer = getattr(host, 'tracer', None)
    return tracer.reason(why) if tracer is not None else contextlib.nullcontext()


def note(host, source, payload=None):
    """Log an input record on the host's trace, when it keeps one."""
    tracer = getattr(host, 'tracer', None)
    if tracer is not None:
        tracer.input(source, payload)
