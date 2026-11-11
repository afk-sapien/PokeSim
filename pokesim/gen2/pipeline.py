"""The Gen II overworld decision on the decide pipeline, in shadow (docs/design/decide-pipeline.md).

Each site in ``policy.py`` that sets the goal records its offer on the step's ``Ballot`` under its site
name, and ``offer`` turns that into a pipeline ``Offer`` with the site's source, needs and rule. The needs
table is read off today's chain: a goal needs every enabler whose site comes later, since a later enabler
replaced it there. The most urgent need is the one the latest site serves.

Slice 4a only records. The chain still sets the goal, and at the end of the step the shadow weighs the
ballot's decision against it. No offer carries a commit, so recording writes nothing. A change to this
table changes what slice 4b switches on, so it goes to the lead first.
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


def offer(site, goal, candidate=None, kind=None):
    """The pipeline offer of ``goal`` at ``site``. Without ``candidate`` it offers a short active goal of
    kind ``kind``, or of its source. An unknown site offers as the legacy chain."""
    source = SOURCES.get(site, 'legacy')
    if candidate is None:
        candidate = Candidate(goal.key, Tier.PROGRESS, values.SMALL, ERRAND_FRAMES, goal=kind or source)
    return Offer(source, goal, candidate, needs=NEEDS.get(site, ()), serves=SERVES.get(site, ''),
                 hold=site in HOLDS, forced=site in FORCED)


class Ballot:
    """The offers of one Gen II overworld decision, in the order the step recorded them.

    Each site records its goal with ``offer``. ``park`` marks an offer the walk found no route to, and
    ``resume`` offers the errand an earlier decision picked again as it was picked. ``decision`` is
    ``decide.decide`` over the offers so far.
    """

    def __init__(self):
        self.offers = []
        self._decision = None

    @property
    def decision(self):
        if self._decision is None:
            self._decision = decide.decide(self.offers)
        return self._decision

    def _add(self, offered):
        self.offers.append(offered)
        self._decision = None
        return offered

    def offer(self, goal, site, candidate=None, kind=None):
        """Record ``goal`` as offered from ``site`` and return its offer."""
        return self._add(offer(site, goal, candidate, kind))

    def park(self, goal, reason=decide.NO_ROUTE):
        """Park the latest offer of ``goal``, which cannot run now for ``reason``."""
        key = getattr(goal, 'key', None)
        offered = next((offered for offered in reversed(self.offers) if offered.key == key), None)
        if offered is not None:
            self._add(replace(offered, parked=reason))

    def resume(self, picked):
        """Offer ``picked``, the errand an earlier decision picked, again as it was picked. An enabler meets
        the same need, a forced move is forced again, and a goal is under way."""
        return self._add(replace(picked, hold=True, parked=''))
