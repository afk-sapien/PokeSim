"""Bounded live PCM and compatibility with silent PyBoy 2.7.0 checkpoints."""
from collections import deque
from importlib.metadata import version
import math
import struct
import threading
import time

SAMPLE_RATE = 48000
WATCH_GRACE = 0.75
BUFFER_SECONDS = 0.4
MAX_FRAMES = 1024


class AudioFeed:
    def __init__(self):
        self.lock = threading.Lock()
        self.until = 0.0
        self.sequence = 0
        self.frames = deque(maxlen=MAX_FRAMES)

    def active(self):
        return time.monotonic() < self.until

    def publish(self, pcm):
        with self.lock:
            self.sequence += 1
            now = time.monotonic()
            self.frames.append((self.sequence, now, bytes(pcm)))
            while self.frames and self.frames[0][1] < now - BUFFER_SECONDS:
                self.frames.popleft()

    def clear(self):
        with self.lock:
            self.frames.clear()

    def read(self, after, state):
        now = time.monotonic()
        with self.lock:
            if now >= self.until or state != 'playing':
                self.frames.clear()
            self.until = now + WATCH_GRACE
            # A new listener starts at the live edge. Slow listeners never build a backlog.
            data = b''.join(pcm for seq, _, pcm in self.frames if seq > after) if after >= 0 else b''
            speed = 1.0
            if len(self.frames) > 1:
                first, last = self.frames[0], self.frames[-1]
                elapsed = last[1] - first[1]
                if elapsed > 0:
                    speed = max(0.1, min(1024.0, (last[0] - first[0]) / elapsed / 60))
            return self.sequence, data, speed


def enable_checkpoint_sound(raw):
    """Repair only disabled APU clocks in a supported in-memory checkpoint.

    PyBoy saves disabled sound clocks as MAX_CYCLES and restores them even when
    sound_emulated=True. Old files are never rewritten. The offsets below follow
    the pinned PyBoy 2.7.0 DMG v15 CPU, LCD, and Sound serializers. Unknown formats
    pass through untouched. A real-ROM round-trip test guards this adapter.
    """
    # Motherboard header, CPU registers, then monochrome LCD state.
    apu = 5 + 26 + 8192 + 160 + 11 + 144 * 5 + 5 + 24 + 1
    clocks = apu + 24 + 1602 + 1
    if (version('pyboy') != '2.7.0' or len(raw) < clocks + 67
            or raw[0] != 15 or raw[4] != 0):
        return raw
    head, samples, period = struct.unpack_from('<QQd', raw, apu)
    targets = struct.unpack_from('<ddQ', raw, clocks)
    if (head != 0 or samples != 800 or not math.isclose(period, 70224 / 800)
            or targets != (float(1 << 31), float(1 << 31), 1 << 31)):
        return raw
    data = bytearray(raw)
    cycles = struct.unpack_from('<Q', raw, clocks + 24)[0]
    struct.pack_into('<ddQ', data, clocks, cycles + period, cycles + 8192, math.ceil(cycles + period))
    # Disabled emulation ignored all register writes. Power on and route future
    # game music to both channels. Notes resume when the game next writes them.
    data[clocks + 56] = 0x80
    data[clocks + 58:clocks + 66] = bytes((128, 64, 32, 16, 8, 4, 2, 1))
    data[clocks + 66] = 0x77
    return bytes(data)
