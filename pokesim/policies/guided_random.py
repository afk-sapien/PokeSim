"""Weighted-random button presses with a few RAM-aware guardrails so the game keeps moving."""
from __future__ import annotations

import random

from .base import Action, Policy, PolicyContext
from .naming import NamingController
from ..screen import Screen

DIRS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


class GuidedRandomPolicy(Policy):
    name = "guided_random"

    def __init__(self, seed=None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.naming = NamingController(seed)
        self.last_dir = "down"
        self.mode = "boot"

    def describe(self) -> str:
        return f"guided_random ({self.mode})"

    def state_dict(self):
        return {"naming": self.naming.state_dict()}

    def load_state_dict(self, data):
        self.naming.load_state_dict(data.get("naming", {}))

    def reset(self):
        self.__init__(self.seed)

    def _walk(self, ctx: PolicyContext) -> list[Action]:
        r = self.rng
        s = ctx.snapshot
        if ctx.stuck_seconds > 60:
            # try harder to leave: long holds in fresh directions, close whatever might be open
            self.mode = "unstick"
            d = r.choice([d for d in DIRS if d != self.last_dir])
            self.last_dir = d
            return [Action("b", 4, 2), Action(d, r.randint(24, 60), 2)]
        self.mode = "overworld"
        x = r.random()
        if x < 0.62:
            if r.random() < 0.7:
                d = self.last_dir
            else:
                d = r.choice([d for d in DIRS if d != OPPOSITE[self.last_dir]] or DIRS)
            self.last_dir = d
            return [Action(d, r.randint(6, 24), 1)]
        if x < 0.90:
            return [Action("a", 6, 4)]
        if x < 0.97:
            return [Action("b", 4, 2)]
        return [Action("start", 6, 6)]

    def step(self, ctx: PolicyContext) -> list[Action]:
        r = self.rng
        s = ctx.snapshot
        if ctx.mem is not None:
            naming_action = self.naming.step(Screen(ctx.mem), s)
            if naming_action is not None:
                self.mode = "naming"
                return [naming_action]
        if not s.player_name:
            self.mode = "intro"
            # Advance the title and intro dialogue.
            x = r.random()
            if x < 0.75:
                return [Action("a", 6, 6)]
            if x < 0.85:
                return [Action("start", 6, 6)]
            return [Action(r.choice(DIRS), 6, 4)]
        if s.in_battle:
            self.mode = "battle"
            x = r.random()
            if s.textbox and x < 0.85:
                return [Action("a", 6, 6)]
            if x < 0.70:
                return [Action("a", 6, 6)]                 # FIGHT -> first move, advance text
            if x < 0.80:
                return [Action(r.choice(DIRS), 6, 4), Action("a", 6, 6)]   # pick another move / menu item
            if s.in_battle == 1 and x < 0.92:
                return [Action("down", 6, 4), Action("a", 6, 8), Action("a", 6, 8)]   # ITEM -> first item (usually a ball)
            if x < 0.97:
                return [Action("b", 6, 4)]
            return [Action("a", 6, 6)]
        if s.textbox:
            self.mode = "text"
            return [Action("a" if r.random() < 0.85 else "b", 6, 6)]
        if s.start_menu:
            self.mode = "menu"
            x = r.random()
            if x < 0.75:
                return [Action("b", 6, 4)]
            if x < 0.9:
                return [Action(r.choice(("up", "down")), 6, 4)]
            return [Action("a", 6, 6)]
        return self._walk(ctx)
