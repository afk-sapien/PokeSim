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
"""
from __future__ import annotations

from dataclasses import dataclass

KEY = 'supervisor-ladder-v1'
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

    def _save(self):
        if self.store is not None:
            self.store.set(KEY, {'reloads': self.reloads, 'exhausted': self.exhausted, 'league': list(self.league)})
