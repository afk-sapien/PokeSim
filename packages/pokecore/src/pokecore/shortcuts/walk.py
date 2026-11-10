"""Walk up to N tiles in one direction, on all six games. One input per ``step``, no memory writes.

``Walk`` taps the direction once per tile and checks the player's map and
coordinates after each tap. A tap that only turns the player is followed by one
more tap. It stops early when the player does not move (a wall, a person, a
ledge from below), when a battle starts, when the map changes, or when text or
a menu opens. The caller picks the direction. There is no route finding.
"""
from __future__ import annotations

from dataclasses import replace

from ..gen1 import W_CUR_MAP, W_FACING, W_X, W_Y
from .dialogue import controls_locked
from .machine import Abort, Done, Shortcut, StopReason

DIRECTIONS = ('up', 'down', 'left', 'right')
# Facing values (direction >> 2) in Gen 1 sprite data and Gen 2 wPlayerDirection.
FACING = ('down', 'up', 'left', 'right')
W_PLAYER_FACING = W_FACING
MAX_TILES = 64
# Screens seen while the game is still moving the player or fading.
_MOVING = ('overworld', 'transition', 'unknown')
_SAID = {StopReason.BLOCKED: 'then could not move further', StopReason.BATTLE: 'then a battle started',
         StopReason.MAP_CHANGE: 'then the map changed', StopReason.DIALOGUE: 'then text or a menu opened',
         StopReason.STOPPED: 'then a game script kept the controls'}


class Walk(Shortcut):
    """Walk ``tiles`` tiles (1 to 64) toward ``direction`` ('up', 'down', 'left' or 'right').

    Starts on the overworld outside battle with no text or menu open. The result
    details hold ``direction``, ``requested``, ``tiles_moved``, ``start``, ``end``
    (each ``{'map', 'x', 'y'}``) and ``facing``. ``completed`` means the player
    moved at least ``tiles`` tiles. A ledge hop counts two tiles.
    """

    kind = 'walk'

    def __init__(self, direction, tiles=1, *, patience=4, **options):
        if direction not in DIRECTIONS:
            raise ValueError('direction must be one of up, down, left, right')
        if type(tiles) is not int or not 1 <= tiles <= MAX_TILES:
            raise ValueError(f'tiles must be an integer from 1 through {MAX_TILES}')
        if type(patience) is not int or not 1 <= patience <= 60:
            raise ValueError('patience must be an integer from 1 through 60')
        self.default_steps = 60 + 20 * tiles
        super().__init__(**options)
        self.direction, self.tiles, self.patience = direction, tiles, patience
        self.start = None
        self.moved = 0

    # Reads -------------------------------------------------------------------
    def position(self, obs=None):
        """(map, x, y). Gen 2 maps are (group, number)."""
        memory = (obs or self.obs).memory
        if self.gen == 2:
            return ((memory.byte('wMapGroup'), memory.byte('wMapNumber')), memory.byte('wXCoord'),
                    memory.byte('wYCoord'))
        return memory[W_CUR_MAP], memory[W_X], memory[W_Y]

    def facing(self, obs=None):
        memory = (obs or self.obs).memory
        value = memory.byte('wPlayerDirection') if self.gen == 2 else memory[W_PLAYER_FACING]
        return FACING[(value >> 2) & 3]

    @staticmethod
    def where(position):
        place, x, y = position
        return {'map': list(place) if isinstance(place, tuple) else place, 'x': x, 'y': y}

    def interruption(self, obs=None):
        obs = obs or self.obs
        if obs.battle:
            return StopReason.BATTLE
        if self.position(obs)[0] != self.start[0]:
            return StopReason.MAP_CHANGE
        if obs.screen not in _MOVING:
            return StopReason.DIALOGUE
        return None

    # Machine -----------------------------------------------------------------
    def result_fields(self):
        return {'direction': self.direction, 'requested': self.tiles, 'tiles_moved': self.moved}

    def _finish(self, done):
        return super()._finish(replace(done, details={**self.result_fields(), **done.details}))

    def validate(self, obs):
        if obs.battle:
            raise Abort('walk starts outside battle. No input sent.', cleanup=False)
        if obs.screen != 'overworld':
            raise Abort('walk starts on the overworld with no text or menu open. No input sent.', cleanup=False)
        if controls_locked(obs, self.gen):
            raise Abort('A game script has the controls. No input sent.', cleanup=False)
        self.start = self.position(obs)
        self.details['start'] = self.where(self.start)

    def flow(self):
        while self.moved < self.tiles:
            before, facing = self.position(), self.facing()
            yield self.direction
            reason = self.interruption()
            if reason is None and self.position() == before and self.facing() != facing:
                # That tap turned the player. The next one steps.
                yield self.direction
                reason = self.interruption()
            if reason is None and self.position() == before:
                reason = yield from self.watch(before)
            if reason is None and self.position() == before:
                # A tap that lands while the last step still animates is dropped. Try once more.
                yield self.direction
                reason = self.interruption()
                if reason is None and self.position() == before:
                    reason = yield from self.watch(before)
                if reason is None and self.position() == before:
                    reason = StopReason.BLOCKED
            self.count(before)
            if reason is None and controls_locked(self.obs, self.gen):
                # A trainer saw the player, or the step triggered a scripted event.
                reason = yield from self.watch(None, limit=60)
                if reason is None and controls_locked(self.obs, self.gen):
                    reason = StopReason.STOPPED
            if reason is not None:
                return (yield from self.end(reason))
        # An encounter or a warp on the last step shows a moment later.
        yield None
        return (yield from self.end(self.interruption() or StopReason.COMPLETED))

    def watch(self, before, limit=None):
        """Wait while nothing visible happens. Returns an interruption, or None once the player moves or rests."""
        for _ in range(limit or self.patience):
            yield None
            reason = self.interruption()
            if reason is not None:
                return reason
            if before is not None and self.position() != before:
                return None
            if before is None and not controls_locked(self.obs, self.gen):
                return None
        # A script that still runs may be about to print text or start a battle.
        for _ in range(60 if before is not None and controls_locked(self.obs, self.gen) else 0):
            yield None
            reason = self.interruption()
            if reason is not None or not controls_locked(self.obs, self.gen):
                return reason
        return None

    def count(self, before):
        after = self.position()
        if after[0] != before[0]:
            self.moved += 1
        else:
            self.moved += abs(after[1] - before[1]) + abs(after[2] - before[2])

    def end(self, reason):
        settled = True
        if reason == StopReason.BATTLE:
            # Let the battle transition finish, so the next command starts on a drawn screen.
            settled = yield from self.until(lambda obs: obs.screen not in ('transition', 'unknown'), limit=40,
                                            press_text=False)
        elif reason == StopReason.MAP_CHANGE:
            # Let the fade finish and the new map's entry script hand back the controls (or print its text).
            settled = yield from self.until(
                lambda obs: obs.screen not in ('transition', 'unknown')
                and (obs.screen != 'overworld' or not controls_locked(obs, self.gen)), limit=60, press_text=False)
        elif reason == StopReason.STOPPED:
            settled = False
        details = {**self.details, **self.result_fields(), 'end': self.where(self.position()),
                   'facing': self.facing()}
        if reason == StopReason.COMPLETED:
            outcome = f'Walked {self.moved} tile{"s" * (self.moved != 1)} {self.direction}.'
        else:
            outcome = f'Walked {self.moved} of {self.tiles} tiles {self.direction}, {_SAID[reason]}.'
        return Done(outcome, self.moved >= self.tiles, bool(settled), details, reason)
