"""One value score for every Pokémon in the PC, and one rule for making room, in all six games.

Each stored Pokémon gets a score built from what it is worth to the adventure: a plan role, shiny,
how rare its DVs are for its family (rarity.py), the post-game focus, other adventures wanting it in
trade, and where it came from. Where it came from is only one input. It never keeps a Pokémon by
itself. Level is not in it, since any copy can be trained.

When room is needed, the lowest-value Pokémon goes first, so among plain spares the most common DVs
go first. A few never go: Keep-locked Pokémon, eggs, party members, trained copies, the best and the
rarest copy of each species (each Unown letter), so the Pokédex never loses an entry, and the copies
a running plan relies on. Each species keeps those, or the copies a plan or the focus needs. The rest
are spares, released lowest score first, and only when room is needed. Copies the demand needs come
after every spare. So the PC can only fill with nothing to release when every slot is locked.

``worth`` asks whether a new copy should be kept at all, for a catch or a gift, by the same rows.

The generation adapters (release.py in each generation) turn their snapshot into ``Entry`` rows, so
this module knows nothing about either cartridge.
"""
import math
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pokecore.dvs import is_shiny

from .rarity import RatingUnavailable, generic

# Every weight in one place. A score is the sum of the parts a Pokémon earns.
WEIGHTS = {
    'role': 400,        # a plan relies on it: breeding parent or stock, trainee, team member, offered trade
    'shiny': 900,       # shiny DVs, above the rarest plain DVs, so it only goes once every plain spare is gone
    'rarity': 50,       # each halving of the share of copies that score as well (rarity.py), 800 at the rarest
    'focus': 150,       # a copy the post-game focus or standing target is working on
    'demand': 50,       # each linked adventure that wishes for the species in trade
    'demand_cap': 100,  # the most trade demand can add
    'legendary': 200,   # a legendary or one-time event Pokémon: it only returns on a long timer, and trades best
    'gift': 80,         # an ordinary gift or fossil: the cartridge gives it once
    'traded': 60,       # traded in from a trainer who is not linked, so it cannot be traded back
    'reward': 0,        # a League reward: the ledger can always deliver another
    'caught': 0,        # caught by the player, or traded from a linked adventure
    'favor': 2,         # Favor shiny or Favor DVs multiplies that part
}
# Breeding stock and offered trade partners hold a plan role for at most this many copies of a
# species, so a breeding plan cannot pin a whole box.
ROLE_COPIES = 2
# Copies of a species the post-game focus or a standing target keeps.
FOCUS_COPIES = 2
# Stat experience summed over the five stats that counts as fully trained. A trained copy is never
# released automatically.
TRAINED_STAT_EXP = 100000
# Release values this close count as equal when choosing a PC visit, so it stays in one box. Each box
# change saves the game, about 4000 frames. It equals one RARITY_STEP of rarity points, so a copy
# twice as rare never shares a band with the one it replaced.
VISIT_BAND = 50
# A new copy of a species already held is kept only when it is at least this many times rarer than
# the rarest copy held.
RARITY_STEP = 2
LAST_COPY = 'last copy'
# The reason on every row when the PC cannot rate (rate).
UNRATED = 'Not rated'
DEADLOCK = 'PC full: every stored Pokémon is Keep-locked, trained, a plan\'s or the best copy of its species.'


@dataclass(frozen=True)
class Entry:
    """One Pokémon as both generations describe it. ``slot`` is (box, position), None in the party."""
    slot: tuple | None
    group: tuple            # (dex, Unown letter or 0)
    name: str
    level: int
    experience: int = 0
    dvs: tuple = ()         # HP, Attack, Defense, Speed, Special
    stat_exp: tuple = ()
    egg: bool = False
    origin: str = 'caught'  # caught, legendary, gift, traded or reward
    locked: bool = False    # Keep, or set to Never trade
    role: bool = False      # a specific Pokémon a plan relies on
    stock: bool = False     # breeding stock or an offered trade partner, capped at ROLE_COPIES
    requested: str = ''     # 'release' when the owner asked, LAST_COPY when the confirm named the last copy
    record: object = field(default=None, compare=False, hash=False)
    trade: bool = False     # the stock is a trade's give or an offered partner, so it holds a role but no floor

    @property
    def dex(self):
        return self.group[0]


@dataclass(frozen=True)
class Inputs:
    """What the adventure wants. ``demand`` maps a dex number to the copies a plan needs and ``wishes``
    to the linked adventures that want it in trade. ``rarity`` gives a copy's rarity from its dex number
    and DVs (rarity.py), or None when it cannot be told. ``team`` holds the (dex, DVs) of the party as
    the PC visit began, so a team member deposited at this visit is no spare."""
    demand: dict = field(default_factory=dict)
    focus: frozenset = frozenset()
    wishes: Counter = field(default_factory=Counter)
    favor: str | None = None   # 'shiny' or 'dvs'
    rarity: object = generic
    team: frozenset = frozenset()


@dataclass
class Rated:
    entry: Entry
    score: int
    parts: list
    # floor (never released automatically), kept (needed copy, after every spare) or spare
    status: str = 'spare'
    reason: str = ''
    rarity: float | None = None

    def describe(self):
        """The breakdown the PC tab and the journal show, such as "Score 1238: Rarity 1 in 512 +450, Shiny +900"."""
        parts = ', '.join(f'{label} +{points}' for label, points in self.parts if points)
        head = f'{self.reason}. ' if self.reason else ''
        return f'{head}Score {self.score}' + (f': {parts}' if parts else '')


def rarity_of(entry, inputs=Inputs()):
    """The share of copies of the family that score at least as well as ``entry``, or None."""
    if len(entry.dvs) != 5 or entry.egg:
        return None
    return inputs.rarity(entry.dex, entry.dvs)


def rarity_points(tail):
    """WEIGHTS['rarity'] for each halving of ``tail``."""
    return round(WEIGHTS['rarity'] * math.log2(1 / tail)) if tail else 0


def parts(entry, inputs=Inputs(), role=False):
    """The scored parts of one Pokémon as (label, points)."""
    weight = WEIGHTS
    record = {'dvs': list(entry.dvs)}
    shiny_x = weight['favor'] if inputs.favor == 'shiny' else 1
    dvs_x = weight['favor'] if inputs.favor == 'dvs' else 1
    known = len(entry.dvs) == 5
    rows = []
    if role:
        rows.append(('Plan role', weight['role']))
    if known and is_shiny(record):
        rows.append(('Shiny', weight['shiny'] * shiny_x))
    tail = rarity_of(entry, inputs)
    if tail:
        rows.append((f'Rarity 1 in {round(1 / tail)}', rarity_points(tail) * dvs_x))
    wished = min(weight['demand'] * inputs.wishes.get(entry.dex, 0), weight['demand_cap'])
    if wished:
        rows.append(('Wanted in trade', wished))
    origin = weight.get(entry.origin, 0)
    if origin:
        rows.append(({'gift': 'Gift', 'legendary': 'Legendary', 'traded': 'Traded in'}.get(entry.origin, entry.origin.title()), origin))
    return rows


def _rank(rated):
    # Level only breaks a tie, as between copies whose DVs are not known.
    entry = rated.entry
    return (rated.score, -(rated.rarity or 1), sum(entry.dvs), entry.experience, entry.level)


def rate(entries, inputs=Inputs()):
    """Score every Pokémon and mark which ones may go. Returns Rated rows in the order given.

    When ``inputs.rarity`` raises RatingUnavailable, every row is a floor marked UNRATED, so only an
    owner's request may release and no new copy is kept but a missing entry, a shiny or the only copy.
    The only copy of a species keeps its reason, so a request still needs the last-copy confirm."""
    try:
        return _rate(entries, inputs)
    except RatingUnavailable:
        held = Counter(entry.group for entry in entries if not entry.egg)
        reason = lambda entry: ('Egg' if entry.egg else 'Keep' if entry.locked else 'In the party' if entry.slot is None  # noqa: E731
                                else 'Only copy' if held[entry.group] == 1 else UNRATED)
        return [Rated(entry, 0, [], 'floor', reason(entry)) for entry in entries]


def _rate(entries, inputs):
    groups = defaultdict(list)
    for entry in entries:
        if not entry.egg:
            groups[entry.group].append(entry)
    rows = {}
    for group, copies in groups.items():
        # Breeding stock and offered partners hold a role for their best ROLE_COPIES only.
        plain = {entry: sum(points for _, points in parts(entry, inputs)) for entry in copies}
        stock = sorted((entry for entry in copies if entry.stock and not entry.role), reverse=True,
                       key=lambda entry: (plain[entry], sum(entry.dvs), entry.experience, entry.level))
        roles = {entry for entry in copies if entry.role} | set(stock[:ROLE_COPIES])
        rated = [Rated(entry, 0, parts(entry, inputs, entry in roles), rarity=rarity_of(entry, inputs))
                 for entry in copies]
        for row in rated:
            row.score = sum(points for _, points in row.parts)
        rated.sort(key=_rank, reverse=True)
        # The rarest copy stays too when another part, such as a gift's, puts a commoner copy first.
        known = [row for row in rated if row.rarity is not None]
        rarest = min(known, key=lambda row: row.rarity) if known else None
        need = max(1, inputs.demand.get(group[0], 0), FOCUS_COPIES if group[0] in inputs.focus else 1)
        if group[0] in inputs.focus:
            # Only the copies the focus keeps. A plainer copy stays a spare, so a hunt for a better
            # one can make room by releasing it.
            for row in rated[:FOCUS_COPIES]:
                row.parts.append(('Focus', WEIGHTS['focus']))
                row.score += WEIGHTS['focus']
        for index, row in enumerate(rated):
            if index == 0:
                row.status, row.reason = 'floor', 'Only copy' if len(rated) == 1 else 'Best copy'
            elif row.entry in roles and not row.entry.trade:
                # A plan's trainee, partner or stock within ROLE_COPIES. Only an owner's request takes it.
                row.status, row.reason = 'floor', 'Plan role'
            elif row is rarest and (rated[0].rarity is None or row.rarity < rated[0].rarity):
                row.status, row.reason = 'floor', 'Rarest copy'
            elif sum(row.entry.stat_exp) >= TRAINED_STAT_EXP:
                # Training is hours of play a new catch cannot make up, so only an owner's request takes it.
                row.status, row.reason = 'floor', 'Trained'
            elif index < need or row.entry in roles:
                row.status = 'kept'
            if row.entry.locked:
                row.status, row.reason = 'floor', 'Keep'
            elif row.entry.slot is None:
                row.status, row.reason = 'floor', 'In the party'
            elif len(row.entry.dvs) == 5 and (row.entry.dex, row.entry.dvs) in inputs.team:
                # Deposited from the party at this visit, as Soak Red's level 43 Weezing was before its release.
                row.status, row.reason = 'floor', 'Team member'
            rows[row.entry] = row
    for entry in entries:
        if entry.egg:
            rows[entry] = Rated(entry, 0, [], 'floor', 'Egg')
    return [rows[entry] for entry in entries]


@dataclass(frozen=True)
class Worth:
    """Whether a new copy is worth keeping, why, its rarity and the rarest held copy's."""
    keep: bool
    reason: str
    rarity: float | None = None
    best: float | None = None


# Floors a new copy earns only by being better than what is held.
BETTER = ('Best copy', 'Rarest copy')


def worth(candidate, held, inputs=Inputs(), *, missing=False, needed=0, active_box=None):
    """Whether the PC would keep ``candidate``, an Entry not yet held, beside the ``held`` rows.

    A copy for a missing Pokédex entry and a shiny are always kept. Otherwise it is rated with the
    held rows and kept when it is not a spare: a plan or the demand needs it, or it is at least
    RARITY_STEP times rarer than the rarest copy of its species held. Its DVs can be unknown, as for
    a gift before it is received. Then it is kept only when the plan needs it or none is held.
    ``needed`` and ``active_box`` are what the release path would pass to ``releases`` once it is
    boxed (catch_visit), and a copy is not kept when that visit would take it or a rarer copy.
    """
    return verdict(rate([*held, candidate], inputs), missing=missing, needed=needed, active_box=active_box)


def catch_visit(headroom, requests=0):
    """The ``needed`` the release path passes to ``releases`` once one more Pokémon is boxed, or 0
    while the boxes still keep their reserve. ``headroom`` is the free box slots before it and
    ``requests`` the owner's release requests, which the visit takes too."""
    from .planning.ledger import box_wanted
    after = headroom - 1
    return max(box_wanted(after, True), requests, 1) if box_wanted(after, False) else 0


class VisitTeam:
    """The (dex, DVs) of every party member seen since the player entered the current map, for
    Inputs.team. A PC visit happens on one map, so a member deposited there is no spare until a later
    visit, however the menus open and close between the deposit and the release."""

    def __init__(self):
        self.where, self.keys, self.boxed = None, frozenset(), frozenset()

    def observe(self, where, keys, stored=()):
        """``stored`` are the boxed (dex, DVs). One seen in a box at this visit before it joined the party is
        no team member, as a Crystal spare withdrawn only to take its item off was before its release."""
        same = where == self.where
        boxed = frozenset(stored) - (self.keys if same else frozenset())
        self.boxed = (self.boxed | boxed) if same else boxed
        self.keys = (frozenset(keys) - self.boxed) | (self.keys if same else frozenset())
        self.where = where
        return self.keys


def keeps_new(rows, *, missing=False, headroom=None, active_box=None):
    """The one rule for a new copy of an owned species, the last of ``rows``: whether the PC keeps it
    at the visit it brings (verdict). Every catch of an owned species in both gens and an incoming
    trade ask it. ``headroom`` is the free box slots before it, or None when the snapshot does not
    show them. Rarity has no level term, so a higher level copy is no better."""
    needed = 0 if headroom is None else catch_visit(headroom, len(requested(rows)))
    return verdict(rows, missing=missing, needed=needed, active_box=active_box).keep


def verdict(rows, *, missing=False, needed=0, active_box=None):
    """``worth`` for rows already rated with the new copy last."""
    row = rows[-1]
    candidate = row.entry
    if missing:
        return Worth(True, 'New entry', row.rarity)
    if len(candidate.dvs) == 5 and is_shiny({'dvs': list(candidate.dvs)}):
        return Worth(True, 'Shiny', row.rarity)
    if row.reason == UNRATED:
        return Worth(False, UNRATED)
    same = [other for other in rows[:-1] if other.entry.group == candidate.group and not other.entry.egg]
    best = min((other.rarity for other in same if other.rarity is not None), default=None)
    if row.status == 'spare':
        return Worth(False, 'Spare', row.rarity, best)
    if row.reason in BETTER:
        # A held copy without DV data, as in a compact snapshot, is not counted.
        if best is None:
            found = Worth(row.rarity is not None, 'Rarer' if row.rarity is not None else 'DVs not known', row.rarity)
        elif row.rarity is None:
            return Worth(False, 'DVs not known', None, best)
        else:
            rarer = row.rarity * RARITY_STEP <= best
            found = Worth(rarer, 'Rarer' if rarer else 'Not rare enough', row.rarity, best)
    else:
        found = Worth(True, row.reason or 'Needed', row.rarity, best)
    if found.keep and pushes_out(rows, needed, active_box):
        return Worth(False, 'Pushes out a rarer copy', row.rarity, best)
    return found


def pushes_out(rows, needed, active_box=None):
    """Whether the visit ``releases`` would make with the new copy last in ``rows`` takes that copy
    or one rarer than it, of any species. The owner's requests go whatever is caught, so they do
    not count."""
    if needed <= 0:
        return False
    new = rows[-1]
    for row in releases(rows, needed, active_box):
        if row is new:
            return True
        if (not row.entry.requested and row.rarity is not None and new.rarity is not None
                and row.rarity < new.rarity):
            return True
    return False


REFUSED = ('Keep', 'In the party', 'Team member', 'Egg')
ORDER = {'spare': 1, 'kept': 2}


def may_go(row):
    """Whether a release may take it. An owner's request may take a best copy, and the last copy of a
    species only when the confirm named it, but never a Keep, party or egg Pokémon."""
    asked = row.entry.requested
    if asked and row.reason not in REFUSED:
        return row.reason != 'Only copy' or asked == LAST_COPY
    return row.status in ORDER


def queue(rated):
    """Pokémon that may go, in release order: owner requests, then spares and then kept copies, each lowest score first."""
    return sorted(filter(may_go, rated), key=lambda row: (not row.entry.requested, ORDER.get(row.status, 0),
                                                          _rank(row), row.entry.slot or ()))


def requested(rated):
    """The owner's release requests a release may take, in release order. Each one starts a PC visit."""
    return [row for row in queue(rated) if row.entry.requested]


def releases(rated, needed, active_box=None):
    """The ``needed`` lowest-value releases, ordered for one PC visit.

    Values within VISIT_BAND count as equal, and among equal values the open box goes first, then the
    box holding the most of them, since every box change saves the game. The visit takes the owner's
    requests first, then the open box, then the box holding the most of the chosen ones.
    """
    candidates = list(filter(may_go, rated))
    band = lambda row: (not row.entry.requested, ORDER.get(row.status, 0), row.score // VISIT_BAND)  # noqa: E731
    per_band = Counter((band(row), row.entry.slot[0]) for row in candidates)
    order = lambda row: (band(row), row.entry.slot[0] != active_box, -per_band[band(row), row.entry.slot[0]],  # noqa: E731
                         _rank(row), row.entry.slot)
    chosen = sorted(candidates, key=order)[:max(needed, 0)]
    per_box = Counter(row.entry.slot[0] for row in chosen)
    # Owner requests stay in front, so one never waits past a visit behind spares from another box.
    return sorted(chosen, key=lambda row: (not row.entry.requested, row.entry.slot[0] != active_box,
                                           -per_box[row.entry.slot[0]], row.entry.slot))


SHOWN = 5


def annotate(rated, active_box=None):
    """The PC tab's view of each boxed Pokémon by (box, position): its score, the breakdown, its status
    and its place among the next SHOWN releases."""
    upcoming = {row.entry.slot: index + 1 for index, row in enumerate(releases(rated, SHOWN, active_box))}
    return {row.entry.slot: {'score': row.score, 'text': row.describe(), 'status': row.status,
                             'reason': row.reason, 'next': upcoming.get(row.entry.slot),
                             'requested': row.entry.requested or None}
            for row in rated if row.entry.slot is not None}


def pc_request(rated, slot, key, keyof, confirm=''):
    """The request for the boxed Pokémon at ``slot`` whose trade key ``keyof`` gives as ``key`` (request_value)."""
    row = next((row for row in rated if row.entry.slot == slot and keyof(row.entry.record) == key), None)
    return request_value(row, confirm)


def request_value(row, confirm=''):
    """The stored request for an owner's Release on ``row``, or ValueError with the reason it is refused.
    The last copy of a species goes only when ``confirm`` names it."""
    if row is None:
        raise ValueError('That Pokémon has moved. Refresh the PC and try again.')
    if row.reason == 'Keep':
        raise ValueError(f'{row.entry.name} is set to Keep. Change its trade setting first.')
    if row.reason == 'In the party':
        raise ValueError(f'{row.entry.name} is in the party. Only boxed Pokémon can be released.')
    if row.reason == 'Egg':
        raise ValueError('An egg is never released.')
    if row.reason == 'Only copy':
        if plain_name(confirm) != plain_name(row.entry.name):
            raise ValueError(f'This is your only {row.entry.name}. Type its name to confirm.')
        return LAST_COPY
    return 'release'


def plain_name(name):
    """A species name to compare typed text with: no accents, spaces or punctuation, ♀ as F and ♂ as M,
    so "mr mime" names Mr. Mime and "Nidoran F" names Nidoran♀."""
    text = unicodedata.normalize('NFKD', str(name).replace('♀', 'F').replace('♂', 'M'))
    return ''.join(char for char in text if char.isalnum()).casefold()


def full_notice(store, blocked):
    """Whether to journal DEADLOCK now: once when the PC fills with nothing that may go, and again only
    after room has come back. The mark is kept in the store, so a restart does not repeat it."""
    logged = bool(store.get('pc_deadlock_logged'))
    if blocked != logged:
        store.set('pc_deadlock_logged', blocked)
    return blocked and not logged


def deadlocked(rated, free):
    """Whether the PC is full, ``free`` being its free slots, and no Pokémon may go: every one is
    Keep-locked, a plan's, in the party or the last copy of its species."""
    return free <= 0 and not queue(rated)
