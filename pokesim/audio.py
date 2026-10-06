"""Bounded live PCM delivery."""
from pokesim_core.checkpoint_audio import enable_checkpoint_sound as enable_checkpoint_sound
from collections import deque
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
