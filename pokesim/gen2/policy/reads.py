"""The battle and screen state one Generation II decision reads, through pokecore's state readers."""
from __future__ import annotations

from functools import cached_property

from pokecore.state import BattleMon, read_battle, read_battlers, read_ui

# A side whose battle structure is still empty, as the cartridge clears it before a Pokémon is sent out.
NO_MON = BattleMon(species=0, dex=None, nick='', level=0, hp=0, status=0, types=(0, 0), moves=(0, 0, 0, 0),
                   pp=(0, 0, 0, 0), stats=(0, 0, 0, 0, 0, 0), dvs=(0, 0, 0, 0, 0), held_item=0, transformed=False,
                   shown_dvs=bytes(2), disabled_move=None, last_move=0, holds_foe=False)


class Reads:
    """pokecore's battle and screen state of one decision's memory, each read once, when first asked.

    The policy reads the game only through these within a decision, and nothing in a decision
    writes memory, so one read stands for every use. ``player`` and ``enemy`` are the sides' battlers,
    or :data:`NO_MON` while a side's structure is empty.
    """

    def __init__(self, memory, game):
        self.memory, self.game = memory, game

    @cached_property
    def battle(self):
        return read_battle(self.memory, self.game)

    @cached_property
    def ui(self):
        return read_ui(self.memory, self.game)

    @property
    def player(self):
        return self.battle.player or NO_MON

    @property
    def enemy(self):
        return self.battle.enemy or NO_MON


class Battlers:
    """Both sides' battlers as the structures stand whatever the battle mode says, read when first asked.

    The emulator asks between presses, from live memory, where the battle mode may already be cleared
    while the structures still hold the battle.
    """

    def __init__(self, memory, game):
        self.memory, self.game = memory, game

    @cached_property
    def sides(self):
        return read_battlers(self.memory, self.game)

    @property
    def player(self):
        return self.sides[0] or NO_MON

    @property
    def enemy(self):
        return self.sides[1] or NO_MON
