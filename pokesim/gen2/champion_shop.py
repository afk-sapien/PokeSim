"""Limited TMs and Champion supplies at the Goldenrod Dept. Store.

The Gen II port of the Red, Blue and Yellow TM shop and Champion shop. Like Gen I, it opens to every
Champion and does not wait for the "Extra store items" setting. After the Hall of Fame,
the 5F TM clerks also sell the one-time TMs a partner would learn for a real gain, and the 4F
clerk sells Champion supplies. Prices and the walking caps match Gen I: a Master Ball or five Rare
Candies once per 1,000,000 steps each, and the policy keeps ₽20,000 for ordinary supplies.

Only the one item the policy plans to buy is added to the clerk's BUY list, through the same
StoreStock hooks as the extra evolution items, so the purchase runs the cartridge's own menus and
TakeMoney. The cartridge is never changed. A TM is taught at once, Rare Candies are used on the
partner they were bought for, Leftovers or a Lucky Egg is given to a partner with empty hands, and
Elixirs restore moves out of PP in the Pokémon League.

PP Up is priced but not planned yet: Core does not recognise the Gen II "raise PP of which move"
list, so the item could not be used after buying it.
"""
from ..planning.ledger import FIELD_MOVES
from .standdown import stand_down, standing_down

KEY = 'gen2-champion-shop-v1'
PLAN = 'champion_shop'
INTERVAL = 1_000_000
RESERVE = 20000
MIN_LEVEL = 50
# Cartridge marts (Goldenrod 5F and Celadon 3F) and Game Corner prizes sell these again and again.
RENEWABLE = frozenset({2, 8, 10, 11, 17, 18, 33, 37, 41, 48, 14, 15, 25, 29, 32, 38})
LIMITED_NUMBERS = tuple(number for number in range(1, 51) if number not in RENEWABLE)
PREMIUM = frozenset({1, 6, 7, 26, 27, 30, 36})
STANDARD = frozenset({3, 16, 19, 22, 23, 24, 28, 35, 42, 44, 47})
# Price of one offer. A capped offer holds several items: the clerk charges price // quantity each.
SUPPLIES = {'PP_UP': 25000, 'RARE_CANDY': 25000, 'MASTER_BALL': 100000, 'ELIXER': 5000,
            'MAX_ELIXER': 10000, 'LEFTOVERS': 25000, 'LUCKY_EGG': 25000}
OFFERS = {'MASTER_BALL': 1, 'RARE_CANDY': 5}
NAMES = {'PP_UP': 'PP Up', 'RARE_CANDY': 'Rare Candy', 'MASTER_BALL': 'Master Ball', 'ELIXER': 'Elixir',
         'MAX_ELIXER': 'Max Elixir', 'LEFTOVERS': 'Leftovers', 'LUCKY_EGG': 'Lucky Egg'}
HELD = ('LEFTOVERS', 'LUCKY_EGG')
# Capped walking offers come first, as in Gen I. PP Up waits for Core to drive the Gen II move list.
ORDER = ('MASTER_BALL', 'RARE_CANDY', 'LEFTOVERS', 'LUCKY_EGG', 'MAX_ELIXER', 'ELIXER')
TM_MARTS = tuple(f'MART_GOLDENROD_5F_{index}' for index in range(1, 5))
SUPPLY_MART = 'MART_GOLDENROD_4F'
# Pocket slots, leaving one for story items and pickups as in Gen I.
POCKET_ROOM = {'ITEM': 19, 'BALL': 11}
CHECK_DECISIONS = 2000
PLAN_DECISIONS = 8000
PLAN_TRIES = 3


def champion(snapshot):
    return bool(getattr(snapshot, 'hall_of_fame_count', 0))


def limited_tms(data):
    """{TM item id: move id} for the one-time TMs."""
    cached = getattr(data, '_champion_tms', None)
    if cached is None:
        moves = {move['constant']: mid for mid, move in data.moves.items()}
        names = {item: name for name, item in data.items.items() if name.startswith('TM_')}
        cached = {}
        for number in LIMITED_NUMBERS:
            item = data.items[f'TM{number:02d}']
            cached[item] = moves[names[item][3:]]
        try:
            data._champion_tms = cached
        except AttributeError:
            pass
    return cached


def tm_number(data, item):
    return next(number for number in range(1, 51) if data.items[f'TM{number:02d}'] == item)


def tm_price(data, item):
    number = tm_number(data, item)
    return 50000 if number in PREMIUM else 25000 if number in STANDARD else 10000


def supply_name(data, item):
    return next((name for name in SUPPLIES if data.items.get(name) == item), None)


def offer_price(data, item):
    """What one planned purchase costs in total, or None for an item outside the catalogue."""
    name = supply_name(data, item)
    if name:
        return SUPPLIES[name]
    return tm_price(data, item) if item in limited_tms(data) else None


def quantity(data, item):
    return OFFERS.get(supply_name(data, item), 1)


def unit_price(data, item):
    total = offer_price(data, item)
    return None if total is None else total // quantity(data, item)


def label(data, item):
    name = supply_name(data, item)
    if name:
        return NAMES[name]
    move = data.moves[limited_tms(data)[item]]['name']
    return f'TM{tm_number(data, item):02d} {move}'


# Walking offers -------------------------------------------------------------------------------

def observe(store, snapshot, walking):
    """Start the walking countdowns the first time the run is seen as Champion."""
    if (snapshot.valid and snapshot.started and champion(snapshot)
            and walking.get('available') and store.get(KEY) is None):
        store.set(KEY, {name: {'next_at': walking['total'] + INTERVAL, 'purchased': 0} for name in OFFERS})


def status(store, data, walking=None):
    """The Champion shop panel on the item statistics page."""
    from .steps import STEPS
    value = store.get(KEY) or {}
    walking = walking or store.get(STEPS) or {}
    total = walking.get('total', 0)
    return {'started': bool(value), 'available': bool(walking.get('available')), 'interval': INTERVAL,
            'counter': 'Goldenrod Dept. Store: one-time TMs on 5F, supplies on 4F',
            'offers': [{'item': data.items[name], 'name': NAMES[name], 'quantity': count, 'price': SUPPLIES[name],
                        'remaining': max(0, value.get(name, {}).get('next_at', total + INTERVAL) - total),
                        'purchased': value.get(name, {}).get('purchased', 0)}
                       for name, count in OFFERS.items()]}


def ready(store, data, walking=None):
    """Item ids of capped offers that can be bought now."""
    value = status(store, data, walking)
    if not value or not value['started'] or not value['available']:
        return set()
    return {row['item'] for row in value['offers'] if not row['remaining']}


def consume(store, data, item, walking):
    """Renew a capped offer after its purchase landed. Returns False for an uncapped item."""
    name = supply_name(data, item)
    value = store.get(KEY)
    if name not in OFFERS or not value or name not in value:
        return False
    value[name].update(next_at=walking['total'] + INTERVAL, purchased=value[name]['purchased'] + 1)
    store.set(KEY, value)
    return True


def catalogue(data, plan, offers):
    """{mart constant: {item: unit price}} the clerks add for the current plan."""
    if not plan or plan.get('bought'):
        return {}
    item = plan['item']
    if supply_name(data, item) in OFFERS and item not in offers:
        return {}
    price = unit_price(data, item)
    if price is None:
        return {}
    marts = TM_MARTS if item in limited_tms(data) else (SUPPLY_MART,)
    return {mart: {item: price} for mart in marts}


# Choosing what to buy ---------------------------------------------------------------------------

def signature(mon):
    return [mon.species, mon.trainer_id, list(mon.dvs), mon.nick]


def _power(data, mon, moves, level=None):
    from pokecore.gen2.battle_power import battle_power
    return battle_power({'species': mon.species, 'level': level or mon.level, 'dvs': mon.dvs,
                         'stat_exp': (65535,) * 5 if level else mon.stat_exp, 'moves': list(moves),
                         'friendship': mon.friendship}, data)


def upgrade(data, mon, item):
    """The move a TM replaces and the Battle Power it adds at level 100, or None for no real gain."""
    move = limited_tms(data).get(item)
    if (move is None or mon.egg or mon.level < MIN_LEVEL or mon.hp <= 0 or mon.status
            or move in mon.moves or move not in data.species[mon.species]['machines']):
        return None
    # Save the one copy when this partner will learn the same move by level.
    if any(level > mon.level and learned == move for level, learned in data.species[mon.species]['learnset']):
        return None
    current = _power(data, mon, mon.moves)
    before = _power(data, mon, mon.moves, 100)
    if current is None or before is None:
        return None
    best = None
    for slot, old in enumerate(list(mon.moves) + [0] * (4 - len(mon.moves))):
        if old in FIELD_MOVES:
            continue
        changed = [move if index == slot else known for index, known in
                   enumerate(list(mon.moves) + [0] * (4 - len(mon.moves)))]
        changed = [known for known in changed if known]
        after = _power(data, mon, changed, 100)
        now = _power(data, mon, changed)
        # The partner must improve now and at level 100.
        if after is None or now is None or now <= current:
            continue
        if best is None or after > best[0]:
            best = (after, old)
    if best is None or best[0] - before <= max(1, before * 0.08):
        return None
    return {'gain': best[0] - before, 'replace': best[1] or None}


def best_tm(data, snapshot, *, owned):
    """Plan the largest level 100 Battle Power gain from a limited TM, bought or already owned."""
    if not champion(snapshot):
        return None
    bag = dict(snapshot.items)
    options = []
    for item in sorted(limited_tms(data)):
        if bool(bag.get(item)) != owned:
            continue
        if not owned and snapshot.money < tm_price(data, item) + RESERVE:
            continue
        for index, mon in enumerate(snapshot.party):
            change = upgrade(data, mon, item)
            if change is not None:
                options.append((change['gain'], -tm_price(data, item), -index, -item, change['replace']))
    if not options:
        return None
    _, _, index, item, replace = max(options)
    mon = snapshot.party[-index]
    return {'item': -item, 'target': -index, 'signature': signature(mon), 'replace': replace, 'quantity': 1}


def pp_slot(data, mon):
    """The strong, low-PP move a PP Up helps most, or None."""
    options = []
    for slot, mid in enumerate(mon.moves):
        move = data.moves.get(mid, {})
        base = move.get('pp', 0)
        maximum = mon.max_pp[slot] if slot < len(mon.max_pp) else 0
        if (mon.level >= 60 and mon.hp > 0 and not mon.status and 0 < base <= 20
                and move.get('power', 0) >= 60 and move.get('effect') not in ('EFFECT_SELFDESTRUCT', 'EFFECT_OHKO')
                and base <= maximum < base + 3 * (base // 5)):
            options.append((move['power'], -base, -slot))
    return -max(options)[2] if options else None


def owned_anywhere(data, snapshot, item):
    return (dict(snapshot.items).get(item, 0) > 0
            or any(getattr(mon, 'held_item', 0) == item for mon in (*snapshot.party, *snapshot.stored)))


def recipient(data, snapshot, name):
    """The party slot a supply is for, or None when no partner needs it."""
    party = [(index, mon) for index, mon in enumerate(snapshot.party) if not mon.egg]
    if name == 'PP_UP':
        candidates = [index for index, mon in party if pp_slot(data, mon) is not None]
    elif name == 'RARE_CANDY':
        candidates = [index for index, mon in party if 30 <= mon.level < 100 and mon.hp > 0]
    elif name in HELD:
        if owned_anywhere(data, snapshot, data.items[name]):
            return None
        candidates = [index for index, mon in party if not mon.held_item and mon.level >= MIN_LEVEL
                      and (name == 'LEFTOVERS' or mon.level < 100)]
        if name == 'LUCKY_EGG':
            # The egg helps a partner still growing most, so the lowest level gets it.
            return min(candidates, key=lambda index: snapshot.party[index].level) if candidates else None
    else:
        candidates = [index for index, mon in party if mon.level >= 35 and mon.hp > 0]
    return max(candidates, key=lambda index: snapshot.party[index].level) if candidates else None


def room(data, snapshot, item):
    if item in limited_tms(data):
        return True
    pocket = data.item_attributes[item]['pocket']
    return len(snapshot.pockets.get('balls' if pocket == 'BALL' else 'items', ())) < POCKET_ROOM.get(pocket, 19)


def best_supply(data, snapshot, offers):
    if not champion(snapshot):
        return None
    for name in ORDER:
        item = data.items[name]
        target = recipient(data, snapshot, name)
        if target is None:
            continue
        plan = {'item': item, 'target': target, 'signature': signature(snapshot.party[target]),
                'replace': None, 'quantity': OFFERS.get(name, 1), 'supply': True}
        if valid_plan(data, snapshot, plan, offers):
            return plan
    return None


def valid_plan(data, snapshot, plan, offers):
    """Whether a purchase plan still makes sense before the item is bought."""
    item, target = plan['item'], plan['target']
    price = offer_price(data, item)
    if (price is None or not champion(snapshot) or not 0 <= target < len(snapshot.party)
            or signature(snapshot.party[target]) != plan['signature']):
        return False
    mon = snapshot.party[target]
    name = supply_name(data, item)
    if name is None:
        if upgrade(data, mon, item) is None:
            return False
    elif name in OFFERS and item not in offers:
        return False
    elif name == 'PP_UP' and pp_slot(data, mon) is None:
        return False
    elif name == 'RARE_CANDY' and not 30 <= mon.level < 100:
        return False
    elif recipient(data, snapshot, name) is None:
        return False
    return (not dict(snapshot.items).get(item) and room(data, snapshot, item)
            and snapshot.money >= price + RESERVE and plan.get('quantity') == quantity(data, item))


def choose(data, snapshot, offers):
    return best_tm(data, snapshot, owned=False) or best_supply(data, snapshot, offers)


# The errand -------------------------------------------------------------------------------------

def plan_key(item):
    return f'champion_shop:{item}'


def _shop(data, mart):
    for entry in data.maps.values():
        for shop in entry['shops']:
            if shop['mart'] == mart:
                return entry, shop
    return None, None


def journey(policy, snapshot, Goal):
    """Walk to the Goldenrod clerk who sells the planned TM or supply."""
    state = policy.collection
    if not champion(snapshot):
        state.pop(PLAN, None)
        return None
    data = policy.data
    offers = getattr(policy, 'shop_offers', None) or set()
    plan = state.get(PLAN)
    if plan and not plan.get('bought'):
        if dict(snapshot.items).get(plan['item'], 0) > plan.get('initial', 0):
            plan['bought'] = True
        elif (policy.decisions - plan['started'] > PLAN_DECISIONS
              or not valid_plan(data, snapshot, plan, offers)):
            if policy.decisions - plan['started'] > PLAN_DECISIONS:
                stand_down(policy, plan_key(plan['item']))
            state.pop(PLAN, None)
            state['champion_check'] = policy.decisions + CHECK_DECISIONS
            plan = None
    if plan and plan.get('bought'):
        return None
    if plan is None:
        if policy.decisions < state.get('champion_check', 0):
            return None
        state['champion_check'] = policy.decisions + CHECK_DECISIONS
        plan = choose(data, snapshot, offers)
        if plan is None or standing_down(policy, plan_key(plan['item'])):
            return None
        plan.update(started=policy.decisions, tries=0, initial=dict(snapshot.items).get(plan['item'], 0))
        state[PLAN] = plan
    marts = TM_MARTS if plan['item'] in limited_tms(data) else (SUPPLY_MART,)
    for mart in marts:
        entry, shop = _shop(data, mart)
        if entry is not None and policy.clerk_present(snapshot, entry, shop):
            count = plan['quantity']
            name = label(data, plan['item'])
            text = f'Buy {f"{count} × " if count > 1 else ""}{name} at the department store'
            return policy.person(snapshot, 'collection_champion_shop', text, entry['constant'], shop['script'])
    return None


def arrive(policy, snapshot):
    if policy.goal.key != 'collection_champion_shop':
        return None
    plan = policy.collection.get(PLAN)
    if not plan or plan.get('bought'):
        return 'b'
    plan['tries'] += 1
    if plan['tries'] > PLAN_TRIES:
        # The clerk was reached but the purchase never landed: stop instead of talking forever.
        stand_down(policy, plan_key(plan['item']))
        policy.collection.pop(PLAN, None)
        return 'b'
    from .menus import Buy
    policy.menu = Buy(plan['item'], plan['quantity'], dict(snapshot.items).get(plan['item'], 0))
    return 'wait'


def use(policy, snapshot):
    """The menu task that puts a bought or owned item to use, or None."""
    if not champion(snapshot) or snapshot.in_battle:
        return None
    from .menus import Give, Teach, UseOn
    data, state = policy.data, policy.collection
    bag = dict(snapshot.items)
    # Battle Power is costly, so nothing is recomputed while the bag and team stay the same.
    key = (tuple(snapshot.items), state.get(PLAN, {}).get('bought'),
           tuple((mon.species, mon.level, tuple(mon.moves), mon.held_item, mon.hp > 0, mon.status, mon.egg)
                 for mon in snapshot.party))
    if getattr(policy, '_champion_idle', None) == key:
        return None
    task = _use(policy, snapshot, data, state, bag, Give, Teach, UseOn)
    policy._champion_idle = None if task is not None else key
    return task


def _use(policy, snapshot, data, state, bag, Give, Teach, UseOn):
    owned = best_tm(data, snapshot, owned=True)
    if owned:
        return Teach(limited_tms(data)[owned['item']], owned['target'], replace_move=owned['replace'])
    plan = state.get(PLAN)
    if plan and plan.get('bought') and not bag.get(plan['item']):
        state.pop(PLAN, None)
        plan = None
    candy = data.items['RARE_CANDY']
    if bag.get(candy) and plan and plan.get('bought') and plan['item'] == candy:
        target = next((index for index, mon in enumerate(snapshot.party) if signature(mon) == plan['signature']
                       and 30 <= mon.level < 100 and mon.hp > 0), None)
        if target is None:
            target = recipient(data, snapshot, 'RARE_CANDY')
        if target is not None:
            return UseOn(candy, target, bag[candy])
        state.pop(PLAN, None)
    if plan and plan.get('bought'):
        name = supply_name(data, plan['item'])
        if name in HELD:
            slot = next((index for index, mon in enumerate(snapshot.party)
                         if signature(mon) == plan['signature'] and not mon.held_item), None)
            if slot is None:
                slot = recipient_for_held(data, snapshot, name)
            state.pop(PLAN, None)
            return Give(plan['item'], slot) if slot is not None else None
        if name is not None and name != 'RARE_CANDY':
            # Balls and Elixirs stay in the bag for later use.
            state.pop(PLAN, None)
    return None


def recipient_for_held(data, snapshot, name):
    party = [(index, mon) for index, mon in enumerate(snapshot.party) if not mon.egg and not mon.held_item]
    if not party:
        return None
    pick = min if name == 'LUCKY_EGG' else max
    return pick(party, key=lambda pair: pair[1].level)[0]


def elixir(data, snapshot, mon):
    """The Max Elixir or Elixir that restores a partner whose attacking move ran out of PP, or None."""
    if mon.egg or mon.hp <= 0 or not any(move and not pp and data.moves.get(move, {}).get('power')
                                         for move, pp in zip(mon.moves, mon.pp)):
        return None
    bag = dict(snapshot.items)
    return next((data.items[name] for name in ('MAX_ELIXER', 'ELIXER') if bag.get(data.items[name])), None)
