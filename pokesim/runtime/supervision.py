"""One supervisor for both generations: the ladder a stuck run climbs, and where it stops.

Goal system v2, section 6 of docs/design/goal-system.md. Each generation still loads its own saves.
The supervisor picks the rung and keeps its counts in the adventure store under ``KEY``, so a worker
restart does not start the ladder again. An owner restart empties them with the old game's state.

The rungs, in order:

1. Reload a save from before the trouble. The third reload in a row without new progress reports
   the run as stalled.
2. Inside the League, from the second reload on, or at once for a battle that cannot end, restart
   the attempt from the League entry save. A save part way through keeps the PP already spent, so
   going back a little replays the same lost battle. The third restart without a new Hall of Fame
   entry calls the League run off.
3. After twelve reloads, give up on the goal every reload left stuck. When there is nothing to give
   up, or the loop guard sees the run repeating itself, stop reloading and stay flagged as stalled
   until the run makes progress again.

Progress is one rule in both generations: a new high, kept under ``BEST_KEY``. A reload rewinds the
game, and the replay journals the same maps, trainers and levels again, which is not progress. A boss
attempt holds the ladder until it ends, and a blackout or a reload out of it is a loss whose progress
does not count.

The status page's help request and progress line are written here too, once for both generations.
So are the policy's own waits, each a named ``Budget`` on the PlayClock, and the progress monitor's
stand-downs and spent frames, kept in ``Tables`` under ``MONITOR_KEY`` so that a reload keeps them.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from ..pcvalue import BOXES_FULL
from ..planning.monitor import STOOD_DOWN

KEY = 'supervisor-ladder-v1'
BEST_KEY = 'supervisor-best-v1'
MONITOR_KEY = 'supervisor-monitor-v1'
# Pokémon whose own bests are kept. A gift and release loop brings a new one each time.
KEEP_MONS = 64
# Reloads in a row without new progress before the run is reported as stalled.
STALL_RELOADS = 3
# The reload from which a run stuck inside the League restarts the attempt from its entry save.
LEAGUE_RELOADS = 2
# League attempts restarted from the entry save without a new Hall of Fame entry before the run is
# called off. Experience gained before each loss counts as progress, so the reload streak never caps it.
LEAGUE_RESTARTS = 3
# Reloads in a row without new progress after which reloading stops, since it only replays the same trouble.
MAX_RELOADS = 12
# The guards' reason for a battle that neither side can finish. Waiting longer cannot help it.
CANNOT_END = 'battle cannot end'
# The help request of a run that has stopped making game progress.
STOPPED = 'The policy has stopped making game progress'
# The policy's mode once it drops its way to a goal and looks for another.
ANOTHER_APPROACH = 'finding another approach'
# Real seconds after a reload that the status page says the run is recovering.
RECOVERING_SECONDS = 30
# Real seconds after an achievement that the status page says the run is making progress.
FRESH_SECONDS = 120

GIVE_UP, HOLD, RELOAD = 'give up', 'hold', 'reload'


@dataclass(frozen=True)
class Budget:
    """A named wait the policy counts on the PlayClock, at 60 frames a second.

    The PlayClock never goes back, so a reload neither restarts a wait nor stretches it. A cap on
    tries stays a count, since a slow screen or a long walk would spend frames without another try.
    """
    name: str
    frames: int

    def until(self, now):
        """The PlayClock frame at which a wait begun at ``now`` ends."""
        return now + self.frames


# A Core shortcut the game refused waits about a minute of game time before another try.
REFUSED_SHORTCUT = Budget('refused shortcut', 3600)
# Gen I trains a promising partner at most once every five game minutes.
PARTNER_TRAINING = Budget('partner training', 18000)
# Gen I's chats and detours: a minute's rest after a detour, half a minute after a look around, and
# a quarter minute after a talk.
DETOUR_REST = Budget('detour rest', 3600)
LOOK_AROUND = Budget('look around', 1800)
CHAT_REST = Budget('chat rest', 900)


class Tables(dict):
    """The progress monitor's tables (planning/monitor.py), kept in the adventure store rather than a save.

    A reload rewinds the game but not the frames a goal really spent, so a goal that stood down keeps
    waiting and a spent budget stays spent. The stand-down times are PlayClock frames, which never go
    back. ``flush`` writes the tables to the store at each autosave, so a worker restart keeps them too,
    and an owner restart empties them with the old game. Without a store, as in a headless run, nothing is kept.

    ``clock`` gives the frames the policy counts on, and defaults to the store's PlayClock. A headless
    run has no store and counts its own frames.
    """

    def __init__(self, store=None, clock=None):
        saved = store.get(MONITOR_KEY) if store is not None else None
        super().__init__(deepcopy(saved) if isinstance(saved, dict) else {})
        self.store = store
        self.clock = clock

    def adopt(self, saved, then, factor=1, now=None):
        """Take the tables a save carried from before they moved here, when there are none yet.

        The save timed its stand-downs on its own clock, which stood at ``then`` and counts ``factor``
        frames per unit. Each keeps the wait it had left, counted from ``now``, which defaults to the
        clock's frame, or ``then`` without a clock. True when there were no tables, whether or not the
        save had any.
        """
        if any(self.values()):
            return False
        if now is None:
            # The emulator sets the store's clock after it attaches the tables, so it is read here.
            clock = self.clock if self.clock is not None else getattr(self.store, 'clock', None)
            now = clock() if callable(clock) else then
        self.clear()
        self.update({name: deepcopy(table) for name, table in (saved or {}).items()
                     if isinstance(table, dict) and table})
        stood = self.get(STOOD_DOWN)
        for key, when in (stood or {}).items():
            stood[key] = now - (then - when) * factor
        return True

    def flush(self):
        if self.store is not None:
            self.store.set(MONITOR_KEY, {name: dict(table) for name, table in self.items() if table})


@dataclass(frozen=True)
class Rung:
    """What a stuck run does next. ``reloads`` counts the reloads in a row without progress, this one included."""
    kind: str
    reloads: int
    # Restart the League attempt from its entry save rather than reload a recent save.
    league: bool = False
    # Tell the owner the run is stuck. Once in each streak.
    report: bool = False
    # The first hold of a streak, so the log says it once rather than at every guard check.
    first: bool = False


def report(why, place):
    """The title and body of the journal entry for a run that reloads for the third time in a row."""
    return ('Stuck? The adventure had to reload three times',
            f'{why.capitalize()} at {place} and {STALL_RELOADS - 1} reloads did not help.')


def mon_key(mon):
    """One key per Pokémon that a reload or a swap does not change: its trainer, DVs and species."""
    dvs = ','.join(str(dv) for dv in (getattr(mon, 'dvs', ()) or ()))
    return f"{getattr(mon, 'trainer_id', None)}/{dvs}/{getattr(mon, 'species', None)}"


def _trim(table, party):
    """Forget the oldest Pokémon past ``KEEP_MONS``, never one in the party."""
    extra = len(table) - KEEP_MONS
    if extra > 0:
        for key in [key for key in table if key not in party][:extra]:
            del table[key]


class Supervisor:
    """The reload ladder of one adventure, the same in Red, Blue and Yellow and in Gold, Silver and Crystal.

    ``store`` is the adventure store. Without one, as in a unit test, nothing is kept.
    """

    def __init__(self, store=None):
        self.store = store
        saved = (store.get(KEY) if store is not None else None) or {}
        self.reloads = int(saved.get('reloads', 0))
        self.exhausted = bool(saved.get('exhausted', False))
        # The most Hall of Fame entries seen, and the League restarts since the last new one.
        seen, restarts = saved.get('league', (0, 0))
        self.league = (int(seen), int(restarts))
        best = (store.get(BEST_KEY) if store is not None else None) or {}
        self.best = tuple(int(count) for count in best.get('score', ()))
        # Each Pokémon's most experience, and each egg's fewest cycles left, or -1 once it hatched.
        self.trained = {str(key): int(value) for key, value in (best.get('trained') or {}).items()}
        self.eggs = {str(key): int(value) for key, value in (best.get('eggs') or {}).items()}
        # The ladder's counts as a boss attempt under way began. Kept in memory only, like the clocks it holds with.
        self.held = None

    @property
    def stalled(self):
        """Whether the ladder flags the run as stalled: three reloads without progress, or reloading stopped."""
        return self.reloads >= STALL_RELOADS or self.exhausted

    def reset(self):
        """Start the ladder again from the bottom, after new progress or after giving up on a goal."""
        if self.reloads or self.exhausted:
            self.reloads, self.exhausted = 0, False
            self._save()

    def climb(self, why, give_up, *, looping=lambda: None, in_league=lambda: False):
        """The next rung for a run stuck because of ``why``.

        ``give_up`` stands down whatever every reload left stuck and says whether there was anything.
        ``looping`` gives the loop guard's reason, if any, and ``in_league`` whether the party is inside
        the League. Each is asked only when the rung depends on it, since a loop scan reads the journal.
        """
        if self.reloads >= MAX_RELOADS and give_up():
            reloads = self.reloads
            self.reset()
            return Rung(GIVE_UP, reloads)
        if self.reloads >= MAX_RELOADS or looping():
            first, self.exhausted = not self.exhausted, True
            if first:
                self._save()
            return Rung(HOLD, self.reloads, first=first)
        self.reloads += 1
        self._save()
        league = (self.reloads >= LEAGUE_RELOADS or why == CANNOT_END) and bool(in_league())
        return Rung(RELOAD, self.reloads, league=league, report=self.reloads == STALL_RELOADS)

    def restarted_league(self, wins):
        """Count a League attempt restarted from its entry save. True when it is time to call the League run off.

        A live Crystal run reloaded its League entry fourteen times in half an hour, as the same team
        met the same trouble at Koga each time. The entry save forgets every attempt, so the count
        lives here and starts again only with a new Hall of Fame entry. ``wins`` is the cartridge's count.
        """
        seen, count = self.league
        count = count + 1 if wins <= seen else 1
        call_off = count >= LEAGUE_RESTARTS
        self.league = (max(wins, seen), 0 if call_off else count)
        self._save()
        return call_off

    def progressed(self, snapshot, areas, wins):
        """Whether the run beat its own best, which starts the ladder again.

        Wandering to new tiles is not progress, so only a new high counts: badges, event flags, Pokédex
        entries, ``areas`` visited, party experience or ``wins`` in the League. A finished run with a
        full Pokédex and a level 100 team still wins the League. The party total drops when a trained
        Pokémon is swapped for a trainee, so each Pokémon also counts against its own best experience.
        A level 100 party walking eggs to hatching earns no experience, so each egg counts once per
        cycle below its fewest seen and once on hatching. A reload back to a fuller egg replays steps
        that already counted.
        """
        party = snapshot.party
        score = (snapshot.badges.bit_count(), sum(byte.bit_count() for byte in snapshot.event_flags),
                 len(snapshot.owned), areas, sum(getattr(mon, 'experience', 0) or 0 for mon in party), wins)
        best = self.best if len(self.best) == len(score) else (0,) * len(score)
        gained = any(new > old for new, old in zip(score, best))
        changed = gained or best is not self.best
        trained = False
        keys = set()
        for mon in party:
            key = mon_key(mon)
            keys.add(key)
            experience = getattr(mon, 'experience', 0) or 0
            most = self.trained.get(key)
            if most is None or experience > most:
                trained |= most is not None
                self.trained[key], changed = experience, True
            # A hatched egg stays on record below any cycle count, so its hatching counts only once.
            cycles = mon.friendship if getattr(mon, 'egg', False) else -1
            fewest = self.eggs.get(key)
            if fewest is None and cycles >= 0 or fewest is not None and cycles < fewest:
                trained |= fewest is not None
                self.eggs[key], changed = cycles, True
        if changed:
            self.best = tuple(max(new, old) for new, old in zip(score, best))
            _trim(self.trained, keys)
            _trim(self.eggs, keys)
            if self.store is not None:
                self.store.set(BEST_KEY, {'score': list(self.best), 'trained': self.trained, 'eggs': self.eggs})
        if gained or trained:
            self.reset()
        return gained or trained

    def watch_boss(self, boss, blackout, stall=None, guard=None):
        """Hold back the progress of a boss attempt until it ends, and drop it when the attempt is lost.

        A team too weak for the Elite Four lost to Lance for 12 hours, and each run earned experience,
        levels and trainer wins on the way, so the stall alert never fired. A loss to a boss is never
        progress. ``boss`` says an attempt is under way, ``blackout`` that the party just fainted. The
        stall watch and the loop guard hold their own clocks with the ladder's counts.
        """
        if blackout and self.held is not None:
            self.lost(stall, guard)
        elif boss and self.held is None:
            self.held = (self.reloads, self.exhausted)
            if stall is not None:
                stall.attempt()
            if guard is not None:
                guard.hold(self.store)
        elif not boss and self.held is not None:
            self.held = None
            if stall is not None:
                stall.settle()
            if guard is not None:
                guard.settle()

    def lost(self, stall=None, guard=None):
        """End a boss attempt as a loss, by a blackout or by a reload out of it.

        Its progress does not count, so the ladder, the stall clocks and the loop guard go back to where
        they stood as it began. At Chuck's gym in Crystal each reload left an attempt whose experience
        started the ladder again, and the run reloaded six times without a report.
        """
        if self.held is None:
            return
        reloads, exhausted = self.held
        self.held = None
        if reloads > self.reloads or exhausted and not self.exhausted:
            self.reloads, self.exhausted = max(reloads, self.reloads), exhausted or self.exhausted
            self._save()
        if stall is not None:
            stall.lost()
        if guard is not None:
            guard.lost(self.store)

    def stuck(self, stall, frames, *, held=False, waiting=False, loop=None):
        """Whether the status shows the run as stalled: looping, high on the ladder or quiet past the
        stall watch's limit in game time. Never while it is paused, in manual play or waiting.

        ``frames`` is the PlayClock. ``loop`` is the loop guard's last answer, which the status reads
        and never scans for, so the status page cannot move a scan to a frame a replay would not reach.
        """
        if held or waiting:
            return False
        return bool(loop) or self.stalled or bool(stall is not None and stall.stalled(frames))

    def help_request(self, stall, frames, *, held=False, waiting=False, loop=None, full=lambda: False, action=''):
        """Ask the owner for a hand, the same in all six games, or None.

        A loop asks first, then a stall. ``full`` says a missing entry is left uncaught for want of a
        slot, with nothing in the PC that may go. It reads the boxes, so it is asked only when the run
        is not stalled. ``action`` is what the policy is doing.
        """
        if held:
            return None
        if self.stuck(stall, frames, waiting=waiting, loop=loop):
            return {'reason': f'The run is caught in a loop. {loop}' if loop else STOPPED, 'action': action}
        if full():
            return {'reason': BOXES_FULL, 'action': action}
        return None

    def progress(self, stall, frames, now, *, achievement=None, held=False, waiting=False, loop=None,
                 glitched=False, last_reload=0.0, mode=''):
        """The status page's progress line, the same in all six games.

        ``achievement`` is the newest journal achievement, ``last_reload`` the real time of the last
        reload and ``mode`` what the policy is doing. ``quiet_game_minutes`` is the stall watch's.
        """
        age = max(0, int(now - achievement['ts'])) if achievement else None
        if self.stuck(stall, frames, held=held, waiting=waiting, loop=loop):
            state = 'stalled'
        elif waiting and not held:
            state = 'waiting'
        elif glitched or now - last_reload < RECOVERING_SECONDS or mode == ANOTHER_APPROACH:
            state = 'recovering'
        else:
            state = 'making_progress' if age is not None and age < FRESH_SECONDS else 'exploring'
        return {'state': state, 'quiet_game_minutes': stall.game_minutes(frames) if stall is not None else 0,
                'last_achievement': {'id': achievement['id'], 'title': achievement['title'], 'ts': achievement['ts'],
                                     'age_seconds': age} if achievement else None}

    def _save(self):
        if self.store is not None:
            self.store.set(KEY, {'reloads': self.reloads, 'exhausted': self.exhausted, 'league': list(self.league)})
