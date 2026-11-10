"""Read how long ago an adventure last made real progress, from its own progress table and journal.

A stand-in until the goal system checks its own liveness. The watchdog asks once every few minutes
and raises a "stalled" problem once a game goes too long without real progress for its stage.

Story progress is a badge, a new area, a new Pokédex entry or a League win. A game in the story
stalls after twice the slowest gap the original Red, Blue, Yellow, Gold, Silver and Crystal games
took in the same stage, and never in under three hours. Postgame progress is a League win, any
Pokédex change (seen, owned, level 100 species and perfect finds) or a level up, which is how a
trainee shows its training. A postgame game stalls after a day without one. Experience alone,
repeat catches and other journal entries never count.

`python -m pokesim.app.progress_sweep <data root>` prints the same reading for every adventure of
a library, as for local sims run outside the hosted app.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import sys
import time

from ..state import schema

FLOOR = 3 * 3600
POSTGAME = 24 * 3600
# Seconds, by (generation, badges, League won at least once). The slowest gap between two progress
# moments in that stage in the original games' progress tables and journals, 2026-11-09.
SLOWEST = {
    (1, 0, False): 271, (1, 1, False): 319, (1, 2, False): 913, (1, 3, False): 460, (1, 4, False): 486,
    (1, 5, False): 420, (1, 6, False): 2081, (1, 7, False): 148, (1, 8, False): 15684,
    (2, 0, False): 27, (2, 1, False): 37, (2, 2, False): 37, (2, 3, False): 88, (2, 4, False): 67,
    (2, 5, False): 399, (2, 6, False): 141, (2, 7, False): 1334, (2, 8, False): 465,
    (2, 8, True): 56, (2, 9, True): 16, (2, 10, True): 17, (2, 11, True): 87, (2, 12, True): 61,
    (2, 13, True): 26, (2, 14, True): 35, (2, 15, True): 30,
}
GEN2 = ('gold', 'silver', 'crystal')
# Enough rows to cover a day of postgame Pokédex changes in the busiest original game.
ROWS = 5000
# Two stall entries at one place within an hour mean the game's own recovery is not working there,
# as when Gold reloaded twice at Violet Gym 34 minutes apart and the three hour floor stayed quiet.
REPEATS = 2
REPEAT_WINDOW = 3600
# Full boxes block every catch, so a day without one is a hunt that cannot finish.
CATCH_QUIET = 24 * 3600


@dataclass(frozen=True)
class Reading:
    last: float      # when the game last made real progress
    limit: float     # seconds without progress before it counts as stalled
    postgame: bool
    badges: int
    stalls: tuple = ()     # (time, place) of the newest stall entries, newest first
    caught: float = 0      # when the game last caught a Pokémon


def repeated(stalls, now):
    """(place, first time, count) when REPEATS stall entries at one place fall in the last REPEAT_WINDOW."""
    recent = {}
    for ts, place in stalls:
        if now - ts <= REPEAT_WINDOW:
            recent.setdefault(place, []).append(ts)
    found = [(place, min(times), len(times)) for place, times in recent.items() if len(times) >= REPEATS]
    return max(found, key=lambda row: row[2], default=None)


def generation(version):
    return 2 if version in GEN2 else 1


def limit(gen, badges, league):
    if league and (gen == 1 or badges >= 16):
        return POSTGAME
    return max(FLOOR, 2 * SLOWEST.get((gen, badges, bool(league)), 0))


def _changed(rows, columns):
    """The time of the newest row whose columns differ from the row before it, or of the oldest row."""
    for newer, older in zip(rows, rows[1:]):
        if any(newer[i] != older[i] for i in columns):
            return newer[0]
    return rows[-1][0]


def read(path, gen):
    """The reading for one adventure's pokesim.sqlite, or None before its first progress row."""
    path = Path(path)
    if not path.is_file():
        return None
    with closing(schema.connect(path, read_only=True, timeout=0.5)) as db:
        rows = db.execute('SELECT ts, badges, owned, seen, league, level100, perfect FROM progress '
                          'ORDER BY rowid DESC LIMIT ?', (ROWS,)).fetchall()
        if not rows:
            return None
        badges, league = rows[0][1], rows[0][4]
        seconds = limit(gen, badges, league)
        postgame = seconds == POSTGAME
        # Columns: 1 badges, 2 owned, 3 seen, 4 league, 5 level 100 species, 6 perfect finds.
        last = _changed(rows, (2, 3, 4, 5, 6) if postgame else (1, 2, 4))
        kind = 'level' if postgame else 'map'
        event = db.execute('SELECT ts FROM events WHERE type=? ORDER BY id DESC LIMIT 1', (kind,)).fetchone()
        stalls = db.execute("SELECT ts, map FROM events WHERE type='stall' ORDER BY id DESC LIMIT 10").fetchall()
        caught = db.execute("SELECT MAX(ts) FROM events WHERE type='catch'").fetchone()[0]
    return Reading(max(last, event[0] if event else 0), seconds, postgame, badges,
                   tuple((ts, place or 'the same place') for ts, place in stalls), caught or 0)


def library(root, now=None):
    """One line per adventure under a library data root, for a check outside the app.

    It reads files only, so unlike the watchdog it counts time a game was stopped or paused."""
    now = time.time() if now is None else now
    lines = []
    for folder in sorted((Path(root) / 'adventures').iterdir()):
        try:
            adventure = json.loads((folder / 'adventure.json').read_text(encoding='utf-8'))
            reading = read(folder / 'pokesim.sqlite', generation(adventure.get('version')))
        except (OSError, ValueError, sqlite3.Error) as error:
            lines.append(f'{folder.name} unreadable: {error}')
            continue
        if reading is None:
            lines.append(f'{folder.name} {adventure.get("name")}: no progress yet')
            continue
        quiet = now - reading.last
        state = 'STALLED' if quiet > reading.limit else 'ok'
        lines.append(f'{folder.name} {adventure.get("name")}: {state}, {quiet / 3600:.1f} h without progress, '
                     f'limit {reading.limit / 3600:.1f} h, {reading.badges} badges'
                     + (', postgame' if reading.postgame else ''))
    return lines


if __name__ == '__main__':
    print('\n'.join(library(sys.argv[1])))
