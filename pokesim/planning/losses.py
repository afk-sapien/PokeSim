"""What a lost boss battle asks of the next try, one rule for both generations.

A loss to a gym leader, an Elite Four member, the Champion or another boss goal raises the level the
team's best fighter trains to before that boss: REGROWTH over the best fighter level that lost, up
to CEILING over the boss's ace, the margin Red, Blue and Yellow train to before a gym. A loss is a
black out in the boss's room, or a battle there that cannot end. The levels live in the adventure's
store, so the reload that follows a battle that cannot end does not take them back.

A fighter is a party Pokémon that is no egg and knows a damaging move. Only fighters count toward a
readiness bar or gate. A Gold run took a Lv 12 Chikorita and five Pokémon at Lv 3 to 5 back to
Falkner for hours: each loss ended on a Metapod that knows only Harden, the battle could not end,
and the reload went straight back in.
"""
from __future__ import annotations

KEY = 'boss_losses'
REGROWTH = 2
CEILING = 10


def fighter(mon, power):
    """Whether a party Pokémon fights: no egg, and ``power(move)`` is nonzero for one of its moves."""
    return not getattr(mon, 'egg', False) and any(power(move) for move in getattr(mon, 'moves', ()) if move)


def best_level(party, power):
    """The best fighter's level, or 0 when no Pokémon in ``party`` can deal damage."""
    return max((mon.level for mon in party if fighter(mon, power)), default=0)


class Losses:
    """The best fighter level that lost to each boss, by goal key, kept in ``store`` when one is given."""

    def __init__(self, store=None):
        self.store = store
        self.memory = {}

    def levels(self):
        if self.store is None:
            return dict(self.memory)
        return dict(self.store.get(KEY) or {})

    def note(self, key, level):
        levels = self.levels()
        if level <= levels.get(key, -1):
            return
        levels[key] = level
        if self.store is None:
            self.memory = levels
        else:
            self.store.set(KEY, levels)

    def bar(self, key, floor, ace):
        """The level the best fighter trains to before ``key``: ``floor`` until a loss there."""
        lost = self.levels().get(key)
        if lost is None:
            return floor
        return min(ace + CEILING, max(floor, lost + REGROWTH))
