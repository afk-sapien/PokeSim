"""The one game loop step that the application, headless runs and the tools all play.

A step asks the policy for its next actions, presses each one and runs what is due after it: the
autosave every ``AUTOSAVE_SECONDS`` of game time and the guards every ``GUARD_FRAMES``. What a host
keeps for itself is setup, commands, pause, manual input, pacing and frame publishing, all through
the ``tick`` it passes in. So a test and the application play the same frames.

The decider is the only part that differs by generation. Red, Blue and Yellow ask with a
``PolicyContext``. Gold, Silver and Crystal ask with the snapshot, the memory and the stack pointer.
This module loads no Gen I code until a Gen I decider is built, so a Gen II worker never reads Gen I
game data.
"""
from __future__ import annotations

from .. import config
from .reload import FRAMES_PER_SECOND, Cadence

# The guards look at the run once a second of game time, in both generations.
GUARD_FRAMES = 60
# The action a Gen I policy that has nothing to do waits with.
IDLE_FRAMES = 12


def play(pb, action, tick):
    """Press, hold, release and wait out one action. ``tick`` advances the emulator and the host's
    frame count. The button comes up even when a tick fails, so a crash never leaves it held."""
    if action.button:
        pb.button_press(action.button)
    try:
        tick(action.hold)
    finally:
        if action.button:
            pb.button_release(action.button)
    tick(action.gap)


def gen1_options(value):
    """The Gen I options byte with fast text and, when the setting asks, no battle animations."""
    if config.FAST_TEXT:
        value = (value & ~7) | 1
    if not config.BATTLE_ANIMATIONS:
        value |= 128
    return value


class Gen1:
    """Asks a Red, Blue or Yellow policy. ``clock`` gives the PlayClock frames the policy reads."""

    def __init__(self, clock):
        from ..policies.base import Action, PolicyContext, stack_pointer
        from ..screen import W_OPTIONS
        self.clock = clock
        self._idle = Action(None, 0, IDLE_FRAMES)
        self._context, self._stack_pointer, self._options = PolicyContext, stack_pointer, W_OPTIONS

    def options(self, pb):
        # Written before every decision, so a menu press that slowed the text never lasts a decision.
        pb.memory[self._options] = gen1_options(pb.memory[self._options])

    def ask(self, policy, snapshot, pb):
        context = self._context(snapshot, self.clock(), pb.memory, self._stack_pointer(pb))
        return list(policy.step(context)) or [self._idle]


class Gen2:
    """Asks a Gold, Silver or Crystal policy for its one next action."""

    def options(self, pb):
        # Gen II sets its options once after each load. A write before every decision would add a
        # memory write to every step of a trace and set it apart from every trace before it.
        pass

    def ask(self, policy, snapshot, pb):
        from ..gen2.menus import stack_pointer
        return [policy.step(snapshot, pb.memory, stack_pointer(pb))]


class GameLoop:
    """One host's decisions and the actions they leave to play.

    ``host`` has ``pb``, ``policy`` and ``frame``. ``guards`` runs every ``GUARD_FRAMES`` and keeps
    its next frame in ``host.guard_frame``, which a host may reset. ``autosave`` runs on the game
    time cadence when ``ready`` allows it. A reload moves the frame back and both start again from
    there.
    """

    def __init__(self, host, decider, tick, guards=None, autosave=None, ready=None):
        self.host, self.decider, self.tick = host, decider, tick
        self.guards, self.autosave, self.ready = guards, autosave, ready
        self.pending = []
        self.cadence = Cadence(config.AUTOSAVE_SECONDS * FRAMES_PER_SECOND, host.frame)

    def decide(self, snapshot, policy=None):
        """Ask ``policy``, the host's own by default, for the next actions and queue them."""
        pb = self.host.pb
        self.decider.options(pb)
        policy = policy or self.host.policy
        self.pending = self.decider.ask(policy, snapshot, pb)
        tracer = getattr(self.host, 'tracer', None)
        if tracer is not None:
            # After the policy chose, so the record names the goal behind the inputs that follow.
            tracer.decide(policy, snapshot)
        return self.pending

    def act(self):
        """Play the next queued action, then autosave and run the guards when they are due."""
        action = self.pending.pop(0)
        play(self.host.pb, action, self.tick)
        frame = self.host.frame
        if self.autosave and (self.ready is None or self.ready()) and self.cadence.due(frame):
            self.autosave()
        if self.guards:
            due = getattr(self.host, 'guard_frame', 0)
            if frame >= due or frame < due - GUARD_FRAMES:
                self.host.guard_frame = frame + GUARD_FRAMES
                self.guards()
        return action

    def step(self, snapshot):
        """One decision and every action it asked for, as a headless run plays it."""
        self.decide(snapshot)
        while self.pending:
            self.act()
