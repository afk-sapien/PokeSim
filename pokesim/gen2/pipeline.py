"""The Gen II overworld decision on the decide pipeline (docs/design/decide-pipeline.md).

Each site in ``policy.py`` offers its goal on the step's ``Ballot`` under its site name, and ``offer``
turns that into a pipeline ``Offer`` with the site's source, needs and rule. The needs table is read off
the old chain: a goal needs every enabler whose site comes later, since a later enabler replaced it there.
The most urgent need is the one the latest site serves. Every Gen II overworld goal is picked by
``decide.decide`` over these offers (slice 4b), so a change to this table changes behaviour and goes to
the lead first.
"""
from __future__ import annotations

from dataclasses import replace

from ..planning import decide, values
from ..planning.arbiter import Candidate, Tier
from ..planning.decide import Offer

# The frames of a short errand such as a Pokémon Center visit or a shop trip, as Gen I prices it.
ERRAND_FRAMES = 3000

# Every overworld site in the order the step reaches it: the site, its source and the need it serves.
SITES = (
    ('story', 'story', ''),              # The story goal, or the collection's goal once the story is done.
    ('holds', 'holds', ''),              # An activity under way that no rung cuts into (collection.holds).
    ('ladder', 'ladder', ''),            # The collection ladder's pick of its rungs.
    ('current', 'current', ''),          # The goal a battle that is starting keeps.
    ('boss', 'boss', 'trained'),         # Training for the next boss.
    ('release', 'party', 'room'),        # A release that makes room in storage.
    ('talk_heal', 'heal', 'healthy'),    # A heal that a talk on the way runs under.
    ('partner', 'party', 'field_move'),  # A partner that knows a field move the party lacks.
    ('delete_hm', 'moves', 'field_move'),  # Deleting an HM to make room for the one the party lacks.
    ('shop', 'supplies', 'supplies'),    # A restock errand.
    ('heal', 'heal', 'healthy'),         # A heal errand.
    ('sudowoodo', 'sudowoodo', ''),      # The returned tree that walls off Route 36.
)

# Sites whose goal is under way, and sites the game forces by map.
HOLDS = frozenset({'holds'})
FORCED = frozenset({'sudowoodo'})

NEEDS = decide.needs(SITES)
SOURCES = {site: source for site, source, _ in SITES}
SERVES = {site: serves for site, _, serves in SITES}


def offer(site, goal, candidate=None, kind=None, commit=None):
    """The pipeline offer of ``goal`` at ``site``, with the writes ``commit`` runs only when it is picked.
    Without ``candidate`` it offers a short active goal of kind ``kind``, or of its source. An unknown site
    offers as the legacy chain."""
    source = SOURCES.get(site, 'legacy')
    if candidate is None:
        candidate = Candidate(goal.key, Tier.PROGRESS, values.SMALL, ERRAND_FRAMES, goal=kind or source)
    return Offer(source, goal, candidate, needs=NEEDS.get(site, ()), serves=SERVES.get(site, ''),
                 hold=site in HOLDS, forced=site in FORCED, commit=commit)


class Ballot:
    """The offers of one Gen II overworld decision, which ``decide.decide`` picks from.

    Each site offers its goal with ``offer`` and gets back the goal that runs now, the decision over the
    offers so far. ``park`` takes out an offer that cannot run now, and ``resume`` offers the errand an
    earlier decision picked again as it was picked. An offer's ``commit`` holds its writes, and only the
    offer that runs writes (rule A).

    ``pinned`` is the key of the offer a manager pinned (planning/pin.py), which ranks after upkeep and
    before every other source's goals. The source that offers the pin says so.
    """

    def __init__(self):
        self.offers = []
        self.pinned = None
        self._decision = None
        self._committed = None

    @property
    def decision(self):
        if self._decision is None:
            self._decision = decide.decide(self.offers, self.pinned)
        return self._decision

    @property
    def running(self):
        """The offer that runs now, or None when nothing was offered."""
        return self.decision.pick

    @property
    def goal(self):
        running = self.running
        return None if running is None else running.goal

    def _add(self, offered):
        self.offers.append(offered)
        self._decision = None
        return self.goal

    def offer(self, goal, site, candidate=None, kind=None, commit=None, pinned=False):
        """Offer ``goal`` from ``site`` and return the goal that runs now. ``commit`` holds the writes that
        run only if this offer is the one that runs. ``pinned`` says the offer is the goal a manager
        pinned."""
        offered = offer(site, goal, candidate, kind, commit)
        if pinned:
            self.pinned = offered.candidate.key
        return self._add(offered)

    def park(self, goal, reason=decide.NO_ROUTE):
        """Park the latest offer of ``goal``, which cannot run now for ``reason``, and return the goal that
        runs now."""
        key = getattr(goal, 'key', None)
        offered = next((offered for offered in reversed(self.offers) if offered.key == key), None)
        if offered is None:
            return self.goal
        return self._add(replace(offered, parked=reason))

    def resume(self, picked):
        """Offer ``picked``, the errand an earlier decision picked, again as it was picked, and return the
        goal that runs now. An enabler meets the same need, a forced move is forced again, and a goal is
        under way. Its writes ran when it was picked, so it carries none."""
        return self._add(replace(picked, hold=True, parked=None, commit=None))

    def commit(self):
        """Run the writes of the offer that runs. Each offer's writes run once, so the step can commit
        before the goal's arrival reads them and again when it ends."""
        running = self.running
        commit = None if running is None else running.commit
        if commit is not None and commit is not self._committed:
            self._committed = commit
            commit()
