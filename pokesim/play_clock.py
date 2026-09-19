"""Persistent simulated playtime, independent of cartridge limits and save rewinds."""


class PlayClock:
    def __init__(self, data=None):
        data = data or {}
        self.frames = int(data.get('frames', 0))
        self.initialized = bool(data.get('initialized', False))
        self.lower_bound = bool(data.get('lower_bound', False))

    def seed(self, cartridge_seconds):
        if not self.initialized:
            self.frames = int(cartridge_seconds) * 60
            self.lower_bound = cartridge_seconds >= 255 * 3600
            self.initialized = True

    def advance(self, frames):
        if self.initialized:
            self.frames += frames

    def restore(self, data):
        if data:
            other = PlayClock(data)
            self.frames = max(self.frames, other.frames)
            self.initialized = self.initialized or other.initialized
            self.lower_bound = self.lower_bound or other.lower_bound

    def state_dict(self):
        return {'frames': self.frames, 'initialized': self.initialized,
                'lower_bound': self.lower_bound}

    def status(self):
        seconds = self.frames // 60
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return {'seconds': seconds, 'display': f'{hours}:{minutes:02d}:{secs:02d}',
                'lower_bound': self.lower_bound, 'source': 'app'}
