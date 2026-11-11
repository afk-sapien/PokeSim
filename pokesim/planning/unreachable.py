"""Walk targets that had no route, so the goal picker leaves them for a while.

A walk that finds no route ends its turn and records a failed attempt here, with the goal, the map it
aimed at and its target tiles. Nothing reloads and the stuck watchdogs see nothing, since a reload
replays the same missing route after a full stall timeout. The attempt stands its goal down in the
shared progress monitor (monitor.py), one key per goal and target, so the wait doubles while the same
target keeps failing and the picker passes it over until the wait runs out.

Each caller passes ``now`` in PlayClock frames, as the monitor does.
"""
from .monitor import Backoff, Monitor

# Name of the table of failed attempts inside the monitor's state.
ATTEMPTS = 'no_route'
# A target with no route waits a game minute, doubled for each failure in a row and four times at most.
# A short first wait lets a route that a person or a failed step only closed for a moment come back soon.
FRAMES = Backoff(3600, doublings=4)
# Attempts remembered, oldest dropped first.
REMEMBERED = 32


def key(goal, place, targets):
    """The monitor key of ``goal`` walking to ``targets`` on ``place``. One target names its tile."""
    if len(targets) == 1:
        return f'route:{goal}:{place}:{targets[0][-2]},{targets[0][-1]}'
    return f'route:{goal}:{place}'


class NoRoute:
    def __init__(self, state, backoff):
        self.monitor = Monitor(state, backoff)

    def record(self, goal, place, targets, now, origin=None):
        """Record a failed walk of ``goal`` to ``targets`` on ``place`` and return when it may be tried again.

        ``origin`` is the map the walk stood on when it found no route.
        """
        name = key(goal, place, targets)
        until = self.monitor.stand_down(name, now)
        rows = self.monitor.rows(ATTEMPTS)
        rows.pop(name, None)
        rows[name] = {'goal': goal, 'map': place, 'targets': [list(target) for target in targets[:8]],
                      'origin': origin, 'at': now, 'until': until}
        for old in list(rows)[:-REMEMBERED]:
            del rows[old]
            self.monitor.clear(old)
        return until

    def waiting(self, goal, place, targets, now):
        """Whether ``goal`` walking to ``targets`` on ``place`` failed and its wait has not run out."""
        return bool(targets) and self.monitor.standing_down(key(goal, place, targets), now)

    def attempts(self):
        """The failed attempts remembered, oldest first."""
        return list(self.monitor.rows(ATTEMPTS).values())
