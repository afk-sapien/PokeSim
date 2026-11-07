"""One value score for every Pokémon in the PC, and one rule for making room, in all six games.

Each stored Pokémon gets a score built from what it is worth to the adventure: a plan role, shiny,
perfect and rare DVs, the level and training put into it, the post-game focus, other adventures
wanting it in trade, and where it came from. Where it came from is only one input. It never keeps a
Pokémon by itself.

When room is needed, the lowest-value Pokémon goes first. A few never go: Keep-locked Pokémon, eggs,
party members, the best copy of each species (each Unown letter), so the Pokédex never loses an
entry, and the copies a running plan relies on. Each species keeps its best copy, or the copies a
plan or the focus needs. The rest are spares, released lowest score first, and only when room is
needed. Copies the demand needs come after every spare. So the PC can only fill with nothing to
release when every slot is locked, a plan's or the last copy of its species.

The generation adapters (release.py in each generation) turn their snapshot into ``Entry`` rows, so
this module knows nothing about either cartridge.
"""
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pokecore.dvs import is_perfect, is_shiny

from .investment import rare_find

# Every weight in one place. A score is the sum of the parts a Pokémon earns.
WEIGHTS = {
    'role': 400,        # a plan relies on it: breeding parent or stock, trainee, team member, offered trade
    'shiny': 300,       # shiny DVs, so it only goes once every plain spare is gone
    'perfect': 250,     # all five DVs at 15
    'rare': 120,        # DVs in the rarest half percent for its species (investment.rare_find)
    'dvs': 60,          # natural potential, scaled by the DV total out of 75
    'level': 100,       # the level, scaled to 100 at Lv 100
    'training': 100,    # stat experience, full at TRAINED_STAT_EXP across the five stats
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
# Stat experience summed over the five stats that counts as fully trained.
TRAINED_STAT_EXP = 100000
# Release values this close count as equal when choosing a PC visit, so it stays in one box. Each box
# change saves the game, about 4000 frames, and a plain spare is worth under 200.
VISIT_BAND = 50
LAST_COPY = 'last copy'
DEADLOCK = 'PC full: every stored Pokémon is Keep-locked, a plan\'s or the only copy of its species.'


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
    to the linked adventures that want it in trade."""
    demand: dict = field(default_factory=dict)
    focus: frozenset = frozenset()
    wishes: Counter = field(default_factory=Counter)
    favor: str | None = None   # 'shiny' or 'dvs'


@dataclass
class Rated:
    entry: Entry
    score: int
    parts: list
    # floor (never released automatically), kept (needed copy, after every spare) or spare
    status: str = 'spare'
    reason: str = ''

    def describe(self):
        """The breakdown the PC tab and the journal show, such as "Score 500: Trained Lv 100 +200, Shiny +300"."""
        parts = ', '.join(f'{label} +{points}' for label, points in self.parts if points)
        head = f'{self.reason}. ' if self.reason else ''
        return f'{head}Score {self.score}' + (f': {parts}' if parts else '')


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
    if known and is_perfect(record):
        rows.append(('Perfect DVs', weight['perfect'] * dvs_x))
    elif known and rare_find(record):
        rows.append(('Rare DVs', weight['rare'] * dvs_x))
    if known:
        rows.append((f'DVs {sum(entry.dvs)}/75', round(weight['dvs'] * dvs_x * sum(entry.dvs) / 75)))
    level = round(weight['level'] * min(entry.level, 100) / 100)
    training = round(weight['training'] * min(1, sum(entry.stat_exp) / TRAINED_STAT_EXP))
    rows.append((f'{"Trained " if training else ""}Lv {entry.level}', level + training))
    wished = min(weight['demand'] * inputs.wishes.get(entry.dex, 0), weight['demand_cap'])
    if wished:
        rows.append(('Wanted in trade', wished))
    origin = weight.get(entry.origin, 0)
    if origin:
        rows.append(({'gift': 'Gift', 'legendary': 'Legendary', 'traded': 'Traded in'}.get(entry.origin, entry.origin.title()), origin))
    return rows


def _rank(rated):
    entry = rated.entry
    return (rated.score, sum(entry.dvs), entry.experience)


def rate(entries, inputs=Inputs()):
    """Score every Pokémon and mark which ones may go. Returns Rated rows in the order given."""
    groups = defaultdict(list)
    for entry in entries:
        if not entry.egg:
            groups[entry.group].append(entry)
    rows = {}
    for group, copies in groups.items():
        # Breeding stock and offered partners hold a role for their best ROLE_COPIES only.
        plain = {entry: sum(points for _, points in parts(entry, inputs)) for entry in copies}
        stock = sorted((entry for entry in copies if entry.stock and not entry.role), key=plain.get, reverse=True)
        roles = {entry for entry in copies if entry.role} | set(stock[:ROLE_COPIES])
        rated = [Rated(entry, 0, parts(entry, inputs, entry in roles)) for entry in copies]
        for row in rated:
            row.score = sum(points for _, points in row.parts)
        rated.sort(key=_rank, reverse=True)
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
            elif index < need or row.entry in roles:
                row.status = 'kept'
            if row.entry.locked:
                row.status, row.reason = 'floor', 'Keep'
            elif row.entry.slot is None:
                row.status, row.reason = 'floor', 'In the party'
            rows[row.entry] = row
    for entry in entries:
        if entry.egg:
            rows[entry] = Rated(entry, 0, [], 'floor', 'Egg')
    return [rows[entry] for entry in entries]


REFUSED = ('Keep', 'In the party', 'Egg')
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
