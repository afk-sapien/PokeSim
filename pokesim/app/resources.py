"""Small, bounded samples of a single adventure worker's resource use."""
import math
import threading
import time

import psutil


class ProcessUsage:
    def __init__(self, pid):
        self.process = psutil.Process(pid)
        self.lock = threading.Lock()
        self.previous = None
        self.cached = None

    def sample(self):
        with self.lock:
            now = time.monotonic()
            try:
                if not self.process.is_running():
                    return None
                if self.previous and now - self.previous[0] < 2:
                    return self.cached
                with self.process.oneshot():
                    times = self.process.cpu_times()
                    cpu = times.user + times.system
                    memory = self.process.memory_info().rss
                percent = None
                if self.previous and now > self.previous[0]:
                    percent = round(max(0, cpu - self.previous[1]) * 100 / (now - self.previous[0]), 1)
                self.previous = (now, cpu)
                self.cached = {'cpu_percent': percent, 'memory_bytes': memory}
                return self.cached
            except (psutil.Error, OSError):
                self.previous = self.cached = None
                return None


def recent_activity(previous, location, now):
    """Keep three observed location changes, without collecting raw worker logs."""
    rows = list(previous.get('recent_activity') or [])[:3]
    if not rows or rows[0]['message'] != location:
        rows.insert(0, {'time': now, 'message': location})
    return rows[:3]


class ObservedSpeed:
    """Recent worker throughput from executed frames, never restored save progress."""
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = None
        self.value = None

    def observe(self, performance):
        frames = (performance or {}).get('frames')
        sampled_at = (performance or {}).get('sampled_at')
        with self.lock:
            if (type(frames) is not int or frames < 0
                    or type(sampled_at) not in (int, float) or not math.isfinite(sampled_at)):
                self.previous = self.value = None
                return
            self.value = None
            if self.previous:
                elapsed = sampled_at - self.previous[1]
                delta = frames - self.previous[0]
                if 0 < elapsed <= 15 and delta >= 0:
                    self.value = round(delta / (60 * elapsed), 1)
            self.previous = (frames, sampled_at)

    def sample(self):
        with self.lock:
            if self.previous is None:
                state = 'measuring'
            elif time.monotonic() - self.previous[1] > 15:
                state = 'unavailable'
            else:
                state = 'ready' if self.value is not None else 'measuring'
            return {'observed_speed': self.value if state == 'ready' else None, 'speed_status': state}
