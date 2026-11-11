"""The Gen I overworld decision on the decide pipeline (docs/design/decide-pipeline.md).

Each site in ``strategic.py`` offers its goal on the step's ``Ballot`` under its site name, and
``offer`` turns that into a pipeline ``Offer`` with the site's source, needs and rule. The needs table
is read off the old chain: a goal needs every enabler whose site comes later, since a later enabler
overrode it there. The most urgent need is the one the latest site serves. Every Gen I overworld goal
is picked by ``decide.decide`` over these offers (slice 3), so a change to this table changes behaviour
and goes to the lead first.
"""
from __future__ import annotations

from ..planning import arbiter, decide, values
from ..planning.arbiter import Candidate
from ..planning.decide import Offer

# The frames of a short errand such as a Pokémon Center visit, a shop trip, a pickup or a passage that
# unblocks the goal behind it. An errand cutting into another one under way pays these frames again.
ERRAND_FRAMES = 3000
# Short goals that serve the goal behind them.
ERRANDS = frozenset(('heal', 'party', 'moves', 'supplies', 'pickup', 'passage', 'trash'))
# Goals that pick the party members they need, so no party upgrade cuts into them.
OWNS_PARTY = frozenset(('collection', 'catch', 'plan'))

# Every overworld site in the order the step offers it: the site, its source and the need it serves.
SITES = (
    ('base', 'story', ''),             # The story goal, the plan placeholder or the current goal.
    ('boss', 'boss', 'trained'),       # Training for the next boss.
    ('project', 'collection', ''),     # The collection project under way.
    ('pickup', 'pickup', ''),          # A ground item pickup under way.
    ('swap', 'party', 'reserve'),      # A reserve swap under way.
    ('errand', 'errand', ''),          # The errand the last overworld decision picked, on the steps after it.
    ('release', 'party', 'room'),      # A release that makes room in storage.
    ('box', 'party', 'room'),          # A box change that makes room for catches.
    ('heal_latch', 'heal', 'healthy'),  # The heal under way, set by the step.
    ('heal', 'heal', 'healthy'),       # The heal under way, set again by the overworld step.
    ('upgrade', 'party', 'team'),      # A stronger reserve in the box.
    ('supplies', 'supplies', 'supplies'),  # A restock the goal cannot go on without.
    ('teach', 'moves', ''),            # An owned HM.
    ('tm_trip', 'moves', ''),          # A TM trip under way.
    ('tm', 'moves', ''),               # An owned TM or supply item, or a TM to buy.
    ('trash', 'trash', 'lock'),        # The trash can locks in Vermilion Gym.
    ('collection', 'collection', ''),  # The collection's pick.
    ('pickup_new', 'pickup', ''),      # A new ground item pickup.
    ('passage', 'passage', ''),        # Leaving the League side of Victory Road.
    ('elevator', 'elevator', ''),      # Riding a lift.
    ('ceremony', 'ceremony', ''),      # The Hall of Fame after the Champion falls.
)

# Sites whose goal is under way, and sites the game forces by map.
HOLDS = frozenset({'pickup', 'errand', 'tm_trip'})
FORCED = frozenset({'passage', 'elevator', 'ceremony'})


def _needs(sites):
    table = {}
    for index, (site, _, _) in enumerate(sites):
        later = []
        for _, _, serves in reversed(sites[index + 1:]):
            if serves and serves not in later:
                later.append(serves)
        table[site] = tuple(later)
    return table


NEEDS = _needs(SITES)
SOURCES = {site: source for site, source, _ in SITES}
SERVES = {site: serves for site, _, serves in SITES}


def offer(site, goal, candidate, source=None, commit=None):
    """The pipeline offer of ``goal`` at ``site``, with the writes ``commit`` runs only when it is picked.
    An unknown site offers as the legacy chain."""
    return Offer(source or SOURCES.get(site, 'legacy'), goal, candidate, needs=NEEDS.get(site, ()),
                 serves=SERVES.get(site, ''), hold=site in HOLDS, forced=site in FORCED, commit=commit)


class Ballot:
    """The offers of one Gen I overworld decision, which ``decide.decide`` picks from.

    Each site offers its goal with ``offer``, and its row in ``SITES`` makes the offer a goal, an enabler,
    a goal under way or a forced move. ``goal`` and ``pick`` are what runs now, the decision over the
    offers so far, so a site reads the pick the sites before it left. An offer's ``commit`` holds its
    writes, and only the offer that runs when the step ends writes (rule A).

    An errand under way weighs nothing but its own steps, so while the pick is an errand an offer of
    another kind is left out. An update of the pick, an enabler, a goal under way and a forced move always
    go in.
    """

    def __init__(self, goal, candidate, site='base', source='current'):
        self.offers = [offer(site, goal, candidate, source)]
        self._decision = None

    @property
    def decision(self):
        if self._decision is None:
            self._decision = decide.decide(self.offers)
        return self._decision

    @property
    def running(self):
        # Every Gen I candidate is active, so the first offer is only a guard.
        return self.decision.pick or self.offers[0]

    @property
    def goal(self):
        return self.running.goal

    @property
    def pick(self):
        return self.running.candidate

    @property
    def kind(self):
        return self.pick.goal

    @property
    def errand(self):
        """Whether the pick is an errand, which nothing short cuts into."""
        return self.kind in ERRANDS

    @property
    def owns_party(self):
        return self.kind in OWNS_PARTY

    def errand_candidate(self, key, kind, frames=ERRAND_FRAMES):
        """An errand that serves the pick. It takes the pick's tier and value, at least a small one, so it
        goes before the longer pick. It pays an errand's frames again to cut into another errand. It ranks
        as the pick does under every play style."""
        held = self.pick
        return Candidate(key, held.tier, max(held.value, values.SMALL), frames,
                         interrupt_frames=ERRAND_FRAMES if self.errand else 0.0, hunt=held.hunt, plan=held.plan,
                         goal=kind)

    def wins(self, candidate):
        """Whether ``candidate`` would replace the pick, for a site that must know before it offers. A goal
        under the pick's own key is its update. Nothing cuts into an errand under way except a step of the
        same errand."""
        if candidate.key == self.pick.key:
            return True
        if self.errand:
            return candidate.goal == self.kind
        return arbiter.choose([self.pick, candidate]) is candidate

    def offer(self, goal, candidate, site, source=None, commit=None):
        """Offer ``goal`` as ``candidate`` from ``site`` and return the goal that runs now. ``commit``
        holds the writes that run only if the step ends with this offer running."""
        offered = offer(site, goal, candidate, source, commit)
        if (offered.serves or offered.hold or offered.forced or not self.errand
                or candidate.key == self.pick.key or candidate.goal == self.kind):
            self.offers.append(offered)
            self._decision = None
        return self.goal

    def commit(self):
        """Run the writes of the offer that runs."""
        if self.running.commit is not None:
            self.running.commit()
