"""One decision pipeline for both generations (docs/design/decide-pipeline.md).

Each source offers goals as candidates. ``decide`` keeps the latest offer of each goal, parks the offers
that cannot run, and picks by fixed rules in order: a move the game forces, a goal under way, the
arbiter's rank, and then the enabler of the best goal's first unmet need.

Until a group of sources switches on, the pipeline only runs beside the old chain in shadow mode. Nothing
here writes state, draws a random number or steps the emulator. An offer's ``commit`` holds the writes
that run only when it is picked, and shadow mode never runs one.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import arbiter
from .arbiter import Candidate

# The rule that picked. A difference between the pipeline and the old chain reuses the first three names.
FORCED = 'forced'   # A move the game forces now, by map or event.
HOLD = 'hold'       # A goal under way, weighed only against its own steps.
NEED = 'need'       # The enabler of the best goal's first unmet need.
RANK = 'rank'       # The arbiter's best goal, with nothing it needs left unmet.

@dataclass(frozen=True)
class Failure:
    """Why a goal cannot run now: one of the kinds below, and plain words for the journal and the pin."""
    kind: str
    detail: str

    def __str__(self):
        return self.detail


# Why an offer was parked, which a director reads.
STOOD_DOWN = Failure('stood_down', 'stood down')   # The supervisor stood it down or its budget ran out.
NO_ROUTE = Failure('no_route', 'no route')         # Its walk found no route lately.
CLAIM_HELD = Failure('claim_held', 'claim held')   # Its gift claim is held.
# Why a goal that ran was set aside. The stand-down keeps the kind (planning/monitor.py).
STUCK = Failure('stuck', 'it stopped moving')
NO_PROGRESS = Failure('no_progress', 'it stopped making progress')
MENU_FAILED = Failure('menu_failed', 'a menu task for it kept failing')
FAILURES = {failure.kind: failure for failure in (STOOD_DOWN, NO_ROUTE, CLAIM_HELD, STUCK, NO_PROGRESS, MENU_FAILED)}
# Why the goal catalogue lists a goal its source left out of the draw (planning/catalogue.py). Each
# Failure of these kinds names what it waits for in its own detail.
NEEDS = 'needs'       # Something it cannot start without, such as a ball or a rod.
NOT_NOW = 'not_now'   # A rule of its source holds it back for now, such as a party too weak for the grass.

# The chain chose a goal the filter parked.
PARKED = 'parked'


@dataclass(frozen=True)
class Offer:
    source: str              # The source that offered it, such as 'heal', 'story' or 'collection'.
    goal: object             # Today's Goal.
    candidate: Candidate
    needs: tuple = ()        # The needs it cannot run without, the most urgent first.
    serves: str = ''         # For an enabler, the need it meets.
    hold: bool = False       # A goal under way.
    forced: bool = False     # A move the game forces now.
    parked: Failure | None = None   # Why it cannot run now, None when it can.
    commit: object = field(default=None, compare=False)

    @property
    def key(self):
        key = getattr(self.goal, 'key', None)
        return key if isinstance(key, str) else self.candidate.key

    @property
    def kind(self):
        return self.candidate.goal or self.candidate.key


@dataclass(frozen=True)
class Decision:
    pick: Offer | None
    rule: str | None
    offers: tuple = ()
    parked: tuple = ()
    # For an enabler, the goal whose need it meets.
    serving: Offer | None = None

    @property
    def key(self):
        return None if self.pick is None else self.pick.key

    def record(self):
        """The pick as plain data for the trace's decide record, or None when nothing was picked."""
        if self.pick is None:
            return None
        return {'goal': self.pick.key, 'source': self.pick.source, 'rule': self.rule}


def needs(sites):
    """The needs table read off a chain of sites, each ``(site, source, serves)`` in chain order. A site
    needs the serves of every later site, since a later enabler overrode it there, and the latest site's
    need is the most urgent, so it comes first."""
    table = {}
    for index, (site, _, _) in enumerate(sites):
        later = []
        for _, _, serves in reversed(sites[index + 1:]):
            if serves and serves not in later:
                later.append(serves)
        table[site] = tuple(later)
    return table


def gather(sources, view):
    """Every offer from ``sources``, in source order. A source is a function of the view that only reads."""
    return [offer for source in sources for offer in source(view) or ()]


def latest(offers):
    """The latest offer of each goal, in the order each goal was last offered. A later offer of a goal under
    way is its update, so it stays under way."""
    kept = {}
    for offer in offers:
        earlier = kept.pop(offer.key, None)
        if earlier is not None and earlier.hold and not offer.hold:
            offer = replace(offer, hold=True)
        kept[offer.key] = offer
    return tuple(kept.values())


def _ranked(offers, pinned, style):
    order = arbiter.rank([offer.candidate for offer in offers], pinned, style)
    return [next(offer for offer in offers if offer.candidate is candidate) for candidate in order]


def serve(best, enablers):
    """The offer that runs for ``best``, and the goal it serves or None. While the pick has a need that an
    enabler in ``enablers``, keyed by the need it serves, can meet, that enabler runs in its place, and
    then its own needs are walked the same way. A need is met once per walk."""
    pick, serving, met = best, None, set()
    while True:
        need = next((need for need in pick.needs if need in enablers and need not in met), None)
        if need is None:
            return pick, serving
        met.add(need)
        pick, serving = enablers[need], best


def decide(offers, pinned=None, style=None):
    """The Decision for ``offers``. ``pinned`` and ``style`` are as for ``arbiter.rank``."""
    offers = latest(offers)
    parked = tuple(offer for offer in offers if offer.parked)
    live = [offer for offer in offers if not offer.parked]
    forced = [offer for offer in live if offer.forced]
    if forced:
        # The game allows one forced move at a time. Of two, the later source is the narrower one.
        return Decision(forced[-1], FORCED, offers, parked)
    goals = [offer for offer in live if not offer.serves]
    enablers = {}
    for offer in live:
        if offer.serves:
            enablers[offer.serves] = offer
    held = [offer for offer in goals if offer.hold]
    if held:
        hold = held[-1]
        pool, rule = [offer for offer in goals if offer is hold or offer.kind == hold.kind], HOLD
    else:
        pool, rule = goals, RANK
    ranked = _ranked(pool, pinned, style)
    best = ranked[0] if ranked else None
    if best is None:
        # With no goal to serve, the latest enabler still meets its need.
        enabler = next(reversed(enablers.values()), None)
        return Decision(enabler, None if enabler is None else NEED, offers, parked)
    pick, serving = serve(best, enablers)
    return Decision(pick, rule if serving is None else NEED, offers, parked, serving)


def difference(decision, chosen):
    """How ``decision`` differs from ``chosen``, the goal key the old chain chose, or None when they agree.

    The names are ``arbiter.compare``'s, plus ``parked`` when the chain's goal was filtered, ``need`` when
    either side is an enabler, and ``forced`` or ``hold`` when either side won by that rule.
    """
    pick = decision.pick
    if chosen is None:
        return None if pick is None else arbiter.IDLE
    if pick is not None and pick.key == chosen:
        return None
    mine = next((offer for offer in decision.offers if offer.key == chosen), None)
    if mine is None:
        return arbiter.UNLISTED
    if mine.parked:
        return PARKED
    if pick is None or mine.candidate.passive:
        return arbiter.PASSIVE
    if mine.serves or pick.serves or decision.rule == NEED:
        return NEED
    if mine.forced or pick.forced:
        return FORCED
    if mine.hold or pick.hold:
        return HOLD
    return arbiter.compare([pick.candidate, mine.candidate], None, mine.candidate.key).difference or arbiter.KEY
