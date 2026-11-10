"""The states an adventure moves through, and the moves allowed between them.

Every change of an adventure's state goes through Registry.transition, which checks the move
against MOVES and logs one line with the reason. A move that is not listed is logged as an error
and still written for now, so a path nobody planned for shows up in the logs instead of hiding.
"""
from __future__ import annotations

STATES = ('stopped', 'starting', 'running', 'recovering', 'stopping', 'failed', 'deleting')

MOVES = {
    'stopped': {'starting', 'failed', 'deleting'},
    'starting': {'running', 'recovering', 'stopping', 'stopped', 'failed'},
    # After PokeSim ends without stopping its workers, the next boot starts a worker the
    # registry still records as running or stopping. A Start on a running adventure also
    # reads as starting until the supervisor sees the worker.
    'running': {'starting', 'stopping', 'stopped', 'failed'},
    'recovering': {'running', 'stopping', 'stopped', 'failed'},
    'stopping': {'starting', 'stopped', 'failed'},
    'failed': {'starting', 'stopping', 'stopped', 'deleting'},
    'deleting': set(),
}

# States that say a worker runs, so the supervisor should hold a child for them.
LIVE = frozenset({'running', 'recovering'})


def allowed(before, after):
    """Whether an adventure may go from `before` to `after`. Staying put is always allowed."""
    return before == after or after in MOVES.get(before, ())
