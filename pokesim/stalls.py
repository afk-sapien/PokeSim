"""Notice a run that keeps playing without achieving anything."""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger(__name__)

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
        # True until the next autosave, which is then the save to keep from before any stall.
        self.fresh = True

    def progress(self, frame, now):
        self.frame, self.since, self.alerted, self.fresh = frame, now, None, True

    def quiet(self, frame, now):
        """Game minutes and real minutes since the last progress, starting the clocks on first use."""
        if self.frame is None or frame < self.frame:
            # A reloaded save restarts the clocks, but it is not progress: the save kept from
            # before the trouble must outlive the reloads that try to escape it.
            self.frame, self.since, self.alerted = frame, now, None
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


def experience(snapshot):
    """Experience across the party. Grinding for a gym earns it steadily between level milestones,
    while a menu loop or a battle that cannot end earns none."""
    return sum(getattr(mon, 'experience', 0) or 0 for mon in snapshot.party)


def advanced(previous, snapshot):
    """True when the run caught something or earned experience since the previous snapshot."""
    return held(snapshot) > held(previous) or (len(snapshot.party) == len(previous.party)
                                               and experience(snapshot) > experience(previous))



# Events a gift and release loop cannot fake. A received gift, an item and a release are left out.
REAL_PROGRESS = ('badge', 'catch', 'evolve', 'champion', 'trainer', 'level', 'map')
# Repeats that count as a loop: the same Pokémon received and released, or the same save reloaded.
LOOP_LIMIT = 6
LOOP_EVENTS = 400
# Gen II names the species, Gen I the nickname and then the species in brackets.
_RECEIVED = re.compile(r'^Received (?:[^(]+ \()?(.+?)\)? (?:from|for) ')
_RELEASED = re.compile(r'^Said goodbye to a spare (.+?)(?: Lv \d+)?$')


class LoopGuard:
    """Notice a run caught repeating itself since its last real progress, in either generation.

    Live, a League gift went in and the same starter came out at every PC visit, hundreds of times,
    and each gift counted as progress, so neither the reload limit nor the stall alert ever fired.
    The same save was also reloaded over and over. Once either repeats LOOP_LIMIT times, the run
    asks for help, gifts stop and reloading stops, until it makes real progress again.
    """

    def __init__(self, limit=LOOP_LIMIT, every=30, clock=time.time):
        self.limit, self.every, self.clock = limit, every, clock
        self.reloads, self.since = {}, None
        self.reason, self.checked = None, None

    def reloaded(self, name):
        self.reloads[name] = self.reloads.get(name, 0) + 1
        self.checked = None

    def looping(self, store):
        """Why the run is in a loop, or None. Reads the journal at most once every ``every`` seconds."""
        now = self.clock()
        if self.checked is not None and now - self.checked < self.every:
            return self.reason
        self.checked = now
        marks = ','.join('?' * len(REAL_PROGRESS))
        with store.lock:
            latest = store.db.execute(f'SELECT MAX(id) FROM events WHERE type IN ({marks})', REAL_PROGRESS).fetchone()[0]
            rows = store.db.execute("SELECT type, title FROM events WHERE id > ? AND type IN ('obtain', 'release') "
                                    'ORDER BY id DESC LIMIT ?', (latest or 0, LOOP_EVENTS)).fetchall()
        if latest != self.since:
            self.since, self.reloads = latest, {}
        received, released = {}, {}
        for kind, title in rows:
            match = (_RECEIVED if kind == 'obtain' else _RELEASED).match(title)
            if match:
                counts = received if kind == 'obtain' else released
                counts[match.group(1)] = counts.get(match.group(1), 0) + 1
        reason = None
        churn = max(((min(count, received.get(name, 0)), name) for name, count in released.items()), default=(0, ''))
        if churn[0] >= self.limit:
            reason = f'It received and released {churn[1]} {churn[0]} times without other progress'
        elif self.reloads and max(self.reloads.values()) >= self.limit:
            name, count = max(self.reloads.items(), key=lambda item: item[1])
            reason = f'It reloaded {name} {count} times without progress'
        if reason and reason != self.reason:
            log.error('Loop guard: %s', reason)
        self.reason = reason
        return reason
