"""Hash-chained traces of an emulator run, and the two ways to replay one.

A trace is a chain of segments. Each segment is a gzip JSON-lines file whose first line is
the header and whose later lines are records. Every record carries a hash of the previous
hash and itself, so a changed, dropped or reordered record breaks the chain. States that a
segment loads are kept beside it as ``<sha256>.state``.

``Recorder`` attaches to a Core emulator and writes every press, release, tick, write,
load, hook registration and clock call. Writes that hooks make during a tick are kept in
that tick's record with the hook fire they came from. The caller adds ``decide`` and
``input`` records. ``verify`` replays a segment with no policy, and ``redecide`` runs a
policy again from the same start and stops at the first record that differs.

This module uses only the standard library and imports nothing from pokecore at module
level, so a tool can load this file by path into an older checkout.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import operator
import os
import zlib
from pathlib import Path

FORMAT = 1
BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
DIGEST_RANGES = ((0xC000, 0xE000),)
CHECK_EVERY = 3600
CLOCK_CALLS = ("lock_clock", "unlock_clock", "advance_clock", "set_rtc_registers", "set_rtc_timezero",
               "import_rtc", "set_clock_lock_state")
BLOCKED = ("start_sequence", "run_sequence", "restore_checkpoint")
RESERVED = frozenset(("format", "rom_sha256", "state_sha256", "frame", "emulator", "settings", "pokecore", "hooks",
                      "pending", "digest_ranges", "check_every", "clock", "previous"))
KINDS = frozenset(("press", "release", "tick", "write", "decide", "input", "load", "check", "hook"))
OK, DIVERGED, HARNESS = 0, 1, 2
# Registration records depend on which observing hooks a commit has, not on what it plays.
_NOT_COMPARED = frozenset(("hook",))


def digest(data):
    """SHA-256 hex digest of bytes or text."""
    return hashlib.sha256(data.encode() if isinstance(data, str) else bytes(data)).hexdigest()


def encoded(value):
    """The canonical JSON text that hashes are taken over."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def chain_hash(previous, record):
    """The hash of ``record`` (without its own hash) after ``previous``."""
    return digest(previous + encoded({key: value for key, value in record.items() if key != "hash"}))


class TraceError(Exception):
    """The trace or the harness is broken: a bad chain, missing state or mismatched provenance (exit 2)."""

    code = HARNESS


class Divergence(Exception):
    """The replay did something other than the log at one record (exit 1). ``details`` says where."""

    code = DIVERGED

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = dict(details or {})


class Result:
    """The outcome of ``verify`` or ``redecide``: code 0 for the same run, 1 for a divergence, 2 for a harness failure."""

    def __init__(self, code, message="", details=None, records=0):
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.records = records

    @property
    def ok(self):
        return self.code == OK

    def __repr__(self):
        return f"Result(code={self.code}, message={self.message!r}, records={self.records})"


class _Stop(BaseException):
    """Ends a redecide run from inside application code, past any ``except Exception``."""


def _version(name):
    from importlib import metadata
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _json_value(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": bytes(value).hex()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _python_value(value):
    if isinstance(value, dict):
        if set(value) == {"bytes"}:
            return bytes.fromhex(value["bytes"])
        return {key: _python_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_python_value(item) for item in value]
    return value


def _normal(value):
    """``value`` as it reads back from a trace file, so tuples compare equal to lists."""
    return json.loads(encoded(value))


# Segment files


class Segment:
    """Writes one segment to ``path`` and keeps loaded states beside it.

    ``keep_start`` also keeps the start state as ``<sha256>.state``. Leave it off when the
    caller already keeps that state, such as an autosave next to its trace.
    """

    def __init__(self, path, *, keep_start=False):
        self.path = Path(path)
        self.folder = self.path.parent
        self.keep_start = keep_start
        self._file = None

    def begin(self, header, state):
        self.folder.mkdir(parents=True, exist_ok=True)
        self._file = gzip.open(self.path, "wt", encoding="utf-8")
        self._file.write(encoded(header) + "\n")
        if self.keep_start:
            self.keep_state(state)

    def record(self, record):
        self._file.write(encoded(record) + "\n")
        if record["kind"] == "check":
            self.flush()

    def keep_state(self, data):
        sha = digest(data)
        target = self.folder / f"{sha}.state"
        if not target.exists():
            partial = target.with_name(f".{sha}.{os.getpid()}.partial")
            partial.write_bytes(bytes(data))
            os.replace(partial, target)
        return sha

    def flush(self):
        """Make every record so far readable even if the process dies before close."""
        if self._file is not None:
            self._file.flush()
            self._file.buffer.flush(zlib.Z_SYNC_FLUSH)

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


class Trace:
    """One segment read back: its header, records, head hash and states folder.

    A file cut off mid-write (a crash) keeps every complete line and sets ``truncated``.
    """

    def __init__(self, header, records, *, path=None, truncated=False):
        self.header = header
        self.records = records
        self.path = Path(path) if path is not None else None
        self.truncated = truncated
        self.head = check_chain(header, records)

    @property
    def folder(self):
        return self.path.parent if self.path is not None else None

    @classmethod
    def read(cls, path):
        lines, truncated = [], False
        try:
            with gzip.open(path, "rt", encoding="utf-8") as file:
                for line in file:
                    if not line.endswith("\n"):
                        truncated = True
                        break
                    lines.append(line)
        except (EOFError, zlib.error):
            truncated = True
        except (OSError, UnicodeDecodeError) as error:
            raise TraceError(f"cannot read trace {path}: {error}") from error
        try:
            values = [json.loads(line) for line in lines]
        except ValueError as error:
            raise TraceError(f"trace {path} has a line that is not JSON: {error}") from error
        if not values:
            raise TraceError(f"trace {path} has no header")
        return cls(values[0], values[1:], path=path, truncated=truncated)

    def state(self, sha, states=None):
        """The bytes of a kept state, from ``states`` (a folder or a mapping) or the trace's folder."""
        source = self.folder if states is None else states
        if isinstance(source, (str, os.PathLike)):
            target = Path(source) / f"{sha}.state"
            data = target.read_bytes() if target.is_file() else None
        elif source is not None:
            data = source.get(sha)
        else:
            data = None
        if data is None:
            raise TraceError(f"state {sha} is not kept beside the trace")
        if digest(data) != sha:
            raise TraceError(f"kept state {sha} does not match its hash")
        return bytes(data)


def check_chain(header, records):
    """The head hash of a segment. Raises TraceError on the first record that breaks the chain."""
    if not isinstance(header, dict) or header.get("format") != FORMAT:
        raise TraceError(f"unsupported trace format {header.get('format') if isinstance(header, dict) else header!r}")
    previous = digest(encoded(header))
    for position, record in enumerate(records):
        if not isinstance(record, dict) or record.get("index") != position:
            raise TraceError(f"record {position} is out of order")
        if record.get("kind") not in KINDS:
            raise TraceError(f"record {position} has unknown kind {record.get('kind')!r}")
        if record.get("hash") != chain_hash(previous, record):
            raise TraceError(f"record {position} breaks the hash chain")
        previous = record["hash"]
    return previous


def read_chain(paths):
    """Read segments in order and check that each header names the previous segment's head."""
    traces, head = [], None
    for path in paths:
        trace = Trace.read(path)
        if traces and trace.header.get("previous") != head:
            raise TraceError(f"{path} does not follow the segment before it")
        if traces and traces[-1].truncated:
            raise TraceError(f"{traces[-1].path} was cut off, so the chain cannot continue")
        traces.append(trace)
        head = trace.head
    return traces


# Recording


def _core_memory(emulator):
    """The Core memory object that every write ends in, under any address translation."""
    return getattr(emulator, "raw_memory", None) or emulator.memory


def _target(key, value):
    """(address, value) for a memory write in trace form, or None when the key is not understood."""
    bank = None
    if isinstance(key, tuple):
        if len(key) != 2:
            return None
        bank, key = key
        try:
            bank = operator.index(bank)
        except TypeError:
            return None
    if isinstance(key, slice):
        if key.step not in (None, 1) or key.start is None:
            return None
        start = operator.index(key.start)
        if isinstance(value, int):
            if key.stop is None:
                return None
            value = [value] * (operator.index(key.stop) - start)
        else:
            value = [operator.index(item) for item in value]
    else:
        try:
            start = operator.index(key)
        except TypeError:
            return None
        if not isinstance(value, int):
            return None
    return (start if bank is None else [bank, start]), value


def _write_memory(memory, address, value):
    if isinstance(address, list):
        bank, start = address
        key = (bank, slice(start, start + len(value))) if isinstance(value, list) else (bank, start)
    else:
        key = slice(address, address + len(value)) if isinstance(value, list) else address
    memory[key] = value


def _swap_class(obj, attribute, function):
    """Give ``obj`` a subclass of its class that overrides ``attribute``. Returns the old class."""
    cls = type(obj)
    traced = type(f"Traced{cls.__name__}", (cls,), {attribute: function, "__slots__": (), "__module__": __name__})
    # Registers refuses ordinary attribute sets, so set the class past its __setattr__.
    object.__setattr__(obj, "__class__", traced)
    return cls


def _clock_present(emulator):
    try:
        return bool(getattr(emulator, "clock_control_available", False)) and bool(emulator.has_rtc)
    except Exception:
        return False


def _set_clock_lock(emulator, lock):
    setter = getattr(emulator, "set_clock_lock_state", None)
    if setter is None:
        setter = emulator._backend.set_clock_lock_state
    setter(lock)


class Recorder:
    """Records everything that changes an attached emulator. Call ``begin`` to start each segment.

    Attaching patches the emulator instance: its press, release, tick, load, hook and clock
    methods, and the classes of its Core memory and register objects, so writes made through
    any reference to them, including hook contexts, are logged. Records made before the first
    ``begin`` are dropped, but hooks and frames are still tracked.

    Hooks registered before attaching are unknown, so a write made inside one marks its tick
    ``unrecorded`` and ``verify`` refuses that trace. Attach when the emulator is built.
    Sequences and checkpoint restores cannot be recorded and raise while attached.
    """

    def __init__(self, emulator, *, digest_ranges=DIGEST_RANGES, check_every=CHECK_EVERY):
        self.emulator = emulator
        self.digest_ranges = [list(item) for item in digest_ranges]
        self.check_every = check_every
        self.sink = None
        self.head = None
        self.index = 0
        self.frames = 0
        self._start = 0
        self._since_check = 0
        self._hooks = {}
        self._hook = None
        self._ticking = False
        self._tick_writes = []
        self._tick_unrecorded = []
        self._deferred = []
        self._reason = "load"
        self._originals = {}
        self._classes = {}
        self._attached = True
        self._attach()

    # Attachment

    def _attach(self):
        emulator = self.emulator
        self._swap_memory(_core_memory(emulator))
        self._swap_registers(emulator.register_file)
        patches = {"press": self._press, "button_press": self._press, "release": self._release,
                   "button_release": self._release, "tick": self._tick, "tick_read": self._tick_read,
                   "load": self._load, "load_state": self._load_state, "hook_register": self._hook_register,
                   "hook_deregister": self._hook_deregister}
        for name in CLOCK_CALLS:
            if hasattr(emulator, name):
                patches[name] = self._clock_call(name)
        for name in BLOCKED:
            if hasattr(emulator, name):
                patches[name] = self._blocked(name)
        for name, function in patches.items():
            self._originals[name] = getattr(emulator, name)
            setattr(emulator, name, function)

    def _swap_memory(self, memory):
        recorder = self

        def set_memory(self, key, value):
            cls.__setitem__(self, key, value)
            recorder._wrote(key, value)

        cls = _swap_class(memory, "__setitem__", set_memory)
        self._classes["memory"] = (memory, cls)

    def _swap_registers(self, registers):
        recorder = self

        def set_register(self, name, value):
            register_class.__setattr__(self, name, value)
            recorder._hook_or_record(name, value)

        register_class = _swap_class(registers, "__setattr__", set_register)
        self._classes["registers"] = (registers, register_class)

    def _rebind(self):
        """Follow a memory or register object the emulator built again after attaching.

        A subclass can replace the Core memory object once ``Emulator.__init__`` returns, as the
        snapshot emulator does, and writes through the new object would otherwise go unlogged.
        """
        current = {"memory": (_core_memory(self.emulator), self._swap_memory),
                   "registers": (self.emulator.register_file, self._swap_registers)}
        for role, (obj, swap) in current.items():
            old, cls = self._classes[role]
            if obj is not old:
                object.__setattr__(old, "__class__", cls)
                swap(obj)

    def detach(self):
        """Close the open segment and put the emulator back as it was."""
        self.close()
        self._attached = False
        for name in self._originals:
            with contextlib.suppress(AttributeError):
                delattr(self.emulator, name)
        self._originals.clear()
        for obj, cls in self._classes.values():
            object.__setattr__(obj, "__class__", cls)
        self._classes.clear()

    def close(self):
        if self.sink is not None:
            sink, self.sink = self.sink, None
            sink.close()

    # Segments

    def begin(self, sink, state=None, **fields):
        """Start a segment on ``sink`` from ``state`` (default: the emulator's current state).

        ``fields`` go into the header beside the reserved ones, for the caller's provenance
        and policy state. A previous segment is closed and the new header names its head.
        ``previous_head`` names the head of a segment another recorder wrote, such as one
        from before a restart.
        """
        if self._ticking:
            raise RuntimeError("Start a trace segment between ticks")
        clash = RESERVED.intersection(fields)
        if clash:
            raise ValueError(f"reserved trace header fields: {', '.join(sorted(clash))}")
        self._rebind()
        emulator = self.emulator
        state = emulator.save() if state is None else bytes(state)
        previous = fields.pop("previous_head", None)
        if self.sink is not None:
            previous = self.head
        self.close()
        header = {"format": FORMAT, "rom_sha256": emulator.rom_sha256, "state_sha256": digest(state),
                  "frame": emulator.frame_count,
                  "emulator": {"backend": "pyboy-rs", "version": _version("pyboy-rs")},
                  "settings": _normal(getattr(emulator, "_settings", None)),
                  "pokecore": _version("pokecore"), "hooks": sorted([list(key) for key in self._hooks]),
                  "pending": [[button, pressed] for button, pressed in emulator.pending_inputs],
                  "digest_ranges": self.digest_ranges, "check_every": self.check_every, "previous": previous}
        if _clock_present(emulator):
            header["clock"] = emulator.clock_lock_state()
        header.update(_json_value(fields))
        for key in self._hooks:
            self._hooks[key] = 0
        self.index = 0
        self._start = header["frame"]
        self.frames = 0
        self._since_check = 0
        self.head = digest(encoded(header))
        self.sink = sink
        sink.begin(header, state)
        return header

    @property
    def frame(self):
        """The trace's own frame: the segment's start frame plus every frame ticked since."""
        return self._start + self.frames

    def _emit(self, kind, **fields):
        if self.sink is None:
            return None
        record = {"index": self.index, "frame": self.frame, "kind": kind, **fields}
        record["hash"] = chain_hash(self.head, record)
        self.head = record["hash"]
        self.index += 1
        self.sink.record(record)
        return record

    # Caller records

    def decide(self, goal, map, x, y, pipeline=None):
        """Log one policy step with a digest of the digest ranges.

        ``pipeline`` is what a shadow decision pipeline picked at this step, as plain data. It is logged
        only when given, and a replay compares it only when the log has it.
        """
        fields = {"goal": _json_value(goal), "map": _json_value(map), "x": x, "y": y}
        if pipeline is not None:
            fields["pipeline"] = _json_value(pipeline)
        return self._emit("decide", **fields, digest=memory_digest(self.emulator, self.digest_ranges))

    def input(self, source, payload=None):
        """Log something from outside the cartridge that the policy uses, such as an owner command."""
        return self._emit("input", source=source, payload=_json_value(payload))

    @contextlib.contextmanager
    def reason(self, reason):
        """Name the reason that loads inside this block are logged with."""
        previous, self._reason = self._reason, reason
        try:
            yield self
        finally:
            self._reason = previous

    # Patched emulator methods

    def _press(self, button):
        self._originals["press"](button)
        self._later("press", button=button)

    def _release(self, button):
        self._originals["release"](button)
        self._later("release", button=button)

    def _later(self, kind, **fields):
        if self._ticking:
            self._deferred.append((kind, fields))
        else:
            self._emit(kind, **fields)

    def _tick(self, frames=1, render=True, sound=True):
        return self._advance(self._originals["tick"], (frames,), frames, render, sound)

    def _tick_read(self, frames, start, stop, *, render=True, sound=True):
        return self._advance(self._originals["tick_read"], (frames, start, stop), frames, render, sound)

    def _advance(self, method, args, frames, render, sound):
        if self._ticking:
            return method(*args, render=render, sound=sound)
        # Rendering and sound change the saved state, so a replay must tick with the logged flags.
        flags = getattr(self.sink, "tick_flags", None)
        render, sound = flags(render, sound) if flags is not None else (bool(render), bool(sound))
        self._ticking = True
        self._tick_writes, self._tick_unrecorded, self._deferred = [], [], []
        before = self.emulator.frame_count
        try:
            result = method(*args, render=render, sound=sound)
        except BaseException as error:
            self._ticking = False
            ran = self.emulator.frame_count - before
            # A tick refused before it ran changed nothing. One that raised part way is logged
            # with the frames that ran, so the trace stays on the timeline, and verify refuses it.
            if ran or self._tick_writes or self._tick_unrecorded:
                self._emit("tick", frames=ran, unrecorded=[f"the tick raised {type(error).__name__}"])
                self.frames += ran
                self._since_check += ran
            self._emit_deferred()
            raise
        self._ticking = False
        fields = {"frames": frames}
        if not render:
            fields["render"] = False
        if not sound:
            fields["sound"] = False
        if self._tick_writes:
            fields["hooks"] = self._tick_writes
        if self._tick_unrecorded:
            fields["unrecorded"] = self._tick_unrecorded
        self._emit("tick", **fields)
        self.frames += frames
        self._since_check += frames
        self._emit_deferred()
        if self.sink is not None and self._since_check >= self.check_every:
            self._since_check = 0
            self._emit("check", sha256=digest(self.emulator.save()))
        return result

    def _emit_deferred(self):
        # Core queues a press made during a tick until the next tick, so it belongs after this one.
        deferred, self._deferred = self._deferred, []
        for kind, fields in deferred:
            self._emit(kind, **fields)

    def _wrote(self, key, value):
        target = _target(key, value)
        if target is None:
            self._unrecorded(f"memory write at {key!r}")
        else:
            self._hook_or_record(*target)

    def _hook_or_record(self, address, value):
        if not self._ticking:
            self._emit("write", address=address, value=value)
        elif self._hook is None:
            self._tick_unrecorded.append(f"write to {address!r} outside a known hook")
        else:
            (bank, hook_address), fire = self._hook
            entry = self._tick_writes[-1] if self._tick_writes else None
            if entry is None or entry[:3] != [bank, hook_address, fire]:
                entry = [bank, hook_address, fire, []]
                self._tick_writes.append(entry)
            entry[3].append([address, value])

    def _unrecorded(self, what):
        if self._ticking:
            self._tick_unrecorded.append(what)
        else:
            self._emit("write", unrecorded=what)

    def _load(self, state):
        data = bytes(state)
        self._originals["load"](data)
        if self._ticking:
            self._unrecorded("a load inside a tick")
            return
        if self.sink is not None:
            sha = self.sink.keep_state(data)
            self._emit("load", state_sha256=sha, reason=self._reason)

    def _load_state(self, stream):
        self._load(stream.read())

    def _hook_register(self, bank, address, callback, context):
        key = (bank, address)
        recorder = self

        def fire(context):
            if recorder._attached:
                count = recorder._hooks.get(key, 0)
                recorder._hooks[key] = count + 1
                outer, recorder._hook = recorder._hook, (key, count)
                try:
                    return callback(context)
                finally:
                    recorder._hook = outer
            return callback(context)

        self._originals["hook_register"](bank, address, fire, context)
        self._hooks[key] = 0
        if self._ticking:
            self._unrecorded(f"hook registered at {key!r} inside a tick")
        else:
            self._emit("hook", bank=bank, address=address, registered=True)

    def _hook_deregister(self, bank, address):
        self._originals["hook_deregister"](bank, address)
        self._hooks.pop((bank, address), None)
        if self._ticking:
            self._unrecorded(f"hook removed at {(bank, address)!r} inside a tick")
        else:
            self._emit("hook", bank=bank, address=address, registered=False)

    def _clock_call(self, name):
        def call(*args, **kwargs):
            if name == "import_rtc" and args and hasattr(args[0], "read"):
                args = (args[0].read(),) + args[1:]
            result = self._originals[name](*args, **kwargs)
            if self._ticking:
                self._unrecorded(f"{name} inside a tick")
            else:
                self._emit("input", source="clock",
                           payload={"call": name, "args": _json_value(args), "kwargs": _json_value(kwargs)})
            return result
        return call

    def _blocked(self, name):
        def call(*_, **__):
            raise RuntimeError(f"{name} cannot be traced. Detach the trace recorder first")
        return call


def memory_digest(emulator, ranges=DIGEST_RANGES):
    """SHA-256 of the given ranges, read from the emulator's untranslated memory."""
    memory = _core_memory(emulator)
    hasher = hashlib.sha256()
    for item in ranges:
        if len(item) == 3:
            hasher.update(memory.read_bank_bytes(*item))
        else:
            hasher.update(memory.read_bytes(*item))
    return hasher.hexdigest()


# Replay


def _prepare(trace, emulator, state, states, check_emulator):
    """Load the segment's start onto ``emulator``: state, clock lock and queued inputs. Returns the state."""
    header = trace.header
    if header.get("rom_sha256") != emulator.rom_sha256:
        raise TraceError("the emulator runs another ROM than the trace")
    recorded = (header.get("emulator") or {}).get("version")
    installed = _version("pyboy-rs")
    if check_emulator and recorded != installed:
        raise TraceError(f"the trace was recorded on pyboy-rs {recorded}, this is pyboy-rs {installed}")
    if state is None:
        state = trace.state(header.get("state_sha256"), states)
    state = bytes(state)
    if digest(state) != header.get("state_sha256"):
        raise TraceError("the start state does not match the trace header")
    settings = getattr(emulator, "_settings", None)
    if None not in (settings, header.get("settings")) and _normal(settings) != header["settings"]:
        raise TraceError(f"the emulator was built with other settings than the recording: {header['settings']}")
    if emulator.pending_inputs:
        raise TraceError("the emulator has queued inputs, so replay needs a fresh emulator")
    present = _clock_present(emulator)
    if ("clock" in header) != present:
        raise TraceError("the trace and the emulator disagree on whether the cartridge has a clock")
    if present:
        lock = header["clock"]
        if lock is None:
            raise TraceError("the cartridge clock was not locked, so the run followed the host clock")
        # A load latches the cartridge clock at its current reading, so lock it first.
        _set_clock_lock(emulator, lock)
    emulator.load(state)
    if present and _normal(emulator.clock_lock_state()) != header["clock"]:
        raise TraceError("the clock lock did not apply")
    # Hardware states do not carry Core's frame counter, so start it where the recording did.
    if hasattr(emulator, "_frame_offset"):
        emulator._frame_offset += header["frame"] - emulator.frame_count
    for button, pressed in header.get("pending", ()):
        (emulator.press if pressed else emulator.release)(button)
    return state


def _apply_write(emulator, address, value):
    if isinstance(address, str):
        setattr(emulator.register_file, address, value)
    else:
        _write_memory(_core_memory(emulator), address, value)


def _decided(record):
    return {key: record.get(key) for key in ("index", "frame", "goal", "map", "x", "y")}


def _fail(record, message, expected, actual, last_decide):
    return Divergence(message, {"index": record["index"], "frame": record["frame"], "kind": record["kind"],
                                "expected": expected, "actual": actual, "last_decide": last_decide})


def verify(trace, emulator, state=None, *, states=None, check_emulator=True):
    """Feed a segment back with no policy and compare every decide digest and state check.

    ``trace`` is a path or a ``Trace``. ``emulator`` is a fresh Core emulator on the same ROM.
    ``state`` defaults to the kept start state. ``states`` is a folder or a mapping of kept
    states, default the trace's folder. ``check_emulator=False`` replays on another pyboy-rs
    version. Returns a Result: 0 when the run matches, 1 at the first record that differs,
    2 for a broken trace or harness.
    """
    replayed = 0
    try:
        trace = trace if isinstance(trace, Trace) else Trace.read(trace)
        unrecorded = next((record for record in trace.records if record.get("unrecorded")), None)
        if unrecorded is not None:
            raise TraceError(f"record {unrecorded['index']} has a change the recorder could not log: "
                             f"{unrecorded['unrecorded']}")
        header = trace.header
        _prepare(trace, emulator, state, states, check_emulator)
        counts, armed = {}, {}

        def fire(key):
            count = counts.get(key, 0)
            counts[key] = count + 1
            for address, value in armed.pop((key, count), ()):
                _apply_write(emulator, address, value)

        for bank, address in header.get("hooks", ()):
            emulator.hook_register(bank, address, fire, (bank, address))
            counts[(bank, address)] = 0
        ranges = header.get("digest_ranges", DIGEST_RANGES)
        frame, last_decide = header["frame"], None
        for record in trace.records:
            if record["frame"] != frame:
                raise TraceError(f"record {record['index']} is at frame {record['frame']}, the replay is at {frame}")
            kind = record["kind"]
            if kind == "tick":
                armed = {((bank, address), count): writes for bank, address, count, writes in record.get("hooks", ())}
                emulator.tick(record["frames"], render=record.get("render", True), sound=record.get("sound", True))
                frame += record["frames"]
                if armed:
                    missed = sorted(f"{bank}:{address:#x} fire {count}" for (bank, address), count in armed)
                    raise _fail(record, "a hook did not fire where it wrote during recording", "fired", missed,
                                last_decide)
            elif kind == "press":
                emulator.press(record["button"])
            elif kind == "release":
                emulator.release(record["button"])
            elif kind == "write":
                _apply_write(emulator, record["address"], record["value"])
            elif kind == "load":
                emulator.load(trace.state(record["state_sha256"], states))
            elif kind == "hook":
                key = (record["bank"], record["address"])
                if record["registered"]:
                    emulator.hook_register(*key, fire, key)
                    counts[key] = 0
                else:
                    emulator.hook_deregister(*key)
                    counts.pop(key, None)
            elif kind == "input":
                payload = record.get("payload") or {}
                if record.get("source") == "clock":
                    getattr(emulator, payload["call"])(*_python_value(payload.get("args", [])),
                                                       **_python_value(payload.get("kwargs", {})))
            elif kind == "decide":
                actual = memory_digest(emulator, ranges)
                if actual != record["digest"]:
                    raise _fail(record, "memory differs at a policy step", record["digest"], actual, last_decide)
                last_decide = _decided(record)
            elif kind == "check":
                actual = digest(emulator.save())
                if actual != record["sha256"]:
                    raise _fail(record, "the full state differs at a check", record["sha256"], actual, last_decide)
            replayed += 1
    except TraceError as error:
        return Result(HARNESS, str(error), records=replayed)
    except Divergence as error:
        return Result(DIVERGED, str(error), error.details, records=replayed)
    return Result(OK, f"{replayed} records match", records=replayed)


class Comparator:
    """A Recorder sink that checks each new record against a logged segment instead of writing it.

    It stops the run, past application ``except Exception`` blocks, at the first record that
    differs and when the log runs out. ``outcome`` then holds the Result. Hook registrations
    are not compared, since an observing hook added or removed does not change play.
    """

    def __init__(self, trace, *, check_emulator=True):
        self.trace = trace
        self.check_emulator = check_emulator
        self.expected = [record for record in trace.records if record["kind"] not in _NOT_COMPARED]
        self.position = 0
        self.started = False
        self.outcome = None
        self.last_decide = None
        self._start = None

    def _stop(self, result):
        if self.outcome is None:
            self.outcome = result
        raise _Stop()

    def _diverged(self, message, details):
        self._stop(Result(DIVERGED, message, {"last_decide": self.last_decide, **details}, records=self.position))

    def begin(self, header, state):
        if self.outcome is not None:
            raise _Stop()
        if self.started:
            if self.position < len(self.expected):
                self._diverged("the run started a new segment before the log ended",
                               {"index": self.expected[self.position]["index"]})
            self._stop(Result(OK, f"{self.position} records match", records=self.position))
        self.started = True
        logged, header = self.trace.header, _normal(header)
        names = ["format", "rom_sha256", "state_sha256", "settings", "pending", "digest_ranges", "check_every",
                 "clock"]
        if self.check_emulator:
            names.append("emulator")
        for name in names:
            if logged.get(name) != header.get(name):
                self._stop(Result(HARNESS, f"the replay header differs from the log in {name}",
                                  {"expected": logged.get(name), "actual": header.get(name)}))
        self._start = (header["frame"], logged["frame"])
        if not self.expected:
            self._stop(Result(OK, "the log has no records", records=0))

    def record(self, record):
        if self.outcome is not None:
            raise _Stop()
        if record["kind"] in _NOT_COMPARED:
            return
        actual = _normal(record)
        expected = self.expected[self.position]
        actual_offset = actual.pop("frame") - self._start[0]
        logged = {key: value for key, value in expected.items() if key not in ("index", "frame", "hash")}
        logged_offset = expected["frame"] - self._start[1]
        for key in ("index", "hash"):
            actual.pop(key, None)
        if actual["kind"] == "decide" and "pipeline" not in logged:
            # A log from before the pipeline field, or a step it did not decide, leaves the field out.
            actual.pop("pipeline", None)
        if (actual_offset, actual) != (logged_offset, logged):
            self._diverged("the run did something other than the log",
                           {"index": expected["index"], "frame": expected["frame"], "kind": expected["kind"],
                            "expected": logged, "actual": actual, "frame_offset": actual_offset - logged_offset})
        if expected["kind"] == "decide":
            self.last_decide = _decided(expected)
        self.position += 1
        if self.position == len(self.expected):
            self._stop(Result(OK, f"{self.position} records match", records=self.position))

    def tick_flags(self, render, sound):
        """The logged render and sound flags when the next logged record is a tick.

        A replay is often headless where the recording had a viewer, and the flags change
        the saved state, so the replay ticks as the recording did.
        """
        if self.position < len(self.expected) and self.expected[self.position]["kind"] == "tick":
            expected = self.expected[self.position]
            return expected.get("render", True), expected.get("sound", True)
        return bool(render), bool(sound)

    def keep_state(self, data):
        return digest(data)

    def close(self):
        pass

    def finish(self):
        """The Result after the run returned on its own."""
        if self.outcome is None:
            if not self.started:
                self.outcome = Result(HARNESS, "the run never started a trace segment")
            else:
                expected = self.expected[self.position]
                self.outcome = Result(DIVERGED, "the run ended before the log did",
                                      {"index": expected["index"], "frame": expected["frame"],
                                       "last_decide": self.last_decide}, records=self.position)
        return self.outcome


def redecide(trace, emulator, play, state=None, *, states=None, check_emulator=True,
             digest_ranges=None, check_every=None):
    """Run a policy again from a segment's start and stop at the first record that differs.

    The emulator is loaded as ``verify`` loads it, a Recorder is attached and a segment begun
    on a Comparator, then ``play(recorder, trace)`` runs. ``play`` registers its own hooks,
    calls ``recorder.decide`` at each policy step and feeds the logged ``input`` records at
    their frames. It is stopped when the log runs out (0) or at the first difference (1).
    A play that returns first is a divergence. Harness failures are 2.
    """
    try:
        trace = trace if isinstance(trace, Trace) else Trace.read(trace)
        state = _prepare(trace, emulator, state, states, check_emulator)
    except TraceError as error:
        return Result(HARNESS, str(error))
    header = trace.header
    comparator = Comparator(trace, check_emulator=check_emulator)
    recorder = Recorder(emulator, digest_ranges=digest_ranges or header.get("digest_ranges", DIGEST_RANGES),
                        check_every=check_every or header.get("check_every", CHECK_EVERY))
    try:
        try:
            recorder.begin(comparator, state)
            play(recorder, trace)
        except _Stop:
            pass
        return comparator.finish()
    finally:
        recorder.detach()


def main(argv=None):
    """``pokecore trace verify SEGMENT --rom ROM``: exit 0, 1 or 2 as ``verify`` returns."""
    import argparse
    import io
    import sys
    parser = argparse.ArgumentParser(prog="pokecore trace")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="replay a trace segment with no policy")
    check.add_argument("segment", help="a .jsonl.gz trace segment")
    check.add_argument("--rom", required=True, help="the cartridge ROM the trace was recorded on")
    check.add_argument("--state", help="the start state, default the kept one beside the segment")
    check.add_argument("--states", help="folder of kept states, default the segment's folder")
    check.add_argument("--any-emulator", action="store_true", help="replay on another pyboy-rs version")
    args = parser.parse_args(argv)
    try:
        trace = Trace.read(args.segment)
        from .emulator import Emulator
        rom = Path(args.rom).read_bytes()
        state = Path(args.state).read_bytes() if args.state else None
        settings = trace.header.get("settings") or {}
        options = {name: settings[key] for key, name in (("sound_emulated", "sound_emulated"),
                                                          ("sample_rate", "sound_sample_rate")) if key in settings}
        if "color_palette" in settings:
            options["color_palette"] = tuple(settings["color_palette"])
        emulator = Emulator(io.BytesIO(rom), **options)
    except (TraceError, ImportError, OSError, ValueError) as error:
        print(f"pokecore trace: {error}", file=sys.stderr)
        return HARNESS
    with emulator:
        result = verify(trace, emulator, state, states=args.states, check_emulator=not args.any_emulator)
    print(result.message)
    if result.details:
        print(encoded(result.details))
    return result.code
