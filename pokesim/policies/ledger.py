"""The resource ledger's view of a Red, Blue or Yellow snapshot.

The bag holds 20 distinct entries, the boxes 20 Pokémon each and the party six. A bag entry that sells
is a unit that frees money: spare battle items and renewable TMs first, then luxuries, then supplies,
and balls last, the order the shop already sells in when it raises funds. Key items and finite TMs
are never offered.
"""
from ..planning.ledger import BOX, MONEY, PARTY, Ledger, Resources, Unit
from ..strategy_data import PRICES
from .battle import BALLS
from .team import storage_headroom

BAG_SLOTS = 20
PARTY_SIZE = 6
# One sale tier is worth this much more per money freed than the tier before it.
TIER = 10 ** 6


def tier(item):
    from .shopping import LUXURIES, SPARE
    return 0 if item in SPARE or 201 <= item <= 250 else 1 if item in LUXURIES else 3 if item in BALLS else 2


def units(snapshot):
    from .shopping import RENEWABLE_TMS
    rows = []
    for index, (item, count) in enumerate(snapshot.items):
        price = PRICES.get(item, 0)
        if not count or price <= 0 or 201 <= item <= 250 and item not in RENEWABLE_TMS:
            continue
        amount = max(price // 2 * count, 1)
        rows.append(Unit(('item', index), MONEY, tier(item) * TIER * amount, 'sell', amount, detail=index,
                         order=(-price, index)))
    return tuple(rows)


def read(snapshot, kinds=None):
    """Free room for ``kinds``, every kind when None, and the units that free it."""
    wanted = (lambda kind: True) if kinds is None else kinds.__contains__
    free = {}
    if wanted('items'):
        free['items'] = BAG_SLOTS - len(snapshot.items)
    if wanted(BOX):
        free[BOX] = storage_headroom(snapshot)
    if wanted(PARTY):
        free[PARTY] = PARTY_SIZE - len(snapshot.party)
    found = units(snapshot) if wanted(MONEY) else ()
    return Resources(free, snapshot.money if wanted(MONEY) else 0, found)


def ledger():
    return Ledger(read)
