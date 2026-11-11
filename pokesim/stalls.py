"""Notice a run that keeps playing without achieving anything."""
from __future__ import annotations

import logging
import re
import threading

from .state import journal

log = logging.getLogger(__name__)

FRAMES_PER_GAME_MINUTE = 3600
# The first autosave after progress, kept under this name so a capture can start from before the stall.
BEFORE_STALL_CHECKPOINT = 'before-stall.state'
# The journal kinds a Red, Blue or Yellow scenario report lists as achievements. A managed trade is
# arranged by the coordinator, so it says nothing about the run's own progress.
PROGRESS_EVENTS = ('badge', 'catch', 'evolve', 'obtain', 'champion', 'item', 'trainer', 'level', 'map')
# Red, Blue and Yellow also restart the stall clock when the run holds more Pokémon, so a long hunt
# that catches species the Pokédex already has is not a stall. A held rise is churn (goal-system.md
# section 4), and the hunt's encounter rate is what should tell a healthy hunt apart. This setting goes
# when that rate leaves shadow, in the switch to net rows. Gold, Silver and Crystal never count it.
GEN1_HELD_RISE = True


class StallWatch:
    """Game time decides a stall, so pace does not matter. Real time only paces the alert and its
    repeat, so Max pace does not send one every few minutes.

    The frames are PlayClock frames, which a reload never takes back. A reload is not progress, so the
    quiet stretch goes on through every reload that tries to escape it."""

    def __init__(self, game_minutes=120, real_minutes=15, repeat_hours=6):
        self.game_frames = game_minutes * FRAMES_PER_GAME_MINUTE
        self.real_seconds = real_minutes * 60
        self.repeat_seconds = repeat_hours * 3600
        self.frame = self.since = self.alerted = None
        # True until the next autosave, which is then the save to keep from before any stall.
        self.fresh = True
        # The clocks from before a boss attempt under way, which a loss to the boss puts back.
        self.held = None
        # The start frame of the quiet stretch that already has a capture.
        self.captured = None

    def progress(self, frame, now):
        self.frame, self.since, self.alerted, self.fresh, self.captured = frame, now, None, True, None

    def attempt(self):
        """Start holding the clocks for a boss attempt. True when this starts a new attempt."""
        if self.held is not None:
            return False
        self.held = (self.frame, self.since, self.alerted)
        return True

    def settle(self):
        """End a boss attempt that did not black out, so the progress it made stands."""
        self.held = None

    def lost(self):
        """Put back the clocks from before a boss attempt that blacked out, so its progress does not count."""
        if self.held is not None:
            self.frame, self.since, self.alerted = self.held
            self.held = None

    def quiet(self, frame, now):
        """Game minutes and real minutes since the last progress, starting the clocks on first use."""
        if self.frame is None:
            self.frame, self.since, self.alerted = frame, now, None
        return max(0, frame - self.frame) // FRAMES_PER_GAME_MINUTE, int(now - self.since) // 60

    def game_minutes(self, frame):
        """Game minutes since the last progress, for the status page. Like ``stalled`` it changes nothing."""
        if frame is None or self.frame is None:
            return 0
        return max(0, frame - self.frame) // FRAMES_PER_GAME_MINUTE

    def stalled(self, frame):
        """Whether the game clock has passed the stall limit since the last progress.

        It changes nothing, so the web status thread can ask at any time without moving the clocks
        the emulator thread keeps.
        """
        return (bool(self.game_frames) and frame is not None and self.frame is not None
                and frame - self.frame >= self.game_frames)

    def check(self, frame, now):
        """Return the quiet minutes when an alert is due, otherwise None."""
        quiet = self.quiet(frame, now)
        if (not self.stalled(frame) or now - self.since < self.real_seconds
                or self.alerted is not None and now - self.alerted < self.repeat_seconds):
            return None
        self.alerted = now
        return quiet

    def capture_due(self, frame):
        """True once for each quiet stretch past the game-minute limit, so its capture never waits
        for the real-minute pacing of the alert. Call it after ``check``, which starts the clocks."""
        if not self.stalled(frame) or self.captured == self.frame:
            return False
        self.captured = self.frame
        return True


def held(snapshot):
    """Pokémon in the party and every box. A catch of a species already registered is still progress."""
    return len(snapshot.party) + (sum(snapshot.box_counts) if snapshot.box_counts else len(snapshot.boxed_pokemon))


def held_rose(previous, snapshot):
    """True when a Red, Blue or Yellow run holds more Pokémon than at the previous snapshot (GEN1_HELD_RISE)."""
    return (GEN1_HELD_RISE and previous is not None and previous.valid and snapshot.valid
            and held(snapshot) > held(previous))


# Events a gift and release loop cannot fake. A received gift, an item and a release are left out.
REAL_PROGRESS = ('badge', 'catch', 'event_return', 'evolve', 'hatch', 'champion', 'trainer', 'level', 'map')
# Repeats that count as a loop: the same Pokémon received and released.
LOOP_LIMIT = 6
LOOP_EVENTS = 400
# The loop guard reads the journal at most once in this many game frames, half a game minute.
SCAN_FRAMES = 1800
# How far back a progress entry is compared after a reload. A reload rewinds the run, and the replay
# journals the same maps, trainers and levels again, which is not progress.
REPLAY_EVENTS = 2000
# Gen II names the species, Gen I the nickname and then the species in brackets.
_RECEIVED = re.compile(r'^Received (?:[^(]+ \()?(.+?)\)? (?:from|for) ')
_RELEASED = re.compile(r'^Said goodbye to a spare (.+?)(?: Lv \d+)?$')
# A return caught or a gift completed. "Has returned" and "available" only open the next visit.
_RETURNED = re.compile(r'^(?:Caught the returning (.+)|Completed (?:the )?(.+?)(?: gift| exchange)?)$')


def species_key(name):
    """One key per species for both spellings: Gen I gifts say SQUIRTLE, MR_MIME or NIDORAN_F, releases
    Squirtle, Mr. Mime or Nidoran♀."""
    return re.sub(r"[\s.'’_]", '', name.casefold().replace('♀', 'f').replace('♂', 'm'))


class LoopGuard:
    """Notice a run caught repeating itself since its last real progress, in either generation.

    Live, a League gift went in and the same starter came out at every PC visit, hundreds of times,
    and each gift counted as progress, so neither the reload limit nor the stall alert ever fired.
    Once the same gift and release repeats LOOP_LIMIT times, the run asks for help, gifts stop and
    reloading stops, until it makes real progress again. The reload ladder counts reloads itself.

    ``clock`` counts game frames, PlayClock frames in both emulators, so a scan falls at the same
    point of a replay at any pace. ``replaying`` says the run has reloaded since its last new high,
    so a journal entry that repeats a recent one is the replay. Only the emulator thread scans. The
    web status thread reads ``reason``, so when it asks cannot move a scan. The state is still
    behind a lock.
    """

    def __init__(self, clock, limit=LOOP_LIMIT, every=SCAN_FRAMES, replaying=lambda: False):
        self.limit, self.every, self.clock, self.replaying = limit, every, clock, replaying
        self.since, self.scanned, self.returned = None, None, {}
        self.reason, self.checked = None, None
        # The last real progress from before a boss attempt under way.
        self.held = None
        # A new loop reason that the emulator has not kept a capture of yet (take_trip).
        self.tripped = None
        self.lock = threading.Lock()

    def hold(self, store):
        """Note where real progress stood as a boss attempt starts (Supervisor.watch_boss)."""
        with self.lock:
            with store.reading() as db:
                self._advance(db)
            self.held = self.since

    def settle(self):
        """Keep the progress of a boss attempt that ended without a blackout."""
        with self.lock:
            self.held = None

    def lost(self, store):
        """Drop the progress of a boss attempt that was lost. Its entries are scanned past, and
        ``since`` goes back to where it stood when it started."""
        with self.lock:
            if self.held is None:
                return
            with store.reading() as db:
                self._advance(db)
            self.since, self.held, self.checked = self.held, None, None

    def looping(self, store):
        """Why the run is in a loop, or None. Reads the journal at most once every ``every`` frames.

        A clock that went back, as on a new game, scans again at once.
        """
        with self.lock:
            now = self.clock()
            if self.checked is not None and 0 <= now - self.checked < self.every:
                return self.reason
            self.checked = now
            with store.reading() as db:
                self._advance(db)
                rows = journal.turnover(db, self.since or 0, LOOP_EVENTS)
            received, released, names = {}, {}, {}
            for kind, title in rows:
                match = (_RECEIVED if kind == 'obtain' else _RELEASED).match(title)
                if match:
                    key = species_key(match.group(1))
                    counts = received if kind == 'obtain' else released
                    counts[key] = counts.get(key, 0) + 1
                    if kind == 'release':
                        names[key] = match.group(1)
            reason = None
            churn = max(((min(count, received.get(key, 0)), key) for key, count in released.items()), default=(0, ''))
            if churn[0] >= self.limit:
                reason = f'It received and released {names[churn[1]]} {churn[0]} times without other progress'
            if reason and reason != self.reason:
                log.error('Loop guard: %s', reason)
                self.tripped = reason
            self.reason = reason
            return reason

    def take_trip(self):
        """The reason of a loop noticed since the last call, or None, so each new loop keeps one capture.
        A loop noticed by a reward check waits here for the emulator's next guard check."""
        with self.lock:
            tripped, self.tripped = self.tripped, None
            return tripped

    def _advance(self, db):
        """Move ``since`` to the newest real progress entry. Only entries after the last scan are read,
        and after a reload one that repeats a recent entry is the replay, not progress.

        A caught return or completed gift counts once it has been kept for a check, so one the PC
        releases straight away, as Sudowoodo was 11 seconds after its return, is not progress.
        """
        kinds = (*REAL_PROGRESS, 'release')
        if self.scanned is None:
            # A release already in the journal is scanned past, but only real progress moves ``since``.
            self.since, self.scanned = journal.marked(db, kinds)
            self.since, self.scanned = self.since or 0, self.scanned or 0
            return
        fresh = journal.marked_after(db, self.scanned, kinds)
        now = self.clock()
        for row_id, kind, title in fresh:
            self.scanned = row_id
            if kind == 'release':
                match = _RELEASED.match(title)
                if match:
                    self.returned.pop(species_key(match.group(1)), None)
                continue
            if self.replaying() and journal.repeats(db, row_id - REPLAY_EVENTS, row_id - 1, kind, title):
                continue
            if kind == 'event_return':
                match = _RETURNED.match(title)
                if match:
                    self.returned[species_key(match.group(1) or match.group(2))] = (row_id, now)
                continue
            self.since = row_id
        for key, (row_id, seen) in list(self.returned.items()):
            if now - seen >= self.every:
                del self.returned[key]
                self.since = max(self.since, row_id)
