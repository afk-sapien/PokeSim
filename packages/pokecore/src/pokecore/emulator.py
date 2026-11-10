"""Explicit emulator operations backed exclusively by PyBoy RS.

The application owns scheduling, files, budgets, and observation policy. Memory
and register writes are trusted host operations and do not belong in agent APIs.
"""
from __future__ import annotations

import io
from copy import deepcopy
import hashlib
from pathlib import Path

from .errors import CoreCapabilityError
from .rom import require_rom

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
FPS = 4_194_304 / 70_224


CLOCK_UNAVAILABLE = ('This operation requires a PyBoy RS build with real-time clock control '
                     '(pyboy-rs 0.1.2 or newer). The installed build cannot control the cartridge clock.')
_CLOCK_METHODS = ('rtc_export', 'rtc_import', 'rtc_registers', 'set_rtc_registers', 'rtc_state',
                  'set_rtc_timezero', 'clock_now', 'lock_clock', 'unlock_clock', 'advance_clock',
                  'clock_lock_state', 'set_clock_lock_state')


_CLOCK_FEATURES = ("rtc_file", "clock_lock", "clock_lock_state", "advance_clock", "export_rtc")


def clock_control_supported(backend=None):
    """Whether the PyBoy RS build can import, export and lock cartridge clocks.

    Uses the build's own capability flags when it publishes them: ``HAS_CLOCK_CONTROL`` and
    ``has_feature(name)`` on the package (pyboy-rs 0.1.1), or a ``has_rtc`` flag that is False
    on the package or the PyBoy class. It then requires every clock method, so older builds
    without any flag are still detected. Never raises, and says nothing about the cartridge.
    """
    import sys
    module = sys.modules.get("pyboy_rs")
    if backend is None:
        backend = getattr(module, "PyBoy", None)
    if backend is None:
        return False
    if getattr(module, "HAS_CLOCK_CONTROL", True) is False:
        return False
    has_feature = getattr(module, "has_feature", None)
    if callable(has_feature) and not all(has_feature(name) for name in _CLOCK_FEATURES):
        return False
    for holder in (module, backend if isinstance(backend, type) else type(backend)):
        flag = getattr(holder, "has_rtc", None)
        if callable(flag):
            try:
                flag = flag()
            except Exception:
                flag = None
        if flag is False:
            return False
    return all(hasattr(backend, name) for name in _CLOCK_METHODS)


class ReplayDivergence(RuntimeError):
    """Replay failed at a checked interval. details contains detached diagnostics."""

    def __init__(self, details):
        self.details = deepcopy(details)
        super().__init__(f"Replay diverged at checkpoint {details['first_failed_offset']}")


class Memory:
    """Live byte and bank access. Slices return detached lists of bytes."""

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, key):
        self._owner._ensure_open()
        return self._owner._backend.memory[key]

    def read_bytes(self, start, stop):
        """Return detached bytes from the current address-space mapping."""
        self._owner._ensure_open()
        backend = self._owner._backend.memory
        read = getattr(backend, 'read_bytes', None)
        if read is not None:
            return read(start, stop)
        import operator
        start, stop = operator.index(start), operator.index(stop)
        if not 0 <= start <= stop <= 65536:
            raise ValueError('Invalid memory range')
        return bytes(backend[start:stop]) if start != stop else b''

    def read_bank_bytes(self, bank, start, stop):
        """Return detached bytes of ``memory[bank, start:stop]``.

        PyBoy RS 0.1.1 and later serve a range inside one bank window with a single native
        call. Older bindings fall back to their per-address bank reads with identical values.
        """
        self._owner._ensure_open()
        backend = self._owner._backend.memory
        read = getattr(backend, 'read_bank_bytes', None)
        if read is not None:
            return bytes(read(bank, start, stop))
        import operator
        bank, start, stop = operator.index(bank), operator.index(start), operator.index(stop)
        if not 0 <= start <= stop <= 65536:
            raise ValueError('Invalid memory range')
        return bytes(bytearray(backend[bank, start:stop])) if start != stop else b''

    def __setitem__(self, key, value):
        self._owner._ensure_open()
        self._owner._backend.memory[key] = value

    def __iter__(self):
        raise TypeError("Read an explicit memory range")


class Registers:
    """Trusted instrumentation registers, independent of the binding's types."""

    _names = frozenset(("A", "F", "B", "C", "D", "E", "HL", "SP", "PC"))

    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name):
        if name not in self._names:
            raise AttributeError(name)
        self._owner._ensure_open()
        return getattr(self._owner._backend.register_file, name)

    def __setattr__(self, name, value):
        if name not in self._names:
            raise AttributeError(name)
        self._owner._ensure_open()
        setattr(self._owner._backend.register_file, name, value)


class Screen:
    """RGBA output. Borrowed views update at the next tick or load."""

    width = 160
    height = 144

    def __init__(self, owner):
        self._owner = owner

    @property
    def raw_buffer(self):
        self._owner._ensure_open()
        return memoryview(self._owner._backend.screen.raw_buffer).toreadonly()

    @property
    def image(self):
        from PIL import Image
        return Image.frombytes("RGBA", (self.width, self.height), bytes(self.raw_buffer))

    @property
    def ndarray(self):
        import numpy as np
        return np.frombuffer(self.raw_buffer, dtype=np.uint8).reshape(self.height, self.width, 4)


class Audio:
    """Signed 8-bit interleaved stereo samples from the final ticked frame."""

    def __init__(self, owner, sample_rate):
        self._owner = owner
        self.sample_rate = sample_rate

    @property
    def raw_buffer(self):
        self._owner._ensure_open()
        return memoryview(self._owner._backend.sound.raw_buffer).toreadonly()

    @property
    def raw_buffer_head(self):
        self._owner._ensure_open()
        return self._owner._backend.sound.raw_buffer_head


class Emulator:
    """One explicitly advanced machine with isolated cartridge RAM.

    Batched tick renders and samples only its final frame. Use single-frame
    calls for continuous audio or video. No automatic file writes or pacing.
    Hooks run synchronously on the caller's thread. A hook may operate another
    machine, but may not recursively advance the same machine.
    """

    def __init__(self, rom, *, sound_emulated=True, sound_sample_rate=48000,
                 color_palette=(0xffffff, 0x999999, 0x555555, 0), ram_file=None,
                 rtc_file=None, window="null", log_level="ERROR", symbols=None):
        if window != "null":
            raise ValueError("Core emulators are headless")
        try:
            from pyboy_rs import PyBoy
        except ImportError as error:
            raise ImportError("Install pokecore with the emulator extra to use the Rust emulator") from error
        self._closed = False
        raw = rom.read() if hasattr(rom, "read") else Path(rom).read_bytes()
        self.rom_sha256 = hashlib.sha256(raw).hexdigest()
        self._settings = {"sample_rate": sound_sample_rate, "sound_emulated": sound_emulated,
                          "color_palette": list(color_palette)}
        self._ram = ram_file if ram_file is not None else io.BytesIO()
        options = {}
        if rtc_file is not None:
            if not clock_control_supported(PyBoy):
                raise CoreCapabilityError(CLOCK_UNAVAILABLE)
            # The backend keeps this stream and may write it on stop, so give it a private copy.
            data = rtc_file if isinstance(rtc_file, (bytes, bytearray, memoryview)) else rtc_file.read()
            options["rtc_file"] = io.BytesIO(bytes(data))
        self._backend = PyBoy(io.BytesIO(raw), window="null", sound_emulated=sound_emulated,
                              sound_sample_rate=sound_sample_rate, color_palette=color_palette,
                              ram_file=self._ram, log_level=log_level, symbols=symbols, **options)
        self._backend.set_emulation_speed(0)
        self._frame_offset = -self._backend.frame_count
        self.memory = Memory(self)
        self.register_file = Registers(self)
        self.screen = Screen(self)
        self.sound = Audio(self, sound_sample_rate)
        self._pending = []
        self._recording_initial = None

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("The emulator is closed")

    @property
    def _pb(self):
        """Legacy 0.1.x attribute name for the backend. Core 0.1.x applications read it."""
        return self._backend

    @property
    def cartridge_title(self):
        self._ensure_open()
        return self._backend.cartridge_title

    @property
    def frame_count(self):
        """Completed frames on the Core timeline, including during callbacks."""
        self._ensure_open()
        return self._frame_offset + self._backend.frame_count

    @property
    def pending_inputs(self):
        return tuple(self._pending)

    def set_emulation_speed(self, speed):
        if speed != 0:
            raise ValueError("The application owns wall-clock pacing")
        self._ensure_open()

    def press(self, button):
        self._input(button, True)

    def release(self, button):
        self._input(button, False)

    def _input(self, button, pressed):
        self._ensure_open()
        if button not in BUTTONS:
            raise ValueError("Unknown controller button")
        self._pending.append((button, pressed))

    button_press = press
    button_release = release

    def tick(self, frames=1, render=True, sound=True):
        return self._advance(frames, render, sound)

    def tick_read(self, frames, start, stop, *, render=True, sound=True):
        """Advance and collect a detached range after all synchronous hooks finish."""
        import operator
        start, stop = operator.index(start), operator.index(stop)
        if not 0 <= start <= stop <= 65536:
            raise ValueError('Invalid memory range')
        return self._advance(frames, render, sound, (start, stop))

    def _flush_inputs(self):
        for button, pressed in self._pending:
            if pressed:
                self._backend.button_press(button)
            else:
                self._backend.button_release(button)
        self._pending.clear()

    def _execution_method(self, name):
        self._ensure_open()
        method = getattr(self._backend, name, None)
        if method is None:
            raise CoreCapabilityError('This operation requires the experimental execution-enabled PyBoy RS build')
        return method

    @property
    def clock_control_available(self):
        """Whether the backend build can control cartridge clocks. Never raises while open."""
        self._ensure_open()
        return clock_control_supported(self._backend)

    def _require_clock_control(self):
        self._ensure_open()
        if not clock_control_supported(self._backend):
            raise CoreCapabilityError(CLOCK_UNAVAILABLE)

    def _rtc_method(self, name):
        self._require_clock_control()
        return getattr(self._backend, name)

    def _rtc_property(self, name):
        self._require_clock_control()
        return bool(getattr(self._backend, name))

    @property
    def has_rtc(self):
        """Whether the cartridge has a real-time clock. False on cartridges without one.

        Raises CoreCapabilityError on a backend that cannot control clocks, because that
        build cannot say whether the clock exists. Use clock_control_available to test first.
        """
        return self._rtc_property('rtc_present')

    def export_rtc(self):
        """Return the ten-byte PyBoy 2.7.0 ``.rtc`` file: little-endian f64 base timestamp, halt, day carry.

        The latched registers are not part of the file. Raises ValueError without an RTC.
        While the clock is locked the file is the host-following equivalent: the one that, read on
        the host clock now, shows the time the locked clock shows now (so a real cartridge or an
        unlocked emulator does not see a fake time). The emulator is unchanged. Pair a locked
        checkpoint's ``rtc_clock`` with the checkpoint, not with this file, to resume exactly.
        """
        return bytes(self._rtc_method('rtc_export')())

    def import_rtc(self, data):
        """Load a PyBoy 2.7.0 ``.rtc`` file from bytes or a binary stream.

        Only the first ten bytes are read. Short input, NaN and flags above 1 raise ValueError.
        """
        self._rtc_method('rtc_import')(data if isinstance(data, (bytes, bytearray, memoryview)) else data.read())

    def rtc_registers(self):
        """Seconds, minutes, hours, days (0 to 511), halt and day_carry at the clock's current reading."""
        return self._rtc_method('rtc_registers')()

    def set_rtc_registers(self, **registers):
        """Set any of seconds, minutes, hours, days, halt and day_carry by moving the base timestamp."""
        self._rtc_method('set_rtc_registers')(**registers)

    def rtc_state(self):
        """Base timestamp (timezero), halt, day carry, latch contents and lock status."""
        return self._rtc_method('rtc_state')()

    def set_rtc_timezero(self, timezero):
        """Set the Unix time at which the clock reads zero."""
        self._rtc_method('set_rtc_timezero')(timezero)

    @property
    def clock_locked(self):
        return self._rtc_property('clock_locked')

    def clock_now(self):
        """The Unix time the cartridge uses: the locked time, or host time when unlocked."""
        return self._rtc_method('clock_now')()

    def lock_clock(self, at=None, follow_frames=False):
        """Stop the cartridge reading the host clock.

        Time is ``at`` (default: the current host time) plus advance_clock() calls, plus
        completed frames at 4389/262144 s each when follow_frames is true. Lock before the
        first tick for reproducible runs. Raw hardware states do not carry the lock,
        checkpoints do.
        """
        self._rtc_method('lock_clock')(at=at, follow_frames=follow_frames)

    def unlock_clock(self):
        """Return to host time, continuing from the frozen reading without a jump."""
        self._rtc_method('unlock_clock')()

    def advance_clock(self, seconds):
        """Advance a locked clock by a finite, non-negative number of seconds."""
        self._rtc_method('advance_clock')(seconds)

    def clock_lock_state(self):
        """The lock as a plain dict (base, offset, frames, follow_frames), or None when unlocked.

        Raw hardware states do not carry it. Checkpoints store it as ``rtc_clock``.
        """
        return self._rtc_method('clock_lock_state')()

    def start_sequence(self, steps):
        if self._pending:
            raise RuntimeError('Advance pending Core inputs before starting a sequence')
        return self._execution_method('start_sequence')(steps)

    @property
    def sequence_progress(self):
        self._ensure_open()
        return deepcopy(getattr(self._backend, 'sequence_progress', None))

    def run_sequence(self, max_frames, *, render=True, sound=True, cancelled=None):
        method = self._execution_method('run_sequence')
        return method(max_frames, render=render, sound=sound, cancelled=cancelled,
                      _before_frame=self._flush_inputs)

    def cancel_sequence(self):
        return self._execution_method('cancel_sequence')()

    def start_recording(self, max_frames=100000, *, diagnostic_interval=0, diagnostic_ranges=((0xc000, 0xe000),)):
        method = self._execution_method('start_recording')
        initial = self.checkpoint()
        if diagnostic_interval or diagnostic_ranges != ((0xc000, 0xe000),):
            method(max_frames, diagnostic_interval=diagnostic_interval, diagnostic_ranges=diagnostic_ranges)
        else:
            method(max_frames)
        self._recording_initial = initial

    def stop_recording(self):
        try:
            backend = self._execution_method('stop_recording')()
        finally:
            initial, self._recording_initial = self._recording_initial, None
        return {'format': 1, 'initial': initial, 'final': self.checkpoint(), 'backend': backend}

    def replay(self, recording):
        method = self._execution_method('replay')
        if self._recording_initial is not None:
            raise RuntimeError('Stop recording before replay')
        if recording.get('format') != 1:
            raise ValueError('Unsupported Core recording')
        for name in ('initial', 'final'):
            checkpoint = recording[name]
            self._validate_checkpoint(checkpoint)
            if checkpoint.get('execution') != recording['backend'][name]:
                raise ValueError('Core and backend recording state mismatch')
        validate = getattr(self._backend, 'validate_recording', None)
        if validate is not None:
            validate(recording['backend'])
        self.restore_checkpoint(recording['initial'])
        try:
            result = method(recording['backend'])
        except RuntimeError as error:
            if hasattr(error, 'details'):
                raise ReplayDivergence(error.details) from error
            raise
        self.restore_checkpoint(recording['final'])
        return result

    def start_profiling(self):
        return self._execution_method('start_profiling')()

    def profiling_counters(self):
        return self._execution_method('profiling_counters')()

    def stop_profiling(self):
        return self._execution_method('stop_profiling')()

    def _advance(self, frames, render, sound, read_range=None):
        self._ensure_open()
        if type(frames) is not int or frames < 1:
            raise ValueError("frames must be a positive integer")
        self._flush_inputs()
        if read_range is None:
            return self._backend.tick(frames, render=render, sound=sound)
        combined = getattr(self._backend, 'tick_read', None)
        if combined is not None:
            return combined(frames, *read_range, render=render, sound=sound)
        self._backend.tick(frames, render=render, sound=sound)
        return self.memory.read_bytes(*read_range)

    def symbol_lookup(self, name):
        self._ensure_open()
        return tuple(self._backend.symbol_lookup(name))

    def hook_register(self, bank, address, callback, context):
        self._ensure_open()
        self._backend.hook_register(bank, address, callback, context)

    def hook_deregister(self, bank, address):
        self._ensure_open()
        self._backend.hook_deregister(bank, address)

    def save(self):
        self._ensure_open()
        stream = io.BytesIO()
        self._backend.save_state(stream)
        return stream.getvalue()

    def save_state(self, stream):
        stream.write(self.save())

    def load(self, state):
        """Load raw format-15 hardware state, preserving caller-queued inputs.

        Hardware states omit pending input. Use checkpoint/restore_checkpoint
        to transfer both the hardware and Core's pending input queue.
        """
        self._ensure_open()
        self._backend.load_state(io.BytesIO(state))

    def load_state(self, stream):
        self.load(stream.read())

    def checkpoint(self):
        from .emulator_state import checkpoint_metadata
        has_clock = self._has_rtc_cartridge()
        # The base timestamp is in the state, but the lock's virtual time is not.
        # Always written for clock cartridges, None meaning the clock follows the host.
        lock = self._backend.clock_lock_state() if has_clock else None
        # checkpoint_metadata adds pyboy_version "2.7.0" exactly when PyBoy 2.7.0 could load
        # this checkpoint (format-15 state, no clock lock carried), so PokeSim 0.4.x can roll back to it.
        checkpoint = {"format": 1, **checkpoint_metadata(rtc_clock=lock), "state": self.save(),
                      "pending_inputs": self.pending_inputs, "frames": self.frame_count,
                      "rom_sha256": self.rom_sha256, "settings": deepcopy(self._settings)}
        if hasattr(self._backend, 'execution_checkpoint'):
            checkpoint['format'] = 2
            checkpoint['execution'] = self._backend.execution_checkpoint()
        if has_clock:
            checkpoint['rtc_clock'] = lock
        return checkpoint

    def _has_rtc_cartridge(self):
        return clock_control_supported(self._backend) and bool(getattr(self._backend, 'rtc_present', False))

    def _validate_checkpoint(self, checkpoint, match="version"):
        self._ensure_open()
        from .emulator_state import validate_runtime
        if "emulator" not in checkpoint:
            raise ValueError("Checkpoint requires explicit emulator provenance")
        validate_runtime(checkpoint, exact=match == "exact", version=match != "state_format")
        if checkpoint.get("format") not in (1, 2):
            raise ValueError("Unsupported Core checkpoint")
        if checkpoint.get("rom_sha256") != self.rom_sha256 or checkpoint.get("settings") != self._settings:
            raise ValueError("Checkpoint ROM or emulator settings mismatch")
        frames = checkpoint.get("frames")
        if type(frames) is not int or frames < 0:
            raise ValueError("Invalid checkpoint frame count")
        pending = checkpoint.get("pending_inputs", ())
        for button, pressed in pending:
            if button not in BUTTONS or type(pressed) is not bool:
                raise ValueError("Invalid pending input")
        if 'rtc_clock' in checkpoint:
            lock = checkpoint['rtc_clock']
            if lock is not None and (type(lock) is not dict or set(lock) != {'base', 'offset', 'frames', 'follow_frames'}):
                raise ValueError('Invalid checkpoint clock lock')
            if lock is not None:
                self._validate_locked_checkpoint(checkpoint, lock)
        if checkpoint['format'] == 2:
            if checkpoint['state'] != checkpoint['execution']['state']:
                raise ValueError('Core and backend checkpoint state mismatch')

    def _validate_locked_checkpoint(self, checkpoint, lock):
        """A checkpoint saved with a locked clock needs a backend that can apply that lock."""
        self._require_clock_control()
        from .emulator_state import runtime_provenance
        source, current = checkpoint["emulator"], runtime_provenance()
        if (source.get("backend"), source.get("version")) != (current["backend"], current["version"]):
            # Another backend or version: the raw state cannot be trusted to carry the lock
            # semantics, so only proceed when this machine already has the same lock applied.
            if self._backend.clock_lock_state() != lock:
                raise ValueError(
                    "Checkpoint was saved with a locked clock by a different emulator build. "
                    "Apply the identical lock with lock_clock() and advance_clock() first, or restore on the original build")

    def restore_checkpoint(self, checkpoint, *, match="version"):
        """Restore a checkpoint written by checkpoint().

        match selects how strictly the emulator build must agree: "version" (default)
        requires the same backend, backend version and state format, "state_format"
        accepts any build of the same backend and state format, and "exact" also requires
        the identical compiled binary and binding. A rebuilt or repackaged wheel of the same
        version restores under the default (and the backend itself checks the state format and
        the cartridge, not the build).

        On a cartridge with a clock the checkpoint's lock is applied. A checkpoint with no clock
        data (saved with a live clock, or by an older Core) releases any lock the emulator had,
        without shifting the clock, so the result does not depend on the emulator's earlier state.
        """
        if match not in ("version", "state_format", "exact"):
            raise ValueError("match must be 'version', 'state_format' or 'exact'")
        checkpoint = deepcopy(checkpoint)
        self._validate_checkpoint(checkpoint, match)
        if self._recording_initial is not None:
            raise RuntimeError('Stop recording before restoring')
        if checkpoint['format'] == 2:
            self._execution_method('restore_execution')(checkpoint['execution'])
        else:
            self.load(checkpoint['state'])
        if self._has_rtc_cartridge():
            # A missing key means no lock, the same as None: restore never keeps a stale lock.
            self._rtc_method('set_clock_lock_state')(checkpoint.get('rtc_clock'))
        self._pending = list(checkpoint.get('pending_inputs', ()))
        self._frame_offset = checkpoint['frames'] - self._backend.frame_count

    def screenshot(self):
        buffer = io.BytesIO()
        self.screen.image.save(buffer, format="PNG")
        return buffer.getvalue()

    def audio_samples(self):
        return bytes(self.sound.raw_buffer[:self.sound.raw_buffer_head])

    def stop(self, save=False, ram_file=None, rtc_file=None):
        """Close the emulator. Streams passed here are written, nothing else is.

        rtc_file receives the ten-byte clock file and is ignored on cartridges without a clock.
        """
        if not self._closed:
            # Persistence is explicit. Closing without a stream never writes a file.
            if rtc_file is not None:
                self._require_clock_control()
            extra = {} if rtc_file is None else {"rtc_file": rtc_file}
            self._backend.stop(save=save or ram_file is not None or rtc_file is not None, ram_file=ram_file, **extra)
            self._closed = True

    def close(self):
        self.stop(save=False)

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *_):
        self.close()


class GameBoy(Emulator):
    """Verified Red/Blue adapter with isolated saves and silent hardware."""

    def __init__(self, rom: str | Path, state: bytes | None = None, *, allowed_games=("red", "blue")):
        self.rom_info = require_rom(rom, allowed_games=allowed_games)
        self.rom_sha256 = self.rom_info.sha256
        super().__init__(str(rom), sound_emulated=False, ram_file=io.BytesIO(bytes(32768)))
        try:
            if state is not None:
                self.load(state)
        except BaseException:
            self.close()
            raise


def check_runtime():
    """Exercise the installed native wheel using its public demonstration ROM."""
    rom = demo_rom().read_bytes()
    with Emulator(io.BytesIO(rom), sound_emulated=False) as game:
        game.tick(30)
        if len(game.screen.raw_buffer) != 160 * 144 * 4:
            raise RuntimeError("Invalid emulator framebuffer")


def demo_rom():
    """Path to the redistributable cartridge used by installed-runtime checks."""
    from importlib.resources import files
    return Path(str(files("pyboy_rs").joinpath("assets/default_rom.gb")))
