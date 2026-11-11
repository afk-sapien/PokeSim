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
"""
from __future__ import annotations

from dataclasses import dataclass

KEY = 'supervisor-ladder-v1'
BEST_KEY = 'supervisor-best-v1'
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

GIVE_UP, HOLD, RELOAD = 'give up', 'hold', 'reload'


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

    def _save(self):
        if self.store is not None:
            self.store.set(KEY, {'reloads': self.reloads, 'exhausted': self.exhausted, 'league': list(self.league)})
