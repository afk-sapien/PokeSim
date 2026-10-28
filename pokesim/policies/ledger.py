"""The resource ledger's view of a Red, Blue or Yellow snapshot.

The bag holds 20 distinct entries, the boxes 20 Pokémon each and the party six. A bag entry that sells
is a unit that frees money: spare battle items and renewable TMs first, then luxuries, then supplies,
and balls last. A crowded bag sells for room in another order: what no plan uses first, then the
finite TM cheapest to buy again, and only when the bag is full. Key items are never offered, and
finite TMs never sell for money.

Money held back from the shop is the ledger's standing reservations: a cash reserve, and the Safari
Zone fee while the story still needs it.
"""
from ..planning.ledger import BOX, MONEY, PARTY, Ledger, Need, Resources, Shortfall, Unit
from ..strategy_data import ITEMS, PRICES
from ..tm_shop import PRICES as REPLACEMENT_PRICES
from .battle import BALLS
from .team import storage_headroom

BAG_SLOTS = 20
PARTY_SIZE = 6
# A bag this crowded also sells the battle items and spare repels no plan uses.
CROWDED = 18
# One sale tier is worth this much more per money freed than the tier before it.
TIER = 10 ** 6

# TMs any mart sells again, so one in the bag can always go.
RENEWABLE_TMS = frozenset(200 + number for number in (1, 2, 5, 7, 9, 15, 17, 23, 32, 33, 37, 50))
# Battle items no plan uses, kept only until the bag or the wallet needs the room.
BATTLE_ITEMS = frozenset(ITEMS[name] for name in ('X_ACCURACY', 'GUARD_SPEC', 'DIRE_HIT', 'X_ATTACK', 'X_DEFEND',
                                                  'X_SPEED', 'X_SPECIAL'))
UNUSED = BATTLE_ITEMS | {ITEMS['NUGGET']}
# Raise a partner, but sell before supplies when money runs out.
LUXURIES = frozenset(ITEMS[name] for name in ('HP_UP', 'PROTEIN', 'IRON', 'CARBOS', 'CALCIUM', 'PP_UP', 'RARE_CANDY'))
REPELS = tuple(ITEMS[name] for name in ('MAX_REPEL', 'SUPER_REPEL', 'REPEL'))

# Red and Blue refuse Safari Zone entry below this amount, and the story needs two visits' worth of
# prizes (Surf and the Gold Teeth), so an unaffordable fee is a permanent roadblock, not a delay.
SAFARI_FEE = 500
CASH_RESERVE = 300


def tier(item):
    return 0 if item in UNUSED or 201 <= item <= 250 else 1 if item in LUXURIES else 3 if item in BALLS else 2


def fund_units(snapshot):
    rows = []
    for index, (item, count) in enumerate(snapshot.items):
        price = PRICES.get(item, 0)
        if not count or price <= 0 or 201 <= item <= 250 and item not in RENEWABLE_TMS:
            continue
        amount = max(price // 2 * count, 1)
        rows.append(Unit(('item', index), MONEY, tier(item) * TIER * amount, 'sell', amount, detail=index,
                         order=(-price, index)))
    return tuple(rows)


def room_units(snapshot):
    """Bag entries that sell to free an entry, surplus first in bag order, then a finite TM in a full bag."""
    crowded = len(snapshot.items) >= CROWDED
    # The best repel in the bag is used first and restocked for a legendary, so weaker ones are spare.
    counts = dict(snapshot.items)
    spare = set([item for item in REPELS if counts.get(item)][1:]) if crowded else set()
    rows = []
    for index, (item, count) in enumerate(snapshot.items):
        if not count:
            continue
        if item == ITEMS['NUGGET'] or item in RENEWABLE_TMS or crowded and (item in BATTLE_ITEMS or item in spare):
            value = 0
        elif len(snapshot.items) >= BAG_SLOTS and item in REPLACEMENT_PRICES:
            # Cheapest to buy the whole stack back later.
            value = TIER + REPLACEMENT_PRICES[item] * count
        else:
            continue
        rows.append(Unit(('entry', index), 'items', value, 'sell', detail=index, order=(index,)))
    return tuple(rows)


def money_needs(snapshot):
    """The standing money reservations: the cash reserve, and the Safari fee from the fourth badge until
    both Safari prizes are collected."""
    counts = dict(snapshot.items)
    knows = {move for mon in snapshot.party for move in mon.moves}
    surf = counts.get(ITEMS['HM03']) or 57 in knows
    strength = counts.get(ITEMS['HM04']) or 70 in knows or counts.get(ITEMS['GOLD_TEETH'])
    needs = {'cash': Need(money=CASH_RESERVE)}
    if snapshot.badges & 8 and not (surf and strength):
        needs['safari'] = Need(money=SAFARI_FEE)
    return needs


def cash_reserve(snapshot):
    """Money the shop leaves alone."""
    return sum(need.money for need in money_needs(snapshot).values())


def read(snapshot, kinds=None):
    """Free room for ``kinds``, every kind when None, and the units that free it."""
    wanted = (lambda kind: True) if kinds is None else kinds.__contains__
    free = {}
    found = ()
    if wanted('items'):
        free['items'] = BAG_SLOTS - len(snapshot.items)
        found += room_units(snapshot)
    if wanted(BOX):
        free[BOX] = storage_headroom(snapshot)
    if wanted(PARTY):
        free[PARTY] = PARTY_SIZE - len(snapshot.party)
    if wanted(MONEY):
        found += fund_units(snapshot)
    return Resources(free, snapshot.money if wanted(MONEY) else 0, found)


def ledger():
    return Ledger(read)


def first_sale(snapshot, kind, goal):
    """The bag index the ledger sells first to free ``kind``, or None when nothing can go."""
    books = ledger()
    books.snapshot(snapshot, kinds=(kind,))
    plan = books.make_room(Shortfall(goal, {kind: 1}))
    return plan[0].detail if plan else None
