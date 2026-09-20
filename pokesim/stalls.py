"""Notice a run that keeps playing without achieving anything."""
from __future__ import annotations

FRAMES_PER_GAME_MINUTE = 3600
# A managed trade is arranged by the coordinator, so it says nothing about the run's own progress.
PROGRESS_EVENTS = ('badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level', 'map')


class StallWatch:
    """Both clocks must pass: game time so pace does not matter, real time so Max pace does not spam."""

    def __init__(self, game_minutes=120, real_minutes=15, repeat_hours=6):
        self.game_frames = game_minutes * FRAMES_PER_GAME_MINUTE
        self.real_seconds = real_minutes * 60
        self.repeat_seconds = repeat_hours * 3600
        self.frame = self.since = self.alerted = None

    def progress(self, frame, now):
        self.frame, self.since, self.alerted = frame, now, None

    def quiet(self, frame, now):
        """Game minutes and real minutes since the last progress, starting the clocks on first use."""
        if self.frame is None or frame < self.frame:
            self.progress(frame, now)
        return (frame - self.frame) // FRAMES_PER_GAME_MINUTE, int(now - self.since) // 60

    def stalled(self, frame, now):
        self.quiet(frame, now)
        return bool(self.game_frames) and frame - self.frame >= self.game_frames and now - self.since >= self.real_seconds

    def check(self, frame, now):
        """Return the quiet minutes when an alert is due, otherwise None."""
        if not self.stalled(frame, now) or (self.alerted is not None and now - self.alerted < self.repeat_seconds):
            return None
        self.alerted = now
        return self.quiet(frame, now)


def held(snapshot):
    """Pokémon in the party and every box. A catch of a species already registered is still progress."""
    return len(snapshot.party) + (sum(snapshot.box_counts) if snapshot.box_counts else len(snapshot.boxed_pokemon))

