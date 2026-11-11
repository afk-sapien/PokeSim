"""Errands as task objects, for both generations (docs/design/one-bot.md, section 5).

An errand breaks off the goal under way for a short trip that serves it: a heal, a shop visit, or the
social detour of Red, Blue and Yellow. Each errand offers its goal to the step's decision, with the
writes that run only when the decision picks it (rule A). The walk takes it to its site, where it acts,
and it is done when it offers nothing. It keeps its own state and saves the part a reload must keep.

``Trip`` holds the errand a decision picked, its goal and the offer it was picked under, until the next
errand decision ends it. A step that does not reach that decision offers it again as it was picked, so
every menu, talk and team step on the way runs under the errand and not the goal behind it.
"""
from __future__ import annotations


class Errand:
    """A short trip that serves the goal under way.

    ``offer`` gives the errand's goal now and the commit that writes its state when the decision picks
    it, ``(None, None)`` once it is done. ``act`` gives the press at its site, or None when the site's
    usual arrival serves. ``state_dict`` and ``load_state_dict`` save and load what a reload keeps,
    and ``reset`` forgets what it does not.
    """
    key = ''

    def offer(self, policy, snapshot):
        return None, None

    def act(self, policy, snapshot):
        return None

    def state_dict(self):
        return {}

    def load_state_dict(self, state):
        pass

    def reset(self):
        pass


class Trip:
    """The errand under way: the ``goal`` an errand decision picked and the ``offer`` it was picked
    under, or None for both."""

    def __init__(self):
        self.goal = self.offer = None

    def start(self, goal, offer):
        self.goal, self.offer = goal, offer

    def end(self):
        self.goal = self.offer = None

    def resume(self, ballot):
        """The goal the trip runs under on ``ballot``, a step's decision that did not reach the errand
        decision. Its offer runs again as it was picked, so it still serves the same need. With no
        ballot, the trip's goal runs alone."""
        return self.goal if ballot is None else ballot.resume(self.offer)
