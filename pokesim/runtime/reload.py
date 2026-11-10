"""The autosaves a stuck run goes back to, and the frame cadence that makes them, in both generations.

Both count the emulator frame, which a reload rewinds together with the saved timers. So a
choice here depends on game time only, never on wall-clock time, file times or emulation speed.
"""
from __future__ import annotations

FRAMES_PER_SECOND = 60
# A reload goes back to a save made at least this much game time before the trouble started.
LOOKBACK_FRAMES = 30 * FRAMES_PER_SECOND


def settled(metadata):
    """Whether a checkpoint was taken with no menu task running and nothing being backed out of.

    A reload drops the running menu task, so a save taken inside a menu brings the run back into a
    screen no plan owns. Saves from before this flag existed count when no menu task was saved.
    """
    if 'settled' in metadata:
        return bool(metadata['settled'])
    return not (metadata.get('policy_state') or {}).get('menu')


def reload_target(store, saves, since_frame):
    """The newest settled autosave made at least LOOKBACK_FRAMES of game time before ``since_frame``.

    Autosaves record the game frame, the clock the stuck guards count in. A save taken inside a menu
    is used only when no settled save is old enough. The oldest save is the fallback.
    """
    early = []
    for path in reversed(saves):
        metadata = store.checkpoint_metadata(path) or {}
        frame = metadata.get('frame')
        if isinstance(frame, int) and frame < since_frame - LOOKBACK_FRAMES:
            if settled(metadata):
                return path
            early.append(path)
    return early[0] if early else saves[0] if saves else None


class Cadence:
    """Due once every ``every`` emulator frames.

    A reload, a rewind or a restart moves the frame back, and the count then starts again from
    there. Left at the old frame, the next save would wait until the run caught up.
    """

    def __init__(self, every, frame=0):
        self.every, self.last = every, frame

    def due(self, frame):
        if frame < self.last:
            self.last = frame
        if frame - self.last < self.every:
            return False
        self.last = frame
        return True
