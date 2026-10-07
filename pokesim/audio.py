"""Bounded live PCM delivery."""
from pokesim_core.checkpoint_audio import enable_checkpoint_sound as enable_checkpoint_sound
from collections import deque, namedtuple
import threading
import time

SAMPLE_RATE = 48000
# Keep enough history for a client jitter buffer to ride out a multi-second stall and catch up.
BUFFER_SECONDS = 2.0
# A listener that goes quiet for less than the buffer keeps its history. The ring is only thrown
# away once nobody could still use it, so the two must not disagree.
WATCH_GRACE = BUFFER_SECONDS
MAX_FRAMES = 1024
# Above this pace the pitch is meaningless, so no audio is sent. Matches the page's limit.
MAX_SPEED = 4.5
SPEED_WINDOW = 1.0

Packet = namedtuple('Packet', 'sequence data speed dropped')


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
        """Everything newer than the caller's cursor, without truncation.

        ``dropped`` counts frames the caller missed because they aged out of the ring.
        """
        now = time.monotonic()
        with self.lock:
            if now >= self.until or state != 'playing':
                self.frames.clear()
            self.until = now + WATCH_GRACE
            # A new listener starts at the live edge, so only a known cursor receives data.
            wanted = [frame for frame in self.frames if frame[0] > after] if after >= 0 else []
            if wanted:
                dropped = max(0, wanted[0][0] - after - 1)
            else:
                # Nothing kept for a known cursor means every newer frame was discarded.
                dropped = max(0, self.sequence - after) if after >= 0 else 0
            speed = 1.0
            if len(self.frames) > 1:
                last = self.frames[-1]
                first = last
                for frame in reversed(self.frames):
                    if frame[1] < last[1] - SPEED_WINDOW:
                        break
                    first = frame
                elapsed = last[1] - first[1]
                if elapsed > 0 and first is not last:
                    speed = max(0.1, min(1024.0, (last[0] - first[0]) / elapsed / 60))
            data = b''.join(pcm for _, _, pcm in wanted)
            return Packet(self.sequence, data, speed, dropped)
