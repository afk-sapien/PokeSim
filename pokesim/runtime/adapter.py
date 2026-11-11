"""What one generation gives the shared runtime: its settings and the few things only its cartridge knows.

The loop, the load, the reload and the save are the same for Red, Blue, Yellow, Gold, Silver and Crystal.
Each generation gives a ``GameAdapter`` (``pokesim/adapter.py`` for Gen I, ``pokesim/gen2/adapter.py`` for
Gen II) with the settings below and the cartridge's own steps: how it boots, how it reads a snapshot, what a
load restores and what a manifest carries. This module loads no game code, so a Gen II process never
reads Gen I game data, and the reverse.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol

from .game_loop import GEN1_WAIT, GEN2_WAIT


@dataclass(frozen=True)
class Settings:
    """The differences between the generations that have a reason on record (docs/design/one-bot.md)."""
    generation: int
    # The frames after a policy press whose action names no gap. Every Gen II trace and gate plays 16.
    wait: int
    # Gen I writes the options byte before every decision. Gen II writes it once after a load, since a
    # write before every decision would set every step of a trace apart from every trace before it.
    options_each_decision: bool
    # Only the Gen II cartridge has a real-time clock, which follows game time.
    clock: bool
    # A second stall before new progress reloads after a park in Gen II (#547).
    reload_after_park: bool
    # The game frames between the checks for work beside play, Gen II's rewards and Celebi, or None.
    background_frames: int | None


GEN1 = Settings(generation=1, wait=GEN1_WAIT, options_each_decision=True, clock=False, reload_after_park=False,
                background_frames=None)
GEN2 = Settings(generation=2, wait=GEN2_WAIT, options_each_decision=False, clock=True, reload_after_park=True,
                background_frames=300)


class GameAdapter(Protocol):
    """One generation's part of a run. ``run`` is the host: a headless run or the application's emulator."""

    generation: int
    settings: Settings

    def boot(self, run, rom, trace=None, fair_wild_dvs=None):
        """Start the cartridge on ``run.pb``, with the tracer and the hooks the generation plays with."""

    def new_policy(self, run, seed):
        """The policy a new run of this cartridge plays with."""

    def start_fresh(self, run):
        """Start a new game with no checkpoint."""

    def read(self, run):
        """The snapshot of the game as it is now."""

    def options(self, pb):
        """Write the text speed and battle animation byte."""

    def check(self, metadata):
        """Raise ValueError for a checkpoint another cartridge wrote."""

    def before_load(self, run, first):
        """What the run keeps from before a load."""

    def after_load(self, run, metadata, first):
        """What a load restores beyond the save state and the policy. ``first`` is the load a run starts
        from, and a reload after it is not."""

    def manifest_fields(self, run):
        """The fields this generation's checkpoint manifest adds."""

    def before_save(self, pb):
        """Get the emulator ready for its save state to be taken."""

    def after_step(self, run, snapshot):
        """The guard a headless run keeps after each step."""

    def waiting(self, run, snapshot):
        """Whether the run waits on purpose, which the stall watch does not count."""


def generation(raw):
    """The generation of a cartridge from its bytes. A file no shelf slot names plays as Gen I, as the Gen I
    runner always took any cartridge."""
    from ..cartridges import identify
    cartridge = identify(raw)
    return cartridge.generation if cartridge is not None else 1


def adapter_for(raw, data_root=None):
    """The adapter for the cartridge ``raw``, importing only that generation's code."""
    sha1 = hashlib.sha1(raw).hexdigest()
    if generation(raw) == 2:
        from ..gen2.adapter import Gen2Adapter
        return Gen2Adapter(raw, sha1, data_root)
    from ..adapter import Gen1Adapter
    return Gen1Adapter(raw, sha1)
