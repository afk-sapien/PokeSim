"""After a postgame League wipe, the League waits until the team changed in a way that bears on the loss.

A Yellow team with Pikachu at Lv 44 and Pidgeotto at Lv 32 lost to Agatha's Gengar at Lv 60, blacked
out and walked straight back in, unchanged, until the next wipe. A short purse made the rematch
upkeep, the black out halved the purse, so it stayed short and the rematch kept its place above
everything else.

A wipe is a battle in a League room after the Champion was beaten where every member fainted.
``record`` keeps the room's bar, the highest foe level the team met there, the sweeper, which is the
foe out at the end, the team's depth toward the bar and how many members hit the sweeper. The League
opens again (``closed``) once the depth grew by DEPTH_REGROWTH, as Gold, Silver and Crystal ask
after a lost run, or once more members hit the sweeper. Depth counts each member's level up to the
bar, so a member under the bar adds the levels it trains, and one swapped for a stronger member adds
the difference. A team already at the bar everywhere is never held, since no level helps it. A win
clears the record (planning/losses.py keeps it).
"""
from types import SimpleNamespace

from ..planning.readiness import DEPTH_REGROWTH
from ..strategy_data import SPECIES
from .battle import damage


def depth(party, bar):
    """The team's levels toward ``bar``: each member's level, up to the bar."""
    return sum(min(mon.level, bar) for mon in party)


def hitters(party, sweeper):
    """How many members know a move that damages ``sweeper``, a species, as the battle scores it."""
    foe = SimpleNamespace(species=sweeper, types=tuple(SPECIES.get(sweeper, {}).get('types', ())),
                          level=1, hp=1, defense=1, special=1, speed=0, status=0)
    return sum(any(damage(move, mon, foe) > 0 for move in mon.moves if move) for mon in party)


def record(party, room, bar, sweeper):
    """The wipe in ``room`` by ``sweeper`` against ``party``, with ``bar`` the highest foe level met there."""
    return {'room': room, 'bar': bar, 'sweeper': sweeper, 'depth': depth(party, bar),
            'hitters': hitters(party, sweeper)}


def closed(wipe, party):
    """Whether the League waits after ``wipe``: the team neither grew toward its bar nor gained a hitter."""
    if not wipe or not party:
        return False
    bar = wipe['bar']
    if depth(party, bar) >= min(wipe['depth'] + DEPTH_REGROWTH, bar * len(party)):
        return False
    return hitters(party, wipe['sweeper']) <= wipe['hitters']
