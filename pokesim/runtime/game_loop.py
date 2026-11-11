"""The one game loop step that the application, headless runs and the tools all play.

A step asks the policy for its next actions, presses each one and runs what is due after it: the
autosave every ``AUTOSAVE_SECONDS`` of game time and the guards every ``GUARD_FRAMES``. What a host
keeps for itself is setup, commands, pause, manual input, pacing and frame publishing, all through
the ``tick`` it passes in. So a test and the application play the same frames.

Both generations ask their policy the same way, with a ``PolicyContext`` (runtime/policy.py). What
differs is two settings of the ``Decider``: Red, Blue and Yellow write the options byte before every
decision, and Gold, Silver and Crystal wait 16 frames after a press where Gen I waits 2. This module
loads no game code, so a Gen II worker never reads Gen I game data.
"""
from __future__ import annotations

from .. import config
from .policy import Action, PolicyContext, stack_pointer
from .reload import FRAMES_PER_SECOND, Cadence

# The guards look at the run once a second of game time, in both generations.
GUARD_FRAMES = 60
# The action a policy that has nothing to do waits with.
IDLE_FRAMES = 12
# The frames each generation waits after a press whose action names no gap of its own.
GEN1_WAIT = 2
GEN2_WAIT = 16


def play(pb, action, tick, wait=GEN1_WAIT):
    """Press, hold, release and wait out one action. ``tick`` advances the emulator and the host's
    frame count, and ``wait`` is the gap of an action that names none. The button comes up even when a
    tick fails, so a crash never leaves it held."""
    if action.button:
        pb.button_press(action.button)
    try:
        tick(action.hold)
    finally:
        if action.button:
            pb.button_release(action.button)
    tick(wait if action.gap is None else action.gap)


def gen1_options(value):
    """The Gen I options byte with fast text and, when the setting asks, no battle animations."""
    if config.FAST_TEXT:
        value = (value & ~7) | 1
    if not config.BATTLE_ANIMATIONS:
        value |= 128
    return value


def write_gen1_options(pb):
    """Write the Gen I options byte. Red, Blue and Yellow write it before every decision, so a menu press
    that slowed the text never lasts a decision. Gen II sets its options once after each load, since a
    write before every decision would set every step of a trace apart from every trace before it."""
    from ..screen import W_OPTIONS
    pb.memory[W_OPTIONS] = gen1_options(pb.memory[W_OPTIONS])


class Decider:
    """Asks a policy of either generation for its next actions. ``clock`` gives the PlayClock frames the
    policy reads. ``options`` writes the options byte before every decision, or is None where the host
    writes it after a load. ``wait`` is the gap after a press of an action that names none."""

    def __init__(self, clock, options=None, wait=GEN1_WAIT):
        self.clock, self.options, self.wait = clock, options, wait

    def ask(self, policy, snapshot, pb):
        if self.options is not None:
            self.options(pb)
        context = PolicyContext(snapshot, self.clock(), pb.memory, stack_pointer(pb))
        return list(policy.step(context)) or [Action(None, 0, IDLE_FRAMES)]


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
        play(self.host.pb, action, self.tick, self.decider.wait)
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
