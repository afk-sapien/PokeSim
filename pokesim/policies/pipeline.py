"""The Gen I overworld chain's sites as decide pipeline sources (docs/design/decide-pipeline.md, slice 1).

Each site of the chain in ``strategic.py`` records its offer under its site name, and ``offer`` turns
that into a pipeline ``Offer`` with the site's source, needs and rule. The needs table is read off the
chain: a goal needs every enabler whose replace comes later, since a later replace overrides it today.
The most urgent need is the one the latest site serves. Changing the table changes behaviour once a
group switches on, so a change goes to the lead first.
"""
from __future__ import annotations

from ..planning.decide import Offer

# Every overworld chain site in the order it runs: the site, its source and the need it serves.
SITES = (
    ('base', 'story', ''),             # The story goal, the plan placeholder or the current goal.
    ('boss', 'boss', 'trained'),       # Training for the next boss.
    ('project', 'collection', ''),     # The collection project under way.
    ('pickup', 'pickup', ''),          # A ground item pickup under way.
    ('swap', 'party', 'reserve'),      # A reserve swap under way.
    ('release', 'party', 'room'),      # A release that makes room in storage.
    ('box', 'party', 'room'),          # A box change that makes room for catches.
    ('heal_latch', 'heal', 'healthy'),  # The heal under way, set by the step.
    ('heal', 'heal', 'healthy'),       # The heal under way, set again by the overworld step.
    ('upgrade', 'party', ''),          # A stronger reserve in the box.
    ('supplies', 'supplies', 'supplies'),  # A restock the goal cannot go on without.
    ('teach', 'moves', ''),            # An owned HM.
    ('tm_trip', 'moves', ''),          # A TM trip under way.
    ('tm', 'moves', ''),               # An owned TM or supply item, or a TM to buy.
    ('trash', 'trash', 'lock'),        # The trash can locks in Vermilion Gym.
    ('collection', 'collection', ''),  # The collection's pick.
    ('pickup_new', 'pickup', ''),      # A new ground item pickup.
    ('passage', 'passage', ''),        # Leaving the League side of Victory Road.
    ('elevator', 'elevator', ''),      # Riding a lift.
)

# Sites whose goal is under way, and sites the game forces by map.
HOLDS = frozenset({'pickup', 'tm_trip'})
FORCED = frozenset({'passage', 'elevator'})


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


def offer(site, goal, candidate, source=None):
    """The pipeline offer of ``goal`` at chain ``site``. An unknown site offers as the legacy chain."""
    return Offer(source or SOURCES.get(site, 'legacy'), goal, candidate, needs=NEEDS.get(site, ()),
                 serves=SERVES.get(site, ''), hold=site in HOLDS, forced=site in FORCED)
