"""Replay journal history through today's stall checks and the typed progress model side by side.

docs/design/goal-system.md, section 12. The input is a read-only copy of an adventures folder,
never a live data folder. Every database opens read-only. The tool reads the journal, the capture
receipts, the progress, progress_events and statistics tables, kv and the stall bundle reports. It
never reads save state and never writes into its input. An adventure replays the progress_events rows
the writers stored when its window holds any, and rows rebuilt from the journal otherwise.

    python -m pokesim.replay progress run STORES_DIR [STORES_DIR ...] --days 14 --out REPORT_JSON [--labels LABELS_JSON] [--churn-n 10] [--rows stored|reclassified|rebuilt]
    python -m pokesim.replay progress report REPORT_JSON

A labels file is JSON, {"labels": [{"adventure": ID, "start": TS, "end": TS, "stall": true, "note": ""}]}.
A label with "stall": false clears any true stall it overlaps.
"""
import argparse
from bisect import bisect_right
from collections import Counter, deque, namedtuple
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import quote

from pokesim import config, state
from pokesim.app.watchdog import Limits, Watchdog
from pokesim.progress_events import HOUR, JOURNAL, NET
from pokesim.stalls import (FRAMES_PER_GAME_MINUTE, GEN1_HELD_RISE, LOOP_EVENTS, LOOP_LIMIT, PROGRESS_EVENTS,
                            REAL_PROGRESS, LossLoop, LoopGuard, StallWatch, _RECEIVED, _RELEASED, species_key)

GEN2 = frozenset({'gold', 'silver', 'crystal'})
# Gen I's last achievement, emulator.py: the progress events plus a trade.
ACHIEVEMENTS = (*PROGRESS_EVENTS, 'trade')
# The stall clock moves on a new high in badges, event flags, Pokédex entries, areas, experience or
# League wins (Supervisor.progressed, from _note_progress in both emulators). The journal shows these
# entries for them, and a rise in owned comes from the progress table.
NEW_HIGH = frozenset({'badge', 'champion', 'map', 'level', 'trainer', 'hatch', 'item'})
# The guard checks run about once a minute.
TICK = 60
# A gap with no journal entry, receipt or statistics bucket this long means the worker was stopped.
GAP = 75 * 60
# Replay starts this long before the window, so the checks are warm when it opens.
WARMUP = 86400
# Checkpoints per course, as each course's description says.
COURSES = {'Kanto': 11, 'Johto': 10}
MARATHON = re.compile(r'^(Kanto|Johto) Marathon (is on!|finished!|called off)')
GAME_HOURS = re.compile(r'^Stuck\? (\d+) game hours without progress')
REAL_MINUTES = re.compile(r'after (\d+) real minutes')
RELOADED = 'Stuck? The adventure had to reload twice'
GAVE_UP = re.compile(r'^Gave up on ')
HATCHED = re.compile(r'^(.+?) hatched from its Egg')
PLAYTIME = re.compile(r'^(\d+):(\d\d):(\d\d)$')
# The League's rooms in both generations, and Red's room at Mt. Silver, as the journal names them.
LEAGUE_ROOM = re.compile(r"^(Lorelei|Bruno|Agatha|Lance|Will|Koga|Karen|Champion)'s Room$")
RED_ROOM = 'Silver Cave Room 3'
# A badge entry's title names the badge: "Beat Brock! Got the Boulder Badge" or "Earned the Rising Badge".
BADGE = re.compile(r'the (\w+) Badge')
# The badge bits in order: Kanto's are bits 0 to 7 in Red, Blue and Yellow and bits 8 to 15 after
# Johto's in Gold, Silver and Crystal.
KANTO_BADGES = ('boulder', 'cascade', 'thunder', 'rainbow', 'soul', 'marsh', 'volcano', 'earth')
JOHTO_BADGES = ('zephyr', 'hive', 'plain', 'fog', 'mineral', 'storm', 'glacier', 'rising')
GREW = re.compile(r'^(.+?) grew to level (\d+)')

Entry = namedtuple('Entry', 'id ts type title body map playtime')


@dataclass(frozen=True)
class Row:
    """A rebuilt progress_events row."""
    ts: float
    frame: float
    kind: str
    net: int
    key: str = ''


@dataclass
class Episode:
    """A true stall, from its start to the moment something reported it."""
    start_ts: float
    start_frame: float
    end_ts: float
    end_frame: float
    sources: list = field(default_factory=list)


@dataclass(frozen=True)
class Flag:
    ts: float
    frame: float
    check: str
    # The frame of the last progress before a quiet check's flag, which starts its quiet stretch, or None.
    since: float | None = None


@dataclass
class Alarm:
    """What a reader would see: the first flag, and the frames from the start of its quiet stretch, or
    the flag itself, to the last flag that joined it."""
    first: Flag
    start: float
    end: float


@dataclass
class Adventure:
    id: str
    version: str
    events: list
    receipts: list
    progress: list
    shiny: list
    stats: list
    bundles: list
    shadow_rows: int = 0
    # The progress_events rows the writers stored: (ts, frame, kind, species, net, rewound, goal, identity, score).
    stored: list = field(default_factory=list)

    @property
    def gen2(self):
        return self.version in GEN2


def connect(path):
    """Open the app database read-only, so a replay can never change its input. An adventure's own
    database opens with ``state.connect``, which also checks its schema version."""
    return sqlite3.connect(f'file:{quote(str(path))}?mode=ro', uri=True)


def load(folder):
    """Read one adventure folder."""
    folder = Path(folder)
    meta = json.loads((folder / 'adventure.json').read_text(encoding='utf-8')) if (folder / 'adventure.json').exists() else {}
    db = state.connect(folder / 'pokesim.sqlite', read_only=True)
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        def rows(table, sql):
            return db.execute(sql).fetchall() if table in tables else []
        has = {row[1] for row in db.execute('PRAGMA table_info(events)')} if 'events' in tables else set()
        detail = "WHEN type = 'trade' THEN COALESCE(detail, '') " if 'detail' in has else ''
        events = [Entry(*row) for row in rows('events', (
            f"SELECT id, ts, type, title, CASE WHEN type = 'stall' THEN body {detail}"
            "ELSE '' END, map, playtime FROM events ORDER BY id"))]
        receipts = rows('capture_receipts', 'SELECT recorded_at, fingerprint, dex FROM capture_receipts ORDER BY recorded_at')
        columns = {row[1] for row in db.execute('PRAGMA table_info(progress)')} if 'progress' in tables else set()
        extra = ', '.join(name if name in columns else '0' for name in ('level100', 'perfect'))
        progress = rows('progress', f'SELECT ts, badges, owned, league, {extra} FROM progress ORDER BY ts')
        # An older shiny ledger keeps no times, so its shiny Pokémon cannot be placed.
        dated = 'shiny_receipts' in tables and 'ts' in {row[1] for row in db.execute('PRAGMA table_info(shiny_receipts)')}
        shiny = rows('shiny_receipts' if dated else '',"SELECT ts, dex FROM shiny_receipts WHERE kind = 'acquired' AND ts IS NOT NULL ORDER BY ts")
        stats = []
        for ts, data in rows('statistics_history', 'SELECT ts, data FROM statistics_history ORDER BY bucket'):
            frames = json.loads(data).get('active_frames')
            if isinstance(frames, (int, float)):
                stats.append((ts, frames))
        written = {row[1] for row in db.execute('PRAGMA table_info(progress_events)')} if 'progress_events' in tables else set()
        undone = 'rewound' if 'rewound' in written else '0'
        noted = ', '.join(name if name in written else 'NULL' for name in ('goal', 'identity', 'score'))
        stored = rows('progress_events', f'SELECT ts, frame, kind, species, net, {undone}, {noted} FROM progress_events '
                                         'ORDER BY id')
    finally:
        db.close()
    bundles = []
    for path in sorted((folder / 'stalls').glob('stall-*/report.json')):
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            ts = time.mktime(time.strptime(path.parent.name[6:], '%Y%m%dT%H%M%SZ')) - time.timezone
        except (ValueError, OSError):
            continue
        bundles.append((ts, report.get('quiet_game_minutes'), report.get('quiet_real_minutes')))
    return Adventure(meta.get('id', folder.name), meta.get('version', ''), events, receipts, progress, shiny, stats,
                     bundles, len(stored), stored)


class Axis:
    """PlayClock frames by wall time. Between two anchors frames run evenly, outside them at full speed."""

    def __init__(self, points, name):
        self.ts, self.frames, self.name = [], [], name
        for ts, frames in sorted(points):
            if self.frames and frames < self.frames[-1]:
                continue
            self.ts.append(ts)
            self.frames.append(frames)

    def __call__(self, ts):
        if not self.ts:
            return ts * 60
        i = bisect_right(self.ts, ts)
        if i == 0:
            return self.frames[0] - (self.ts[0] - ts) * 60
        if i == len(self.ts):
            return self.frames[-1] + (ts - self.ts[-1]) * 60
        (t0, f0), (t1, f1) = (self.ts[i - 1], self.frames[i - 1]), (self.ts[i], self.frames[i])
        return f0 + (f1 - f0) * (ts - t0) / (t1 - t0) if t1 > t0 else f1


def axis_for(adventure, start, end):
    """The statistics history's active frames where they cover the window, else the cartridge's play time."""
    times = [entry.ts for entry in adventure.events if start <= entry.ts <= end]
    stats = adventure.stats
    if len(stats) >= 2 and times and sum(stats[0][0] <= t <= stats[-1][0] for t in times) >= 0.8 * len(times):
        return Axis(stats, 'statistics')
    cap = 999 if adventure.gen2 else 255
    clock = []
    for entry in adventure.events:
        match = PLAYTIME.match(entry.playtime or '')
        if match and int(match[1]) < cap:
            clock.append((entry.ts, (int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3])) * 60))
    if len(clock) >= 2:
        return Axis(clock, 'playtime')
    if len(stats) >= 2:
        return Axis(stats, 'statistics')
    return Axis([], 'wall')


def received_key(entry):
    """The species key of a Pokémon that joined, as LoopGuard spells it, or '' when the title names none."""
    if entry.type == 'trade':
        try:
            name = ((json.loads(entry.body or '{}') or {}).get('received') or {}).get('name')
        except ValueError:
            name = None
        return species_key(name) if name else ''
    match = (HATCHED if entry.type == 'hatch' else _RECEIVED).match(entry.title)
    return species_key(match.group(1)) if match else ''


def released_key(entry):
    match = _RELEASED.match(entry.title)
    return species_key(match.group(1)) if match else ''


def constant(name):
    """A map's journal name as its map constant: "Lance's Room" is LANCES_ROOM."""
    return re.sub('[^A-Z0-9]+', '_', (name or '').upper().replace("'", '')).strip('_')


class Readiness:
    """The band a level gain is judged by (planning/readiness.band), rebuilt from the journal.

    The badges and Hall of Fame entries come from the journal, a loss from a blackout in a boss's room
    and the party's best level from the gains seen so far. The tracker also stands in for the
    supervisor's losses, so a loss raises the next boss's target once, as it does live."""

    def __init__(self, gen2):
        # The tables read the game data as they load, so --help works on a machine without it.
        self.badges = self.hall_of_fame = self.top = 0
        self.lost, self.best = set(), {}
        if gen2:
            from pokesim.gen2.readiness import BOSS_TABLE
            from pokesim.planning.league import gain_band
            self.hook = lambda snapshot, key, species: gain_band(BOSS_TABLE, snapshot, losses=self)
            self.room = constant
            self.bits = {name: 1 << bit for bit, name in enumerate(JOHTO_BADGES + KANTO_BADGES)}
        else:
            from pokesim.policies.progression import BOSS_TABLE, gain_band
            from pokesim.strategy_data import MAPS
            self.hook = lambda snapshot, key, species: gain_band(snapshot, key, species, losses=self)
            self.room = lambda name: MAPS.get(constant(name))
            self.bits = {name: 1 << bit for bit, name in enumerate(KANTO_BADGES)}
        self.table = BOSS_TABLE

    def levels(self):
        """The bosses lost to, as losses.Losses.levels keys them."""
        return self.lost

    def entry(self, entry):
        if entry.type == 'badge' and (match := BADGE.search(entry.title)):
            self.badges |= self.bits.get(match[1].lower(), 0)
        elif entry.type == 'champion':
            self.hall_of_fame += 1
        elif entry.type == 'blackout' and (row := self.table.room(self.room(entry.map))) is not None:
            self.lost.add(row.key)

    def snapshot(self):
        return SimpleNamespace(badges=self.badges, hall_of_fame_count=self.hall_of_fame,
                               party=(SimpleNamespace(level=self.top, egg=False),))

    def gain(self, who, level, key=None, species=None):
        """``improve`` when ``who`` reaches a new best ``level`` inside the band, else ``level``, as
        progress_events.gained classes it. ``key`` is the running goal and ``species`` a Pokédex number."""
        self.top = max(self.top, level)
        best = self.best.get(who)
        if best is not None and level <= best:
            return 'level'
        self.best[who] = level
        levels = self.hook(self.snapshot(), key, species)
        return 'improve' if levels is not None and levels[0] <= level <= levels[1] else 'level'


def rebuild(adventure, axis):
    """The progress_events rows the new writers would have written, from the journal, receipts and progress table.

    Catches come from the receipts and receives, releases and the STORY kinds from the journal. A new
    owned entry is a dex row, and a new level 100, perfect or shiny Pokémon is an improve row. A
    finished marathon gets one checkpoint row per checkpoint, spread evenly over the race. A level gain
    is an improve row when its Pokémon reaches a new best level inside the band (Readiness).
    """
    rows = []

    def add(ts, kind, key='', net=None):
        rows.append(Row(ts, axis(ts), kind, int(NET[kind] if net is None else net), key))
    obtained = {entry.id for entry in adventure.events if entry.type == 'obtain'}
    items, trainers, race = set(), set(), None
    tracker = Readiness(adventure.gen2)
    for entry in adventure.events:
        tracker.entry(entry)
        kind = JOURNAL.get(entry.type)
        if kind == 'receive':
            add(entry.ts, kind, received_key(entry))
        elif kind == 'release':
            add(entry.ts, kind, released_key(entry))
        elif entry.type == 'badge':
            add(entry.ts, 'badge')
        elif entry.type == 'champion':
            add(entry.ts, 'league')
        elif entry.type == 'map':
            add(entry.ts, 'area')
        elif entry.type == 'item':
            # Only the first of an item is needed. A repeat is a purchase or a pickup of a spare.
            add(entry.ts, 'item', net=entry.title not in items)
            items.add(entry.title)
        elif entry.type == 'trainer' and entry.title not in trainers:
            # A story trainer's first defeat sets its event flag. A rematch sets nothing.
            trainers.add(entry.title)
            add(entry.ts, 'event')
        elif entry.type == 'level' and (match := GREW.match(entry.title)):
            add(entry.ts, tracker.gain(match[1], int(match[2])))
        elif entry.type in ('level', 'plan'):
            add(entry.ts, entry.type)
        elif entry.type == 'marathon' and (match := MARATHON.match(entry.title)):
            if match[2] == 'is on!':
                race = (entry.ts, COURSES[match[1]])
            elif match[2] == 'finished!' and race:
                begun, points = race
                for point in range(1, points + 1):
                    add(begun + (entry.ts - begun) * point / points, 'checkpoint')
                race = None
            else:
                race = None
    for ts, fingerprint, dex in adventure.receipts:
        if fingerprint.startswith('gift-event:'):
            ref = fingerprint.split(':', 1)[1]
            if not ref.isdigit() or int(ref) not in obtained:
                add(ts, 'receive', f'dex:{dex}')
        else:
            add(ts, 'catch', f'dex:{dex}')
    best = None
    for ts, _badges, owned, _league, level100, perfect in adventure.progress:
        values = (owned or 0, level100 or 0, perfect or 0)
        if best is None:
            best = values
            continue
        for _ in range(values[0] - best[0]):
            add(ts, 'dex')
        for _ in range(max(0, values[1] - best[1]) + max(0, values[2] - best[2])):
            add(ts, 'improve')
        best = tuple(max(a, b) for a, b in zip(values, best))
    for ts, _dex in adventure.shiny:
        add(ts, 'improve')
    rows.sort(key=lambda row: row.ts)
    return rows


def stored_rows(adventure, axis):
    """The progress_events rows the writers stored, in place of the rebuilt ones.

    On a statistics axis each row keeps its own PlayClock frame, the clock that axis reads. A row with
    no frame, or any row on another axis, is placed at its wall time. Receive and release rows key the
    loop check by dex number. A row a reload undid (rewound) counts no net progress."""
    own = axis.name == 'statistics'
    rows = [Row(ts, float(frame if own and frame is not None else axis(ts)), kind, 0 if rewound else int(net or 0),
                f'dex:{species}' if species is not None and kind in ('receive', 'release') else '')
            for ts, frame, kind, species, net, rewound, *_ in adventure.stored]
    rows.sort(key=lambda row: row.ts)
    return rows


def reclassified(adventure, axis):
    """The stored rows with each level gain classed again by today's band (planning/readiness.band).

    A gain row keeps its goal, species, identity and level, and becomes ``improve`` when the Pokémon
    reaches a new best level inside the band, else ``level``. The band reads the badges, Hall of Fame
    entries and losses from the journal up to the row, and the best level any gain row reached."""
    tracker, entries, at, rows = Readiness(adventure.gen2), adventure.events, 0, []
    for ts, frame, kind, species, net, rewound, goal, identity, level in sorted(adventure.stored, key=lambda r: r[0]):
        while at < len(entries) and entries[at].ts <= ts:
            tracker.entry(entries[at])
            at += 1
        if kind in ('level', 'improve') and level is not None:
            kind = tracker.gain((species, identity), int(level), goal, species)
            net = NET[kind]
        rows.append((ts, frame, kind, species, net, rewound, goal, identity, level))
    return stored_rows(replace(adventure, stored=rows), axis)


def ground_truth(adventure, axis, labels=()):
    """True stalls from the stall alerts and bundles, reload reports, give-ups and labels, merged into episodes."""
    items, used = [], set()
    for entry in adventure.events:
        if entry.type != 'stall':
            continue
        if match := GAME_HOURS.match(entry.title):
            real = REAL_MINUTES.search(entry.body or '')
            game, wall = int(match[1]) * 60, int(real[1]) if real else config.STALL_ALERT_REAL_MINUTES
            bundle = next((b for b in adventure.bundles if abs(b[0] - entry.ts) <= 120 and b[1] is not None), None)
            if bundle:
                used.add(bundle)
                game, wall = bundle[1], bundle[2] or wall
            items.append(Episode(entry.ts - wall * 60, axis(entry.ts) - game * FRAMES_PER_GAME_MINUTE, entry.ts,
                                 axis(entry.ts), ['bundle' if bundle else 'stall alert']))
        elif entry.title == RELOADED or GAVE_UP.match(entry.title):
            # Two reloads each follow a stuck spell of STUCK_RELOAD_SECONDS.
            begun = entry.ts - 2 * config.STUCK_RELOAD_SECONDS
            items.append(Episode(begun, axis(begun), entry.ts, axis(entry.ts),
                                 ['reload report' if entry.title == RELOADED else 'give-up']))
    for bundle in adventure.bundles:
        if bundle not in used and bundle[1] is not None:
            items.append(Episode(bundle[0] - (bundle[2] or 0) * 60, axis(bundle[0]) - bundle[1] * FRAMES_PER_GAME_MINUTE,
                                 bundle[0], axis(bundle[0]), ['bundle']))
    cleared = []
    for label in labels:
        if label.get('adventure') != adventure.id:
            continue
        begun, ended = float(label['start']), float(label.get('end', label['start']))
        if label.get('stall', True):
            items.append(Episode(begun, axis(begun), ended, axis(ended), ['label']))
        else:
            cleared.append((begun, ended))
    return [episode for episode in merge(items)
            if not any(begun <= episode.end_ts and episode.start_ts <= ended for begun, ended in cleared)]


def merge(items):
    """Join reports of the same stall, such as the repeat alert six hours on."""
    episodes = []
    for item in sorted(items, key=lambda e: e.start_frame):
        last = episodes[-1] if episodes else None
        if last and item.start_frame <= last.end_frame + HOUR:
            last.start_ts, last.start_frame = min(last.start_ts, item.start_ts), min(last.start_frame, item.start_frame)
            if item.end_frame > last.end_frame:
                last.end_ts, last.end_frame = item.end_ts, item.end_frame
            last.sources = sorted(set(last.sources) | set(item.sources))
        else:
            episodes.append(Episode(item.start_ts, item.start_frame, item.end_ts, item.end_frame, list(item.sources)))
    return episodes


def segments(adventure, gap=GAP):
    """Stretches when the worker ran, from the journal, receipts and statistics buckets."""
    times = sorted([e.ts for e in adventure.events] + [r[0] for r in adventure.receipts] + [s[0] for s in adventure.stats])
    found = []
    for ts in times:
        if found and ts - found[-1][1] <= gap:
            found[-1][1] = ts
        else:
            found.append([ts, ts])
    return [tuple(pair) for pair in found]


class Journal:
    """An in-memory journal that LoopGuard reads as it would the store, filled as the replay goes."""
    KINDS = frozenset((*REAL_PROGRESS, 'release', 'obtain'))

    def __init__(self):
        self.lock = threading.Lock()
        # The adventure schema itself, so LoopGuard reads the tables it reads in a worker.
        self.db = state.connect(':memory:', check_same_thread=False)

    def add(self, entry):
        if entry.type in self.KINDS:
            self.db.execute('INSERT INTO events (id, ts, type, title) VALUES (?, ?, ?, ?)',
                            (entry.id, entry.ts, entry.type, entry.title))

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    @contextmanager
    def reading(self):
        with self.lock:
            yield self.db


class Status:
    """What the worker's status would show the watchdog, kept across worker restarts."""

    def __init__(self):
        self.achievement = self.owned = self.badges = self.league = None
        self.areas, self.place, self.net = 0, None, 0
        # Receives and releases since the newest net row, for the new loop check.
        self.cycle = deque(maxlen=LOOP_EVENTS)
        self.catches = 0


def watchdog():
    return SimpleNamespace(progress={}, limits=Limits())


class OldChecks:
    """StallWatch, LoopGuard and the watchdog fingerprint as they decide on main, for one worker run."""

    def __init__(self, gen2, journal, status, clock):
        self.gen2, self.journal, self.status, self.clock = gen2, journal, status, clock
        self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                config.STALL_ALERT_REPEAT_HOURS)
        # The loop guard counts game frames, so ``clock`` holds the frame on the replay axis.
        self.guard = LoopGuard(lambda: clock[0])
        self.watch, self.loop, self.quiet = watchdog(), None, False

    def entry(self, entry, frame):
        if entry.type in NEW_HIGH:
            self.stall.progress(frame, entry.ts)

    def receipt(self, ts, frame):
        # Gen I also counts any rise in the Pokémon held, until GEN1_HELD_RISE goes.
        if not self.gen2 and GEN1_HELD_RISE:
            self.stall.progress(frame, ts)

    def owned(self, ts, frame):
        self.stall.progress(frame, ts)

    def tick(self, ts, frame):
        flags = []
        reason = self.guard.looping(self.journal)
        if reason and not self.loop:
            flags.append(Flag(ts, frame, 'loopguard'))
        self.loop = reason
        if self.stall.check(frame, ts) is not None:
            flags.append(Flag(ts, frame, 'stallwatch', self.stall.frame))
        s = self.status
        quiet = Watchdog._quiet(self.watch, 'replay', {
            'watch': {'owned': s.owned, 'badges': s.badges, 'hall_of_fame': s.league, 'map': s.place},
            'progress': {'last_achievement': {'id': s.achievement}}, 'league_rewards': {'wins': s.league},
            'areas_discovered': s.areas, 'play_clock': {'seconds': int(frame // 60)}}, ts)
        if quiet and not self.quiet:
            flags.append(Flag(ts, frame, 'watchdog', self.stall.frame))
        self.quiet = quiet
        return flags


def loss_key(map_name):
    """The boss a blackout on ``map_name`` lost to, as Supervisor.lost names it, or None: 'league' for
    any League room, 'red' at Mt. Silver and the gym's own name for a gym."""
    name = map_name or ''
    if LEAGUE_ROOM.match(name):
        return 'league'
    if name == RED_ROOM:
        return 'red'
    return name if name.endswith(' Gym') else None


class NewChecks:
    """The same three checks reading only net rows, and receive and release rows for the loop, plus
    the loss loop check (stalls.LossLoop) on the journal's blackouts in a boss's room."""

    def __init__(self, status, losses):
        self.status = status
        self.stall = StallWatch(config.STALL_ALERT_GAME_MINUTES, config.STALL_ALERT_REAL_MINUTES,
                                config.STALL_ALERT_REPEAT_HOURS)
        self.watch, self.loop, self.quiet = watchdog(), None, False
        # The loss loop's counts outlive a worker restart, as the supervisor keeps them in the store.
        self.losses, self.pending = losses, []

    def row(self, row):
        if row.net:
            self.stall.progress(row.frame, row.ts)

    def entry(self, entry, frame):
        if entry.type == 'blackout' and (boss := loss_key(entry.map)) and self.losses.note(boss, frame):
            self.pending.append(Flag(entry.ts, frame, 'lossloop'))

    def tick(self, ts, frame):
        flags, self.pending = self.pending, []
        received, released = Counter(), Counter()
        for kind, key in self.status.cycle:
            (received if kind == 'receive' else released)[key] += 1
        churn = max((min(count, received[key]) for key, count in released.items()), default=0)
        reason = churn >= LOOP_LIMIT
        if reason and not self.loop:
            flags.append(Flag(ts, frame, 'loopguard'))
        self.loop = reason
        if self.stall.check(frame, ts) is not None:
            flags.append(Flag(ts, frame, 'stallwatch', self.stall.frame))
        quiet = Watchdog._quiet(self.watch, 'replay', {'watch': {'map': self.status.place},
                                                       'progress': {'last_achievement': {'id': self.status.net}},
                                                       'play_clock': {'seconds': int(frame // 60)}}, ts)
        if quiet and not self.quiet:
            flags.append(Flag(ts, frame, 'watchdog', self.stall.frame))
        self.quiet = quiet
        return flags


def replay(adventure, axis, rows, start, end, churn_n=10):
    """Run both models over the same history. Returns the old flags, the new flags and the churn flags."""
    # The journal reads the game data as it loads, so --help works on a machine without game data.
    from pokesim.gen2.journal import NOT_PROGRESS
    stream = ([(e.ts, 0, 'entry', e) for e in adventure.events]
              + [(r[0], 1, 'receipt', r) for r in adventure.receipts]
              + [(p[0], 2, 'progress', p) for p in adventure.progress]
              + [(r.ts, 3, 'row', r) for r in rows])
    stream.sort(key=lambda item: (item[0], item[1]))
    journal, status, clock, losses = Journal(), Status(), [0.0], LossLoop()
    old_flags, new_flags, churn = [], [], []
    position, best_owned = 0, None
    old = new = None

    def consume(until):
        nonlocal position, best_owned
        while position < len(stream) and stream[position][0] <= until:
            ts, _, kind, item = stream[position]
            position += 1
            frame = axis(ts)
            clock[0] = frame
            if kind == 'entry':
                journal.add(item)
                if item.map:
                    status.place = item.map
                if item.type == 'map':
                    status.areas += 1
                if (item.type not in NOT_PROGRESS) if adventure.gen2 else (item.type in ACHIEVEMENTS):
                    status.achievement = item.id
                if old:
                    old.entry(item, frame)
                if new:
                    new.entry(item, frame)
            elif kind == 'receipt':
                if old:
                    old.receipt(ts, frame)
            elif kind == 'progress':
                _, badges, owned, league, *_ = item
                status.badges, status.owned, status.league = badges, owned, league
                if best_owned is not None and owned > best_owned and old:
                    old.owned(ts, frame)
                best_owned = owned if best_owned is None else max(best_owned, owned)
            else:
                if item.net:
                    status.net += 1
                    status.cycle.clear()
                    status.catches = 0
                elif item.kind in ('receive', 'release') and item.key:
                    status.cycle.append((item.kind, item.key))
                elif item.kind == 'catch':
                    status.catches += 1
                    if status.catches == churn_n and start <= ts <= end:
                        churn.append(Flag(ts, frame, 'churn'))
                if new:
                    new.row(item)

    for begun, ended in segments(adventure):
        if ended < start - WARMUP or begun > end:
            continue
        consume(begun - 1e-6)
        old = OldChecks(adventure.gen2, journal, status, clock)
        new = NewChecks(status, losses)
        t = max(begun, start - WARMUP)
        while t <= min(ended, end):
            consume(t)
            frame = axis(t)
            clock[0] = frame
            flags_old, flags_new = old.tick(t, frame), new.tick(t, frame)
            if start <= t <= end:
                old_flags += flags_old
                new_flags += flags_new
            t += TICK
        consume(ended)
        old = new = None
    return old_flags, new_flags, churn


def alarms(flags):
    """The alarms a reader would see, whichever check raised them.

    The quiet checks' flags in one quiet stretch, which share the frame of its last progress, make one
    alarm, so the repeat alert six hours on and the watchdog beside it do not count as more stalls.
    Any other flag joins the alarm before it when within a game hour of its end."""
    kept, stretches = [], {}
    for flag in sorted(flags, key=lambda f: f.frame):
        alarm = stretches.get(flag.since) if flag.since is not None else None
        if alarm is None and kept and flag.frame <= kept[-1].end + HOUR:
            alarm = kept[-1]
        if alarm is None:
            alarm = Alarm(flag, flag.frame if flag.since is None else min(flag.since, flag.frame), flag.frame)
            kept.append(alarm)
        alarm.end = max(alarm.end, flag.frame)
        if flag.since is not None:
            stretches[flag.since] = alarm
    return kept


def score(episodes, flags, start, end):
    """Caught, missed and false alarms for one model, with the time to detect each caught stall."""
    window = [e for e in episodes if start <= e.end_ts <= end]
    flags = [f for f in flags if start <= f.ts <= end]
    frames, minutes, caught = [], [], 0
    for episode in window:
        first = next((f for f in sorted(flags, key=lambda f: f.frame)
                      if episode.start_frame - HOUR <= f.frame <= episode.end_frame + HOUR), None)
        if first:
            caught += 1
            frames.append(max(0, first.frame - episode.start_frame))
            minutes.append(max(0.0, first.ts - episode.start_ts) / 60)
    raised = alarms(flags)
    false = [a for a in raised if not any(e.start_frame - HOUR <= a.end and a.start <= e.end_frame + HOUR for e in episodes)]
    return {'stalls': len(window), 'caught': caught, 'missed': len(window) - caught, 'false_alarms': len(false),
            'alarms': len(raised),
            'detect_frames': {'median': round(statistics.median(frames)) if frames else None,
                              'worst': round(max(frames)) if frames else None},
            'detect_minutes': {'median': round(statistics.median(minutes), 1) if minutes else None,
                               'worst': round(max(minutes), 1) if minutes else None},
            'false_alarm_times': [round(a.first.ts) for a in false]}


def model(episodes, flags, start, end):
    result = score(episodes, flags, start, end)
    result['checks'] = {check: {key: value for key, value in score(episodes, [f for f in flags if f.check == check],
                                                                    start, end).items() if key != 'false_alarm_times'}
                        for check in ('stallwatch', 'loopguard', 'watchdog', 'lossloop')}
    return result


def bar(result, days):
    """Why an adventure fails the bar to switch, or an empty list."""
    reasons, new, old = [], result['new'], result['old']
    if new['missed']:
        reasons.append(f"missed {new['missed']} of {new['stalls']} true stalls")
    allowed = days / 7
    if new['false_alarms'] > allowed:
        reasons.append(f"{new['false_alarms']} false alarms in {days} days, over {allowed:g}")
    ours, theirs = new['detect_frames']['median'], old['detect_frames']['median']
    if ours is not None and theirs is not None and ours > theirs:
        reasons.append(f'median time to detect {ours} frames, old {theirs}')
    return reasons


def fidelity(adventure, flags, start, end):
    """How the replayed StallWatch matches the alerts the live one wrote to the journal."""
    live = [e.ts for e in adventure.events if e.type == 'stall' and GAME_HOURS.match(e.title) and start <= e.ts <= end]
    replayed = [f.ts for f in flags if f.check == 'stallwatch']
    matched = sum(any(abs(ts - other) <= 3600 for other in replayed) for ts in live)
    return {'live_alerts': len(live), 'replayed_alerts': len(replayed), 'live_matched_within_an_hour': matched}


def restarts(stores):
    """Starts after the first per adventure from the app database next to the adventures, which keeps no dates."""
    path = Path(stores).parent / 'app.sqlite'
    if not path.exists():
        return None
    db = connect(path)
    try:
        counts = Counter()
        for (result,) in db.execute("SELECT result FROM operations WHERE kind IN ('start', 'restart')"):
            try:
                counts[json.loads(result).get('id')] += 1
            except (ValueError, AttributeError):
                continue
    except sqlite3.Error:
        return None
    finally:
        db.close()
    return {aid: count - 1 for aid, count in counts.items() if count > 1}


def run_input(stores, days, labels, churn_n, source=None):
    """One input folder's results. ``source`` picks the rows, stored or rebuilt. With None an adventure
    replays its stored rows when the window holds any, and rebuilds them otherwise."""
    stores = Path(stores)
    folders = sorted(p for p in stores.iterdir() if (p / 'pokesim.sqlite').exists())
    adventures = [load(folder) for folder in folders]
    newest = max((e.ts for a in adventures for e in a.events[-1:]), default=time.time())
    end, start = newest, newest - days * 86400
    owner = restarts(stores)
    results, bundles = [], 0
    for adventure in adventures:
        bundles += len(adventure.bundles)
        axis = axis_for(adventure, start, end)
        picked = source or ('stored' if any(start <= row[0] <= end for row in adventure.stored) else 'rebuilt')
        rows = {'stored': stored_rows, 'reclassified': reclassified, 'rebuilt': rebuild}[picked](adventure, axis)
        episodes = ground_truth(adventure, axis, labels)
        old_flags, new_flags, churn = replay(adventure, axis, rows, start, end, churn_n)
        window = [row for row in rows if start <= row.ts <= end]
        active = sum(min(b, end) - max(a, start) for a, b in segments(adventure) if b >= start and a <= end)
        result = {'adventure': adventure.id, 'version': adventure.version, 'axis': axis.name, 'rows_source': picked,
                  'active_hours': round(active / 3600, 1),
                  'entries': sum(start <= e.ts <= end for e in adventure.events),
                  'rows': dict(Counter(row.kind for row in window)), 'net_rows': sum(row.net for row in window),
                  'shadow_rows_in_store': adventure.shadow_rows, 'stall_bundles': len(adventure.bundles),
                  'stall_bundles_in_window': sum(start <= b[0] <= end for b in adventure.bundles),
                  'truth': [{'start': round(e.start_ts), 'end': round(e.end_ts),
                             'game_minutes': round((e.end_frame - e.start_frame) / FRAMES_PER_GAME_MINUTE),
                             'sources': e.sources} for e in episodes if start <= e.end_ts <= end],
                  'old': model(episodes, old_flags, start, end), 'new': model(episodes, new_flags, start, end),
                  'churn_flags': len(churn), 'fidelity': fidelity(adventure, old_flags, start, end)}
        result['bar'] = bar(result, days)
        results.append(result)
    notes = []
    if not bundles:
        notes.append('No stall bundles in this input.')
    if owner is None:
        notes.append('No app database beside the adventures, so owner restarts are unknown.')
    return {'path': str(stores), 'window': [round(start), round(end)], 'adventures': results, 'stall_bundles': bundles,
            'owner_restarts_undated': owner, 'notes': notes}


AMBIGUITIES = [
    'Rows: an adventure whose store holds progress_events rows in the window replays those stored rows unless '
    '--rows rebuilt, and its rows_source says which. The notes on improve, event, item and checkpoint describe the '
    'rebuild and do not apply to stored rows. On a statistics axis a stored row keeps its own PlayClock frame. A row '
    'with no frame, or any row on another axis, is placed at its wall time. A row a reload undid counts no net '
    'progress.',
    'Window: section 4 gives no window for the new stall rule, so it uses the StallWatch clocks, 120 game minutes '
    'and 15 real minutes with a repeat after 6 hours. The new watchdog keeps its 3600 real seconds and its map rule, '
    'with the newest net row as its fingerprint.',
    'Healthy rate: no input has encounter_counts, so the healthy-rate exception never applies and nothing is parked.',
    'improve: there is no worth oracle yet, so a new level 100, perfect or shiny Pokémon stands in for it.',
    'Level gains: a rebuilt or reclassified gain is improve when its Pokémon reaches a new best level inside today\'s '
    'band. The band reads the badges and Hall of Fame entries from the journal, and losses from blackouts in a '
    'boss\'s room only, since a battle that cannot end and a loss on the way to a goal leave no journal entry. The '
    'party\'s best level is the best any gain reached so far, so a Pokémon boxed or released still counts. Gold, '
    'Silver and Crystal read each boss\'s ace from its table row, and Yellow\'s gyms read Red\'s aces unless the '
    'Yellow variant is set. A rebuilt gain names its Pokémon by nickname and has no goal, so Red, Blue and Yellow\'s '
    'postgame evolve and rematch bands apply to reclassified rows only.',
    'Quiet stretches: the stall alerts and watchdog flags in one quiet stretch make one alarm, from the frame of the '
    'stretch\'s last progress to its last flag, and the alarm is false only when that span is more than a game hour '
    'from every true stall. Any other flag joins the alarm before it when within a game hour of its end.',
    'event: a story trainer\'s first defeat stands for an event flag. A rematch writes no row.',
    'item: only the first of each item title is a needed item.',
    'checkpoint: the journal keeps only a race\'s start and finish, so a finished race gets its checkpoints spread '
    'evenly between them and a race called off gets none.',
    'Catching a stall: a flag from one game hour before a stall starts to one game hour after it was reported '
    'catches it, with a time to detect of zero when early. An alert dates a stall by the old clocks, which a model '
    'that ignores catches can pass sooner. Any other alarm is false.',
    'True stalls: the alerts are the old StallWatch\'s own, so the old model catches them by construction where the '
    'replay is faithful. The reload reports, give-ups and labels are the independent sources.',
    'Old model limits: the replay cannot see experience between level-ups, boss attempts, save reloads or pauses, '
    'so the replayed StallWatch moves on fewer things than the live one and LoopGuard never counts reloads.',
]
MISSING = [
    'Help requests: the status builds them live and nothing stores them. Only Gen II reload reports reach the journal.',
    'Owner restarts: the hosted backup copy holds no app database, and the local one keeps undated operations only.',
    'Stall bundles past the newest five per adventure: KEEP_STALL_BUNDLES prunes them, so the journal alerts stand in.',
]


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run')
    run.add_argument('stores', nargs='+', type=Path)
    run.add_argument('--days', type=float, default=14)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--labels', type=Path)
    run.add_argument('--churn-n', type=int, default=10)
    run.add_argument('--rows', choices=('stored', 'reclassified', 'rebuilt'),
                     help='the rows to replay. By default an adventure replays its stored rows when the window holds '
                          'any, and rebuilds them from the journal otherwise. Reclassified rows are the stored ones '
                          'with each level gain classed again by today\'s band')
    show = commands.add_parser('report')
    show.add_argument('report', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'report':
        print(render(json.loads(args.report.read_text(encoding='utf-8'))))
        return 0
    labels = json.loads(args.labels.read_text(encoding='utf-8')).get('labels', []) if args.labels else []
    for stores in args.stores:
        if args.out.resolve().is_relative_to(stores.resolve()):
            parser.error('The report must go outside the input')
    began = time.time()
    report = {'tool': 'replay_progress', 'days': args.days, 'churn_n': args.churn_n, 'labels': len(labels),
              'rows': args.rows or 'stored when the window holds any',
              'constants': {'tick_seconds': TICK, 'gap_seconds': GAP, 'warmup_seconds': WARMUP, 'hour_frames': HOUR,
                            'stall_game_minutes': config.STALL_ALERT_GAME_MINUTES,
                            'stall_real_minutes': config.STALL_ALERT_REAL_MINUTES,
                            'watchdog_seconds': Limits().no_progress, 'loop_limit': LOOP_LIMIT},
              'inputs': [run_input(stores, args.days, labels, args.churn_n, args.rows) for stores in args.stores],
              'ambiguities': AMBIGUITIES, 'missing_sources': MISSING}
    failures = [{'input': item['path'], 'adventure': result['adventure'], 'reasons': result['bar']}
                for item in report['inputs'] for result in item['adventures'] if result['bar']]
    report['bar'] = {'pass': not failures, 'failures': failures}
    report['seconds'] = round(time.time() - began, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=asdict), encoding='utf-8')
    print(render(report))
    return 0


def render(report):
    lines = [f"Window {report['days']:g} days, churn N {report['churn_n']}, labels {report['labels']}"]

    def cell(side):
        frames, minutes = side['detect_frames'], side['detect_minutes']
        return (f"{side['caught']}/{side['stalls']} caught, {side['false_alarms']} false, "
                f"detect {frames['median']}/{frames['worst']} frames {minutes['median']}/{minutes['worst']} min")
    for item in report['inputs']:
        lines.append(f"\n{item['path']}  bundles {item['stall_bundles']}  {' '.join(item['notes'])}")
        for result in item['adventures']:
            lines.append(f"  {result['adventure'][:6]} {result['version']:<8} {result['active_hours']:>6}h "
                         f"{result.get('rows_source', 'rebuilt'):<7} net {result['net_rows']:<5} old: {cell(result['old'])} | new: {cell(result['new'])} "
                         f"| churn {result['churn_flags']} | {'; '.join(result['bar']) or 'pass'}")
    lines.append(f"\nBar: {'pass' if report['bar']['pass'] else 'fail'}")
    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main())
