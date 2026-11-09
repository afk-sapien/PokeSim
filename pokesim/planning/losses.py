"""What a lost boss battle asks of the next try, one rule for both generations.

A loss to a gym leader, an Elite Four member, the Champion or another boss goal raises the level the
team's best fighter trains to before that boss: REGROWTH over the best fighter level that lost, up
to CEILING over the boss's ace, the margin Red, Blue and Yellow train to before a gym. A loss is a
black out in the boss's room, a battle there that cannot end, or a stall reload during a battle
there. A boss is named by its trainer class too (BOSS_CLASSES), since the rival, Giovanni and the
Rocket executives fight on ordinary maps: a loss to one counts against the goal under way, capped
over the foe's level. The levels live in the adventure's store, so the reload that follows does not
take them back.

A fighter is a party Pokémon that is no egg and knows a damaging move. Only fighters count toward a
readiness bar or gate. A Gold run took a Lv 12 Chikorita and five Pokémon at Lv 3 to 5 back to
Falkner for hours: each loss ended on a Metapod that knows only Harden, the battle could not end,
and the reload went straight back in.
"""
from __future__ import annotations

KEY = 'boss_losses'
ACES = 'boss_aces'
REGROWTH = 2
CEILING = 10

# The trainer classes that block the story until beaten, by generation: every rival battle, the gym
# leaders, the Elite Four, the Champion, Red, and the story's villains.
BOSS_CLASSES = {
    1: frozenset({25, 42, 43,                         # the rival
                  34, 35, 36, 37, 38, 39, 40,         # Brock to Blaine
                  29,                                 # Giovanni, at the Rocket Hideout, Silph Co. and his gym
                  33, 44, 46, 47}),                   # Bruno, Lorelei, Agatha, Lance
    2: frozenset({9, 42,                              # the rival
                  1, 2, 3, 4, 5, 6, 7, 8,             # Falkner to Clair
                  17, 18, 19, 21, 26, 35, 46, 64,     # Brock, Misty, Lt. Surge, Erika, Janine, Sabrina, Blaine, Blue
                  11, 13, 14, 15, 16, 63,             # Will, Bruno, Karen, Koga, Lance, Red
                  51, 55}),                           # the Rocket executives
}


def boss_trainer(snapshot, generation):
    """The trainer class of the boss ``snapshot`` is battling, or None outside a boss battle."""
    if getattr(snapshot, 'in_battle', 0) != 2:
        return None
    trainer = getattr(snapshot, 'trainer_class', None)
    return trainer if trainer in BOSS_CLASSES[generation] else None


def fighter(mon, power):
    """Whether a party Pokémon fights: no egg, and ``power(move)`` is nonzero for one of its moves."""
    return not getattr(mon, 'egg', False) and any(power(move) for move in getattr(mon, 'moves', ()) if move)


def best_level(party, power):
    """The best fighter's level, or 0 when no Pokémon in ``party`` can deal damage."""
    return max((mon.level for mon in party if fighter(mon, power)), default=0)


def ace_slot(party, power):
    """The party slot of the best fighter, the first at the top level, or None when none can deal damage.

    Both generations teach a field move to another member when one can learn it. A Gen II League ace
    once carried Cut and Strength in two of its four slots into the Elite Four."""
    return max((i for i, mon in enumerate(party) if fighter(mon, power)), key=lambda i: (getattr(party[i], 'level', 0), -i), default=None)


class Losses:
    """The best fighter level that lost to each boss, by goal key, kept in ``store`` when one is given."""

    def __init__(self, store=None):
        self.store = store
        self.memory = {}

    def _read(self, name):
        if self.store is None:
            return dict(self.memory.get(name) or {})
        return dict(self.store.get(name) or {})

    def _write(self, name, values):
        if self.store is None:
            self.memory[name] = values
        else:
            self.store.set(name, values)

    def levels(self):
        return self._read(KEY)

    def aces(self):
        """The best foe level seen in a loss to each boss with no ace of its own in a table."""
        return self._read(ACES)

    def note(self, key, level, ace=None):
        aces = self.aces()
        if ace is not None and ace > aces.get(key, -1):
            aces[key] = ace
            self._write(ACES, aces)
        levels = self.levels()
        if level <= levels.get(key, -1):
            return
        levels[key] = level
        self._write(KEY, levels)

    def bar(self, key, floor, ace=None):
        """The level the best fighter trains to before ``key``: ``floor`` until a loss there.

        ``ace`` defaults to the best foe level a loss there noted."""
        lost = self.levels().get(key)
        if lost is None:
            return floor
        ace = self.aces().get(key, lost) if ace is None else ace
        return min(ace + CEILING, max(floor, lost + REGROWTH))
