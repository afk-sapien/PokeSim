"""The resource ledger's view of a Gold, Silver or Crystal snapshot.

Each pocket holds a fixed number of distinct entries, the boxes 20 Pokémon each and the party six.
An items-pocket entry no plan wants can be put in the PC to free its entry, worth its sale price for
the whole stack. Valuables are sold when money runs out, so they go last. An item a plan wants is
never offered.
"""
from ..planning.ledger import BOX, PARTY, PRICELESS, Ledger, Need, Resources, Shortfall, Unit
from .champion_shop import SUPPLIES
from .menus import Release
from .release import headroom

# Distinct entries each Gen 2 pocket holds.
POCKET_SLOTS = {'items': 20, 'balls': 12}
PARTY_SIZE = 6
STACK = 99
# Items each plan uses from the bag. Evolution items are added from the species data.
WANTS = {
    'training': ('EXP_SHARE', 'EVERSTONE'),
    'battle': ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION', 'SUPER_POTION', 'POTION', 'MAX_REVIVE', 'REVIVE',
               'FULL_HEAL', 'ANTIDOTE', 'AWAKENING', 'PARLYZ_HEAL', 'BURN_HEAL', 'ICE_HEAL'),
    'champion shop': tuple(SUPPLIES),
    'battle tower': ('PRZCUREBERRY', 'LEFTOVERS'),
}
# Sold for money when the wallet runs dry, so they leave the bag last.
VALUABLES = ('NUGGET', 'PEARL', 'BIG_PEARL', 'STARDUST', 'STAR_PIECE')
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


def wanted_items(data):
    """Items some plan uses from the bag, with every evolution item the species data names."""
    wanted = {data.items[name] for names in WANTS.values() for name in names if name in data.items}
    wanted |= {data.items[req] for entry in data.species.values() for evo in entry['evolutions']
               if evo['method'] in ('item', 'trade') for req in evo['requirements'] if req in data.items}
    return wanted


def units(data, snapshot):
    wanted = wanted_items(data)
    valuables = {data.items[name] for name in VALUABLES if name in data.items}
    rows = []
    for item, count in snapshot.pockets.get('items', ()):
        attributes = data.item_attributes.get(item, {})
        if item in wanted or attributes.get('pocket') != 'ITEM':
            value = PRICELESS
        else:
            value = attributes['price'] * count + (VALUABLE if item in valuables else 0)
        rows.append(Unit(('item', item), 'items', value, 'deposit', detail=item, order=(item,)))
    return tuple(rows)


def read(data, snapshot, kinds=None, boxes=None):
    """Free room of every kind, and the units that free ``kinds``, every kind when None.

    ``boxes`` lists the box units for a snapshot, since ranking boxed Pokémon needs the policy's plans.
    """
    wanted = (lambda kind: True) if kinds is None else kinds.__contains__
    free = {name: size - len(snapshot.pockets.get(name, ())) for name, size in POCKET_SLOTS.items()}
    free[BOX] = headroom(snapshot)
    free[PARTY] = PARTY_SIZE - len(snapshot.party)
    found = units(data, snapshot) if wanted('items') else ()
    if boxes is not None and wanted(BOX):
        found += tuple(boxes(snapshot))
    return Resources(free, snapshot.money, found)


def ledger(data, boxes=None):
    return Ledger(lambda snapshot, kinds: read(data, snapshot, kinds, boxes))


# Worth of a boxed spare: a plain duplicate, a trained one, and more for one holding an item. Training
# took many battles, so it weighs more than any cheap item. An item held by a released spare is lost
# with it, so its price counts too, halved when the bag holds more of it.
PLAIN, TRAINED, HELD = 1, 50, 10


def member(mon):
    return [mon.species, mon.trainer_id, list(mon.dvs)]


def box_units(policy, snapshot, allowed=lambda mon: True):
    """Boxed spares that could go to free a slot, worth least first.

    A plain spare goes as it is. A spare holding an item no plan wants may go with its item, worth the
    item's price as well. Any held spare may also have its item taken off first, which keeps the item
    but needs a free party slot and a bag entry, so it is chosen only when both are free. A spare
    holding an item some plan wants goes only that way.
    """
    from pokecore.gen2.breeding import breeding_stock
    from .release import TRAINED_STAT_EXP, plan_partners, spares
    from .standdown import standing_down
    data = policy.data
    keep = breeding_stock(data, [mon.species for mon in snapshot.party + snapshot.stored if not mon.egg])
    partners = plan_partners(policy.collection)
    preferences = policy.trade_preferences()
    plain = spares(snapshot, policy.demand, keep, preferences, partners)
    lenient = spares(snapshot, policy.demand, keep, preferences, partners, lenient=True)
    wanted = wanted_items(data)
    bag = dict(snapshot.pockets.get('items', ()))
    rows = []
    for rank, mon in enumerate(plain):
        if allowed(mon):
            rows.append(Unit(('mon', mon.box, mon.position), BOX, PLAIN, 'release', detail=mon, order=(0, rank)))
    plain = {(mon.box, mon.position) for mon in plain}
    for rank, mon in enumerate(lenient):
        if (mon.box, mon.position) in plain or not allowed(mon):
            continue
        key = ('mon', mon.box, mon.position)
        base = TRAINED if sum(mon.stat_exp) >= TRAINED_STAT_EXP else PLAIN
        if not mon.held_item:
            rows.append(Unit(key, BOX, base, 'release', detail=mon, order=(1, rank)))
            continue
        price = data.item_attributes.get(mon.held_item, {}).get('price', 0)
        if mon.held_item not in wanted:
            lost = price // 2 if bag.get(mon.held_item) else price
            rows.append(Unit(key, BOX, HELD + base + lost, 'release', detail=mon, order=(1, rank)))
        if standing_down(policy, unequip_key(mon)):
            continue
        need = needs(data, snapshot, mon.held_item)
        rows.append(Unit(key, BOX, HELD + base, 'unequip', needs=Need(pocket_slots=need.pocket_slots, party_slots=1),
                         detail=mon, order=(1, rank)))
    return rows


def unequip_key(mon):
    return 'unequip:' + str(member(mon))


def unequip_step(policy, snapshot):
    """The next PC step for a spare whose item comes off before it goes, or None when none is under way.

    The spare is withdrawn, its item taken into the bag, and it goes back to the box it left, which
    has the slot it freed. Then it is released from there. A step the game refuses stands the spare
    down for a while, so another unit goes first. A spare already withdrawn goes back to the box with
    its item, so it does not stay in the party.
    """
    from .menus import ChangeBox, Storage, Take
    from .standdown import stand_down
    state = policy.collection
    wanted = state.get('unequip')
    if not wanted:
        return None
    mon = next((row for row in snapshot.party + snapshot.stored if member(row) == wanted), None)
    returning = state.get('unequip_return')
    if mon is None or returning and mon.box is not None:
        # Released, so the slot is free, or put back after a refused step.
        state.pop('unequip', None)
        state.pop('unequip_return', None)
        return None
    if returning:
        task = Storage('DEPOSIT', snapshot.party.index(mon), len(snapshot.party))
    elif mon.box is not None and mon.box != snapshot.active_box:
        task = ChangeBox(mon.box)
    elif mon.box is not None and mon.held_item:
        if len(snapshot.party) >= PARTY_SIZE:
            state.pop('unequip', None)
            return None
        task = Storage('WITHDRAW', mon.position, len(snapshot.party))
    elif mon.box is None and mon.held_item:
        task = Take(snapshot.party.index(mon), wanted[1:])
    elif mon.box is None:
        task = Storage('DEPOSIT', snapshot.party.index(mon), len(snapshot.party))
    else:
        task = Release(mon.box, mon.position, wanted)
    if not policy.allowed(task, snapshot):
        stand_down(policy, unequip_key(mon))
        if mon.box is None and not returning:
            state['unequip_return'] = True
            return unequip_step(policy, snapshot)
        state.pop('unequip', None)
        state.pop('unequip_return', None)
        return None
    policy.menu = task
    return 'a'


def release_step(policy, snapshot):
    """The next PC step of a release visit, or 'wait' when it has nothing more to do.

    A spare whose item is coming off finishes first. After that the visit ends at the refill mark,
    so it does not start another spare. Starting one each time an unequip ended kept a Crystal visit
    releasing for 250,000 frames, to 34 free slots.
    """
    from ..planning.ledger import box_wanted
    from .menus import ChangeBox
    step = unequip_step(policy, snapshot)
    if step is not None:
        return step
    if not box_wanted(headroom(snapshot), True):
        return 'wait'
    unit = policy.storage_target(snapshot)
    if unit is None:
        return 'wait'
    mon = unit.detail
    if unit.action == 'unequip':
        policy.collection['unequip'] = member(mon)
        return unequip_step(policy, snapshot) or 'wait'
    policy.menu = (ChangeBox(mon.box) if mon.box != snapshot.active_box
                   else Release(mon.box, mon.position, member(mon)))
    return 'a'


def storage_unit(policy, snapshot, direct=False):
    """The boxed spare to let go for one more box slot, or None.

    ``direct`` keeps to spares that can go straight from the box, for callers that release at once.
    """
    allowed = lambda mon: policy.allowed(Release(mon.box, mon.position), snapshot)  # noqa: E731
    books = ledger(policy.data, boxes=lambda view: box_units(policy, view, allowed))
    resources = books.snapshot(snapshot, kinds=(BOX,))
    if direct:
        resources = Resources(resources.free, resources.money,
                              tuple(unit for unit in resources.units if unit.action == 'release'))
    plan = books.make_room(Shortfall('storage', {BOX: 1}), resources)
    return plan[-1] if plan else None


def room(data, snapshot, goal, item):
    """The bag entries to put away before ``item`` fits: [] when it fits, None when nothing can go."""
    need = needs(data, snapshot, item)
    books = ledger(data)
    books.snapshot(snapshot, kinds=tuple(need.pocket_slots))
    answer = books.reserve(goal, need)
    if answer.ok:
        return []
    return books.make_room(answer) or None


def fits(data, snapshot, item):
    return room(data, snapshot, 'fits', item) == []


def tidy_goal(policy, snapshot, Goal, item):
    """Walk to the PC to put a spare entry away when the bag has no entry for ``item``, or None."""
    data = policy.data
    plan = room(data, snapshot, 'collection_tidy', item)
    if not plan:
        return None
    spare = plan[0].detail
    policy.collection['tidy_item'] = spare
    goal = policy.storage_goal(snapshot)
    return Goal('collection_tidy', f'Store {data.item_names.get(spare, "a spare item")} in the PC to make room', goal.map_name, goal.x, goal.y, goal.face)
