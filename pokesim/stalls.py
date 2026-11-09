"""Notice a run that keeps playing without achieving anything."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
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
        # The clocks from before a boss attempt under way, which a loss to the boss puts back.
        self.held = None

    def progress(self, frame, now):
        self.frame, self.since, self.alerted, self.fresh = frame, now, None, True

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


def boss_attempt(stall, guard, store, boss, blackout):
    """Hold back the progress of a boss attempt until it ends, and drop it when the attempt blacks out.

    A team too weak for the Elite Four lost to Lance for 12 hours, and each run earned experience,
    levels and trainer wins on the way, so the stall alert never fired. A loss to a boss is never
    progress. ``boss`` says an attempt is under way, ``blackout`` that the party just fainted.
    """
    if blackout and stall.held is not None:
        stall.lost()
        if guard is not None:
            guard.lost(store)
    elif boss:
        if stall.attempt() and guard is not None:
            guard.hold(store)
    elif stall.held is not None:
        stall.settle()
        if guard is not None:
            guard.settle()


def stalled_state(live, waiting, stuck, loop):
    """Whether the status shows a run as stalled: live, stuck or looping, and never while it waits."""
    return bool(live and not waiting and (stuck or loop))


# Events a gift and release loop cannot fake. A received gift, an item and a release are left out.
REAL_PROGRESS = ('badge', 'catch', 'event_return', 'evolve', 'hatch', 'champion', 'trainer', 'level', 'map')
# Repeats that count as a loop: the same Pokémon received and released, or the same save reloaded.
LOOP_LIMIT = 6
LOOP_EVENTS = 400
# How far back a progress entry is compared after a reload. A reload rewinds the run, and the replay
# journals the same maps, trainers and levels again, which is not progress.
REPLAY_EVENTS = 2000
# Reload counts are kept in the adventure, so a worker restart does not forget a save it keeps reloading.
RELOADS_KEY = 'loop-guard-reloads-v1'
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
    The same save was also reloaded over and over. Once either repeats LOOP_LIMIT times, the run
    asks for help, gifts stop and reloading stops, until it makes real progress again.

    The web status thread and the emulator thread both ask, so the state is behind a lock.
    """

    def __init__(self, limit=LOOP_LIMIT, every=30, clock=time.time):
        self.limit, self.every, self.clock = limit, every, clock
        self.reloads, self.since, self.scanned, self.returned = {}, None, None, {}
        self.reason, self.checked, self.saved = None, None, {}
        # The last real progress and the reload counts from before a boss attempt under way.
        self.held = None
        self.lock = threading.Lock()

    def reloaded(self, name):
        with self.lock:
            self.reloads[name] = self.reloads.get(name, 0) + 1
            self.checked = None

    def hold(self, store):
        """Note where real progress stood as a boss attempt starts (stalls.boss_attempt)."""
        with self.lock:
            with store.lock:
                self._advance(store)
            self.held = (self.since, dict(self.reloads))

    def settle(self):
        """Keep the progress of a boss attempt that ended without a blackout."""
        with self.lock:
            self.held = None

    def lost(self, store):
        """Drop the progress of a boss attempt that blacked out. Its entries are scanned past, and
        ``since`` and the reload counts go back to where they stood when it started."""
        with self.lock:
            if self.held is None:
                return
            with store.lock:
                self._advance(store)
            self.since, reloads = self.held
            for name, count in reloads.items():
                self.reloads[name] = max(self.reloads.get(name, 0), count)
            self.held, self.checked = None, None

    def looping(self, store):
        """Why the run is in a loop, or None. Reads the journal at most once every ``every`` seconds."""
        with self.lock:
            now = self.clock()
            if self.checked is not None and now - self.checked < self.every:
                return self.reason
            self.checked = now
            with store.lock:
                self._advance(store)
                self._save(store)
                rows = store.db.execute("SELECT type, title FROM events WHERE id > ? AND type IN ('obtain', 'release') "
                                        'ORDER BY id DESC LIMIT ?', (self.since or 0, LOOP_EVENTS)).fetchall()
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
            elif self.reloads and max(self.reloads.values()) >= self.limit:
                name, count = max(self.reloads.items(), key=lambda item: item[1])
                reason = f'It reloaded {name} {count} times without progress'
            if reason and reason != self.reason:
                log.error('Loop guard: %s', reason)
            self.reason = reason
            return reason

    def _save(self, store):
        if self.reloads == self.saved:
            return
        try:
            with store.db:
                store.db.execute('INSERT OR REPLACE INTO kv(k,v) VALUES (?,?)', (RELOADS_KEY, json.dumps(self.reloads)))
        except sqlite3.Error:
            log.warning('Could not keep the loop guard reload counts', exc_info=True)
            return
        self.saved = dict(self.reloads)

    def _advance(self, store):
        """Move ``since`` to the newest real progress entry. Only entries after the last scan are read,
        and after a reload one that repeats a recent entry is the replay, not progress.

        A caught return or completed gift counts once it has been kept for a check, so one the PC
        releases straight away, as Sudowoodo was 11 seconds after its return, is not progress.
        """
        kinds = (*REAL_PROGRESS, 'release')
        marks = ','.join('?' * len(kinds))
        if self.scanned is None:
            row = store.db.execute('SELECT v FROM kv WHERE k = ?', (RELOADS_KEY,)).fetchone()
            saved = json.loads(row[0]) if row and row[0] else {}
            self.saved = dict(saved)
            for name, count in saved.items():
                self.reloads[name] = self.reloads.get(name, 0) + int(count)
            # A release already in the journal is scanned past, but only real progress moves ``since``.
            self.since, self.scanned = store.db.execute(
                f"SELECT MAX(CASE WHEN type != 'release' THEN id END), MAX(id) FROM events WHERE type IN ({marks})",
                kinds).fetchone()
            self.since, self.scanned = self.since or 0, self.scanned or 0
            return
        fresh = store.db.execute(f'SELECT id, type, title FROM events WHERE id > ? AND type IN ({marks}) ORDER BY id',
                                 (self.scanned, *kinds)).fetchall()
        now = self.clock()
        for row_id, kind, title in fresh:
            self.scanned = row_id
            if kind == 'release':
                match = _RELEASED.match(title)
                if match:
                    self.returned.pop(species_key(match.group(1)), None)
                continue
            if self.reloads and store.db.execute(
                    'SELECT 1 FROM events WHERE id BETWEEN ? AND ? AND type = ? AND title = ? LIMIT 1',
                    (row_id - REPLAY_EVENTS, row_id - 1, kind, title)).fetchone():
                continue
            if kind == 'event_return':
                match = _RETURNED.match(title)
                if match:
                    self.returned[species_key(match.group(1) or match.group(2))] = (row_id, now)
                continue
            self.since, self.reloads = row_id, {}
        for key, (row_id, seen) in list(self.returned.items()):
            if now - seen >= self.every:
                del self.returned[key]
                self.since, self.reloads = max(self.since, row_id), {}
