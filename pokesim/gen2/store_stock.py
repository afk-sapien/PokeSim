"""Extra Goldenrod Dept. Store stock, the "Extra store items" adventure setting.

Gold and Silver have one Leaf, Fire, Water and Thunder Stone each (from Bill's grandfather) and
one King's Rock, Metal Coat, Dragon Scale and Up-Grade. With the setting on, the store sells them,
so a spent one-time item no longer blocks a Pokédex entry.

The cartridge is never changed. When a clerk opens the BUY list, StandardMart.Buy has just run
FarReadMart, which copies the ROM list into wCurMartCount and wCurMartItems and writes each
price as 3 BCD bytes from wMartItem1BCD on (pret pokegold and pokecrystal, engine/items/mart.asm).
A hook at BuyMenu appends the extra items to that RAM copy and its prices. The prices sit in a
WRAM union with the 70 byte wBufferMon, so 14 items (42 bytes) fit, and wCurMartItems holds 14
items and the end marker. SelectQuantityToBuy takes the charged price from GetItemPrice in D and
E, so a second hook right after that call charges the store price for an extra item.

The 4F clerk (vitamins) sells the six stones and the 3F clerk (battle items) the four held items.
Stones cost 2100 as in Celadon. The held items keep the cartridge's own item price (King's Rock and
Metal Coat 100, Dragon Scale and Up-Grade 2100).

The policy buys one only for a missing, prerequisite or peer-requested species, and only when no
legitimate source is left: the bag, an unused one-time item the policy collects, a Crystal phone
trainer, or a peer that offers the species for trade.
"""
from collections import Counter

from .. import config
from .standdown import stand_down, standing_down

STONES = ('LEAF_STONE', 'FIRE_STONE', 'WATER_STONE', 'THUNDERSTONE', 'MOON_STONE', 'SUN_STONE')
HELD = ('KINGS_ROCK', 'METAL_COAT', 'DRAGON_SCALE', 'UP_GRADE')
# Mart constant, ROM label, extra items.
MARTS = (('MART_GOLDENROD_4F', 'MartGoldenrod4F', STONES), ('MART_GOLDENROD_3F', 'MartGoldenrod3F', HELD))
STONE_PRICE = 2100
MART_ITEMS = 14
# A purchase that has not landed after this many visits or decisions stands down.
STORE_TRIES = 3
STORE_DECISIONS = 8000
# One-time items the policy itself collects (quests.stones and quests.trade_items).
GRANDPA = {'LEAF_STONE': 43, 'WATER_STONE': 120, 'THUNDERSTONE': 172}
ONE_TIME = {'MOON_STONE': 'EVENT_TOHJO_FALLS_MOON_STONE', 'UP_GRADE': 'EVENT_GOT_UP_GRADE',
            'KINGS_ROCK': 'EVENT_GOT_KINGS_ROCK_IN_SLOWPOKE_WELL',
            'DRAGON_SCALE': 'EVENT_MOUNT_MORTAR_2F_INSIDE_DRAGON_SCALE'}


def enabled():
    return bool(getattr(config, 'EXTRA_STORE_ITEMS', False))


def price(data, item):
    """What the store charges for an item, extra or not."""
    names = getattr(data, 'items', {})
    if item in {names.get(name) for name in STONES}:
        return STONE_PRICE
    return data.item_attributes[item]['price']


def extras(data, mart):
    """Extra item ids a mart constant sells while the setting is on."""
    if not enabled():
        return []
    for constant, _, names in MARTS:
        if constant == mart:
            return [data.items[name] for name in names]
    return []


def stock(data, shop):
    """The items a shop entry sells: its cartridge list, then any extra items."""
    items = list(shop['items'])
    return (items + [item for item in extras(data, shop['mart']) if item not in items])[:MART_ITEMS]


def bcd(value):
    digits = f'{value:06d}'
    return [int(digits[i]) << 4 | int(digits[i + 1]) for i in range(0, 6, 2)]


class StoreStock:
    """Emulator hooks that add the extra items to an opened BUY list and charge their price."""

    def __init__(self, data):
        self.data = data
        self.marts = {}
        for constant, label, _ in MARTS:
            if label in data.symbols:
                self.marts[tuple(data.symbols[label])] = constant
        self.extra_prices = {data.items[name]: STONE_PRICE for name in STONES}

    def attach(self, pb):
        symbols = self.data.symbols
        if not self.marts or 'BuyMenu' not in symbols or 'SelectQuantityToBuy' not in symbols:
            return False
        bank, address = symbols['SelectQuantityToBuy']
        # farcall GetItemPrice (ld a, BANK / ld hl, addr / rst FarCall), then ld a, d.
        code = bytes(pb.memory[bank, address:address + 7])
        if code[0] != 0x3E or code[2] != 0x21 or code[5] != 0xCF or code[6] != 0x7A:
            raise ValueError('The Gen II buy price instruction signature does not match the cartridge')
        pb.hook_register(*symbols['BuyMenu'], self.opened, pb)
        pb.hook_register(bank, address + 6, self.priced, pb)
        return True

    def _read(self, pb, name, size=1, offset=0):
        bank, address = self.data.symbols[name]
        return bytes(pb.memory[bank, address + offset:address + offset + size])

    def _write(self, pb, name, values, offset=0):
        bank, address = self.data.symbols[name]
        pb.memory[bank, address + offset:address + offset + len(values)] = list(values)

    def mart(self, pb):
        """The mart constant of the list being bought from, or None for any other list."""
        pointer = self._read(pb, 'wMartPointer', 2)
        key = (self._read(pb, 'wMartPointerBank')[0], pointer[0] | pointer[1] << 8)
        return self.marts.get(key)

    def opened(self, pb):
        if not enabled():
            return
        mart = self.mart(pb)
        if mart is None:
            return
        shop = next((shop for entry in self.data.maps.values() for shop in entry['shops'] if shop['mart'] == mart), None)
        count = self._read(pb, 'wCurMartCount')[0]
        current = list(self._read(pb, 'wCurMartItems', count))
        # Only a fresh cartridge list is extended, so reopening the list never adds twice.
        if shop is None or current != list(shop['items']):
            return
        items = stock(self.data, shop)
        self._write(pb, 'wCurMartCount', [len(items)])
        self._write(pb, 'wCurMartItems', items + [0xFF])
        for index, item in enumerate(items[count:], count):
            self._write(pb, 'wMartItem1BCD', bcd(price(self.data, item)), offset=3 * index)

    def priced(self, pb):
        if not enabled() or self.mart(pb) is None:
            return
        item = self._read(pb, 'wCurItem')[0]
        value = self.extra_prices.get(item)
        if value is not None:
            pb.register_file.D, pb.register_file.E = value >> 8, value & 0xFF


def _targets(policy, snapshot):
    """Extra-stock items a held partner needs, as {item: set of species it would become}."""
    from .collection import prerequisites
    from .training import requested
    data, demand = policy.data, getattr(policy, 'demand', None) or {}
    party, stored = tuple(snapshot.party), tuple(snapshot.stored)
    needed = prerequisites(data, snapshot) if party or stored else set()
    owned = set(snapshot.owned)
    names = set(STONES)
    # A trade evolution needs a cable partner, so its item is only wanted while a peer is linked.
    if getattr(policy, 'peers', 0):
        names |= set(HELD)
    targets = {}
    for mon in party + stored:
        if mon.egg:
            continue
        for evo in data.species[mon.species]['evolutions']:
            if evo['method'] not in ('item', 'trade') or not evo['requirements']:
                continue
            name = evo['requirements'][0]
            if name not in names:
                continue
            species = evo['species']
            if (species in owned and species not in needed
                    and not requested(data, snapshot, demand, species, item=True)):
                continue
            # A partner already holding its trade item needs no other.
            if evo['method'] == 'trade' and getattr(mon, 'held_item', 0) == data.items[name]:
                continue
            targets.setdefault(data.items[name], set()).add(species)
    return targets


def legitimate(policy, snapshot, name, species):
    """Whether a source other than the store will still provide this item or its species."""
    data = policy.data
    if name in GRANDPA and not snapshot.event('EVENT_GOT_' + name + '_FROM_BILLS_GRANDPA'):
        if any(mon.species == GRANDPA[name] and not mon.egg for mon in snapshot.party + snapshot.stored):
            return True
    if name == 'FIRE_STONE' and not snapshot.event('EVENT_GOT_FIRE_STONE_FROM_BILLS_GRANDPA'):
        shown = 37 if data.game == 'silver' else 58
        if any(mon.species == shown and not mon.egg for mon in snapshot.party + snapshot.stored):
            return True
    if name in ONE_TIME and ONE_TIME[name] in data.events and not snapshot.event(ONE_TIME[name]):
        return True
    from .item_sources import PHONE_GIFTS, phone_key
    if data.game == 'crystal' and name in PHONE_GIFTS and not standing_down(policy, phone_key(name)):
        return True
    supply = getattr(policy, 'peer_supply', None) or set()
    return bool(species) and species <= supply


def needs(policy, snapshot):
    """Items to buy at the store, as {item id: count}, in stock order."""
    if not enabled():
        return {}
    data = policy.data
    targets = _targets(policy, snapshot)
    bag = Counter()
    for item, count in snapshot.items:
        bag[item] += count
    result = {}
    for _, _, names in MARTS:
        for name in names:
            item = data.items[name]
            species = targets.get(item, set())
            if len(species) > bag[item] and not legitimate(policy, snapshot, name, species):
                result[item] = len(species) - bag[item]
    return result


def shortfall(policy, snapshot):
    """Whether a needed extra item waits only for money, which a League run then earns."""
    data = policy.data
    return any(not standing_down(policy, store_key(item)) and snapshot.money < price(data, item)
               for item in needs(policy, snapshot))


def store_key(item):
    return f'store:{item}'


def journey(policy, snapshot, Goal):
    """Walk to the clerk who sells a needed extra item, when the money covers one."""
    state = policy.collection
    wanted = needs(policy, snapshot)
    errand = state.get('store')
    if errand and (errand['item'] not in wanted or policy.decisions - errand['started'] > STORE_DECISIONS):
        if errand['item'] in wanted:
            stand_down(policy, store_key(errand['item']))
        state.pop('store', None)
        errand = None
    data = policy.data
    for item, count in wanted.items():
        cost = price(data, item)
        if standing_down(policy, store_key(item)) or not cost or snapshot.money < cost:
            continue
        for mid, entry in data.maps.items():
            for shop in entry['shops']:
                if item not in stock(data, shop) or not policy.clerk_present(snapshot, entry, shop):
                    continue
                if errand is None or errand['item'] != item:
                    errand = state['store'] = {'item': item, 'started': policy.decisions, 'tries': 0}
                errand['amount'] = min(count, snapshot.money // cost)
                label = f'Buy a {data.item_names.get(item, item)} at the department store'
                return policy.person(snapshot, 'collection_store', label, entry['constant'], shop['script'])
    return None


def arrive(policy, snapshot):
    if policy.goal.key != 'collection_store':
        return None
    errand = policy.collection.get('store')
    if not errand:
        return 'b'
    errand['tries'] += 1
    if errand['tries'] > STORE_TRIES:
        # The clerk was reached but the purchase never landed: stop instead of talking forever.
        stand_down(policy, store_key(errand['item']))
        policy.collection.pop('store', None)
        return 'b'
    from .menus import Buy
    policy.menu = Buy(errand['item'], errand['amount'], dict(snapshot.items).get(errand['item'], 0))
    return 'wait'
