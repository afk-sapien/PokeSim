"""Each ball thrown in a wild battle restarts the hung-battle clock, in every generation.

The application reloads a battle that runs past BATTLE_TIMEOUT_SECONDS, and a scenario replay does
the same with its own timeout. A static legendary can take longer than that while the battle still
moves: Lugia's catch rate of 3 lets about one Ultra Ball in eighty land on an awake Lugia, and a Silver
run reloaded the battle with balls still in the bag. So a ball thrown counts as the battle going
somewhere, as a new opponent does in a Gold, Silver or Crystal trainer battle.

A battle cannot add balls to the bag, and the count only restarts the clock when it falls below the
fewest seen in this battle, so the clock restarts at most once for each ball carried in. A battle
that throws no ball keeps the timeout it always had. A throw moves only the clock the timeout counts,
not the battle's start, which the reload goes back before and the autosave hold counts from. So a
reload still lands before the battle and not on a save taken part way through it.
"""
from __future__ import annotations


def gen1_balls(snapshot):
    """The balls a Red, Blue or Yellow policy throws, in the bag. A Master Ball ends the battle it is
    thrown in, and the Safari Zone keeps its own count outside the bag. Gold, Silver and Crystal count
    theirs with gen2.ledger.balls."""
    from ..policies.battle import BALLS
    return sum(count for item, count in snapshot.items if item in BALLS)


class ThrowClock:
    """The frame of the latest ball thrown in the current wild battle. One for each emulator or replay."""

    fewest = frame = None

    def look(self, snapshot, frame, count):
        """Note the balls ``count(snapshot)`` finds at ``frame`` and return the frame of the latest
        throw in this wild battle, or None. Outside a wild battle the count starts over. A snapshot
        that does not read as a running game changes nothing."""
        if not getattr(snapshot, 'valid', True):
            return self.frame
        if snapshot.in_battle != 1 or not getattr(snapshot, 'started', True):
            self.fewest = self.frame = None
            return None
        balls = count(snapshot)
        if self.fewest is not None and balls < self.fewest:
            self.frame = frame
        self.fewest = balls if self.fewest is None else min(self.fewest, balls)
        return self.frame

    def since(self, start):
        """The frame the timeout counts from: the battle's ``start`` or its latest throw, whichever is later."""
        return start if start is None or self.frame is None else max(start, self.frame)


def note_throws(emulator, snapshot, count):
    """Count an emulator's balls in this snapshot. Its ``throws`` clock starts on the first look and
    again after a reload, which sets it to None as it rewinds the frames."""
    throws = getattr(emulator, 'throws', None)
    if throws is None:
        throws = emulator.throws = ThrowClock()
    throws.look(snapshot, emulator.frame, count)


def timed_from(emulator):
    """The frame an emulator's hung-battle timeout counts from: its ``battle_frame``, or the latest ball
    thrown in that battle."""
    throws = getattr(emulator, 'throws', None)
    return emulator.battle_frame if throws is None else throws.since(emulator.battle_frame)
