"""The resource ledger's view of a Gold, Silver or Crystal snapshot.

Each pocket holds a fixed number of distinct entries, the boxes 20 Pokémon each and the party six.
An items-pocket entry no plan wants can be put in the PC to free its entry, worth its sale price for
the whole stack. Valuables are sold when money runs out, so they go last. An item a plan wants is
never offered.

Money is held back as reservations: Day Care fees with a margin for the walk back, and a cash reserve.
The shop restocks what ``supplies`` lists, keeping balls to catch with before the cash reserve, and a
run sells valuables and spare TMs only when it has no ball and no money for one.
"""
from ..planning.ledger import BOX, MONEY, PARTY, PRICELESS, Ledger, Need, Resources, Shortfall, Unit
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
# A spare in another box costs a box change first, which saves the game and takes about as long as a
# release. So a spare in the open box goes before a near equal one elsewhere.
BOX_CHANGE = 10


def moved(snapshot, mon):
    return 0 if mon.box == snapshot.active_box else BOX_CHANGE


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
    owners = policy.release_owners() if hasattr(policy, 'release_owners') else None
    plain = spares(snapshot, policy.demand, keep, preferences, partners, owners=owners)
    lenient = spares(snapshot, policy.demand, keep, preferences, partners, lenient=True, owners=owners)
    wanted = wanted_items(data)
    bag = dict(snapshot.pockets.get('items', ()))
    rows = []
    for rank, mon in enumerate(plain):
        if allowed(mon):
            rows.append(Unit(('mon', mon.box, mon.position), BOX, PLAIN + moved(snapshot, mon), 'release',
                             detail=mon, order=(0, rank)))
    plain = {(mon.box, mon.position) for mon in plain}
    for rank, mon in enumerate(lenient):
        if (mon.box, mon.position) in plain or not allowed(mon):
            continue
        key = ('mon', mon.box, mon.position)
        base = (TRAINED if sum(mon.stat_exp) >= TRAINED_STAT_EXP else PLAIN) + moved(snapshot, mon)
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


def catch_need(snapshot):
    """The room one catch takes: none while the party has a free slot, a box slot after that."""
    return Need() if len(snapshot.party) < PARTY_SIZE else Need(box_slots=1)


def catch_room(policy, snapshot, goal):
    """Whether a catch made for ``goal`` has somewhere to go: a free party or box slot, or a boxed spare
    the ledger can let go for one."""
    from ..planning.conditions import Requirements, feasible
    need = catch_need(snapshot)
    if not need.amounts():
        return True
    books = ledger(policy.data)
    books.snapshot(snapshot, kinds=(BOX,))
    return bool(feasible(Requirements(need=need), None, books, key=goal)
                or policy.storage_target(snapshot) is not None)


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


# Money the shop leaves alone. With Day Care fees owed, the fees and a margin for the walk back stay.
CASH_RESERVE = 400
DAYCARE_MARGIN = 1000
# Money a Day Care pairing needs before it starts.
BREEDING_FUNDS = 3000
# Restock levels. Balls refill below the floor, to a full stock for a legendary or a one-time encounter.
BALL_FLOOR = 4
BALL_REFILL, BALL_STOCK_REFILL = 20, 40
BALL_STOCK = 20
POTIONS = ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION')
POTION_LOW, POTION_FULL = 8, 12
REVIVE_LOW, REVIVE_FULL = 3, 5
# An ordinary catch keeps the last few balls while money cannot buy the floor back. Species met only
# once, such as Sudowoodo, Snorlax, the red Gyarados and the legendaries, always get a throw.
LAST_BALLS = 3
ONE_CHANCE = frozenset({130, 143, 185, 243, 244, 245, 249, 250, 251})
# One sale tier is worth this much more per money freed than the tier before it.
TIER = 10 ** 7


def price(data, name):
    return data.item_attributes[data.items[name]]['price']


def balls(snapshot):
    return sum(count for _, count in snapshot.pockets['balls'])


def money_needs(data, snapshot):
    """The standing money reservations: Day Care fees with their margin, and the cash reserve."""
    from pokecore.gen2.breeding import retrieval_cost
    fees = retrieval_cost(data, snapshot)
    needs = {}
    if fees:
        needs['daycare'] = Need(money=fees + DAYCARE_MARGIN - CASH_RESERVE)
    needs['cash'] = Need(money=CASH_RESERVE)
    return needs


def held_money(data, snapshot, goal=None):
    """Money the reservations hold from ``goal``. Balls to catch with come before the cash reserve."""
    needs = money_needs(data, snapshot)
    if goal == 'balls':
        needs.pop('cash')
    return sum(need.money for need in needs.values())


def money_books(data, snapshot, goal=None, sales=True):
    """Books for money alone, with the standing reservations held, and the bag's sales when ``sales``."""
    books = Ledger(lambda view, kinds: Resources({}, view.money, fund_units(data, view) if sales else ()))
    books.snapshot(snapshot)
    books.reservations['held'] = Need(money=held_money(data, snapshot, goal))
    return books


def fund_units(data, snapshot):
    """Bag entries that sell for money: valuables first, then TMs no plan teaches, cheapest to buy again."""
    from .champion_shop import RENEWABLE, tm_price
    from .tower import MACHINES
    valuables = [data.items[name] for name in VALUABLES if name in data.items]
    machines = {data.items[f'TM{number:02d}']: number for number in range(1, 51) if f'TM{number:02d}' in data.items}
    taught = {data.items[name] for _, name in MACHINES if name in data.items}
    rows = []
    for item, count in snapshot.items:
        sale = data.item_attributes.get(item, {}).get('price', 0) // 2 * count
        if sale <= 0:
            continue
        if item in valuables:
            value, order = 0, (valuables.index(item),)
        elif item in machines and item not in taught:
            tier = 1 if machines[item] in RENEWABLE else 2
            value, order = (tier * TIER + tm_price(data, item)) * sale, (item,)
        else:
            continue
        rows.append(Unit(('sell', item), MONEY, value, 'sell', sale, detail=(item, count), order=order))
    return tuple(rows)


def ball_sale(data, snapshot):
    """(item, count) to sell when the ball pocket is empty and money cannot buy one Poké Ball, else None."""
    books = money_books(data, snapshot, 'balls')
    answer = books.reserve('balls', Need(money=price(data, 'POKE_BALL')))
    if answer.ok:
        return None
    plan = books.make_room(answer)
    return plan[0].detail if plan else None


def ball_names(snapshot):
    return ('ULTRA_BALL', 'GREAT_BALL', 'POKE_BALL') if snapshot.badges & 64 else ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')


def supplies(policy, snapshot):
    """What the shop restocks, most needed first: (goal, item names by preference, units)."""
    from .quests import static_wanted
    data = policy.data
    collection = policy.collection
    unique = policy.goal is not None and policy.goal.key in {'sudowoodo', 'snorlax', 'collection_lapras'}
    stocking = collection.get('phase') == 'legendary' or unique
    # Roaming beasts and the other legendaries have catch rates of 3, so every throw counts: while one
    # is still wanted, an affordable Ultra Ball beats a nearer shop's Great Ball.
    legendary = snapshot.can_catch and bool(snapshot.badges & 64) and (unique
        or collection.get('phase') == 'legendary'
        and not {243, 244, 245, 249, 250} <= set(snapshot.owned) - policy.returned
        or static_wanted(policy, snapshot))
    rows = []
    ultras = dict(snapshot.pockets['balls']).get(data.items['ULTRA_BALL'], 0)
    if (legendary and ultras < BALL_STOCK
            and snapshot.money - held_money(data, snapshot) >= price(data, 'ULTRA_BALL') * min(5, BALL_STOCK - ultras)):
        rows.append(('ultras', ('ULTRA_BALL',), BALL_STOCK - ultras))
    # Any ball still beats none when no Ultra Ball counter can be reached.
    if balls(snapshot) < (BALL_STOCK if stocking else BALL_FLOOR) and snapshot.can_catch:
        rows.append(('balls', ball_names(snapshot), BALL_STOCK_REFILL if stocking else BALL_REFILL))
    if snapshot.badges & 64 and 'red' not in policy.completed and (not snapshot.hall_of_fame_count
                                                                   or snapshot.badges == 65535):
        inventory = dict(snapshot.items)
        count = sum(inventory.get(data.items[name], 0) for name in POTIONS)
        if count < POTION_LOW:
            rows.append(('potions', POTIONS, POTION_FULL - count))
        revives = inventory.get(data.items['REVIVE'], 0)
        if revives < REVIVE_LOW:
            rows.append(('revives', ('REVIVE',), REVIVE_FULL - revives))
    return rows


def spare_throw(data, snapshot, species):
    """Whether an ordinary catch may throw a ball: a one-time encounter, more than the last few balls,
    or money past the reservations to buy the floor back."""
    if species in ONE_CHANCE or balls(snapshot) > LAST_BALLS:
        return True
    books = money_books(data, snapshot, sales=False)
    return books.reserve('throw', Need(money=price(data, 'POKE_BALL') * BALL_FLOOR)).ok


def funding_short(policy, snapshot):
    """The money need a League run pays for, or None: the Day Care fees with their margin, or a ball
    floor in the shop's best ball."""
    data = policy.data
    needs = money_needs(data, snapshot)
    if 'daycare' in needs and snapshot.money < held_money(data, snapshot):
        return 'daycare'
    if balls(snapshot) >= BALL_FLOOR:
        return None
    best = ball_names(snapshot)[0]
    return 'balls' if snapshot.money < held_money(data, snapshot, 'balls') + price(data, best) * BALL_FLOOR else None


def red_short(policy, snapshot):
    """Whether the potions run low before Red and the money past the reservations cannot restock them."""
    data = policy.data
    inventory = dict(snapshot.items)
    count = sum(inventory.get(data.items[name], 0) for name in POTIONS)
    return (count < POTION_LOW
            and snapshot.money < held_money(data, snapshot) + price(data, POTIONS[-1]) * (POTION_FULL - count))
