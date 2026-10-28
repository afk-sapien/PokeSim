"""The resource ledger's view of a Gold, Silver or Crystal snapshot.

Each pocket holds a fixed number of distinct entries, the boxes 20 Pokémon each and the party six.
An items-pocket entry no plan uses can be put in the PC to free its entry, worth its sale price for
the whole stack. Valuables are sold when money runs out, so they go last. Items a plan uses are never
offered.
"""
from ..planning.ledger import BOX, MONEY, PARTY, PRICELESS, Ledger, Need, Resources, Unit
from .release import headroom

# Distinct entries each Gen 2 pocket holds.
POCKET_SLOTS = {'items': 20, 'balls': 12}
PARTY_SIZE = 6
STACK = 99
# Added to a valuable's worth so every ordinary entry goes before any valuable.
VALUABLE = 10 ** 7


def pocket(data, item):
    return 'balls' if data.item_attributes[item]['pocket'] == 'BALL' else 'items'


def needs(data, snapshot, item):
    """What the bag needs before it can take one more ``item``: nothing when it stacks, else one entry."""
    name = pocket(data, item)
    count = dict(snapshot.pockets.get(name, ())).get(item, 0)
    if count and count < STACK:
        return Need()
    return Need(pocket_slots={name: 1})


def kept_items(data):
    """Items some plan uses from the bag, with every evolution item the species data names."""
    from .training import KEPT_ITEMS
    kept = {data.items[name] for name in KEPT_ITEMS if name in data.items}
    kept |= {data.items[req] for entry in data.species.values() for evo in entry['evolutions']
             if evo['method'] in ('item', 'trade') for req in evo['requirements'] if req in data.items}
    return kept


def units(data, snapshot):
    from .training import VALUABLES
    kept = kept_items(data)
    valuables = {data.items[name] for name in VALUABLES if name in data.items}
    rows = []
    for item, count in snapshot.pockets.get('items', ()):
        attributes = data.item_attributes.get(item, {})
        if item in kept or attributes.get('pocket') != 'ITEM':
            value = PRICELESS
        else:
            value = attributes['price'] * count + (VALUABLE if item in valuables else 0)
        rows.append(Unit(('item', item), 'items', value, 'deposit', detail=item, order=(item,)))
    return tuple(rows)


def read(data, snapshot, kinds=None):
    """Free room for ``kinds``, every kind when None, and the units that free it."""
    wanted = (lambda kind: True) if kinds is None else kinds.__contains__
    free = {name: size - len(snapshot.pockets.get(name, ())) for name, size in POCKET_SLOTS.items() if wanted(name)}
    if wanted(BOX):
        free[BOX] = headroom(snapshot)
    if wanted(PARTY):
        free[PARTY] = PARTY_SIZE - len(snapshot.party)
    found = units(data, snapshot) if wanted('items') else ()
    return Resources(free, snapshot.money if wanted(MONEY) else 0, found)


def ledger(data):
    return Ledger(lambda snapshot, kinds: read(data, snapshot, kinds))
