"""The "Extra store items" setting: Goldenrod sells spent one-time evolution items."""
import os
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.gen2 import store_stock
from pokesim.gen2.item_sources import PHONE_GIFTS, phone_key
from pokesim.gen2.standdown import stand_down, standing_down


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, 'EXTRA_STORE_ITEMS', True, raising=False)


def mon(species, **extra):
    return SimpleNamespace(**{'species': species, 'egg': False, 'held_item': 0, 'level': 30, 'box': 1,
                              'position': 0, 'trainer_id': 1, 'dvs': (9, 9, 9, 9, 9), **extra})


def case(data, party=(), stored=(), items=(), money=50000, events=(), owned=(), phone=False, **policy):
    spent = {'EVENT_GOT_LEAF_STONE_FROM_BILLS_GRANDPA', 'EVENT_GOT_FIRE_STONE_FROM_BILLS_GRANDPA',
             'EVENT_GOT_WATER_STONE_FROM_BILLS_GRANDPA', 'EVENT_GOT_THUNDERSTONE_FROM_BILLS_GRANDPA',
             *store_stock.ONE_TIME.values()} - set(events)
    snapshot = SimpleNamespace(party=tuple(party), stored=tuple(stored), items=list(items), money=money,
                               owned=frozenset(owned), daycare=(), event=lambda name: name in spent)
    state = SimpleNamespace(data=data, collection={}, decisions=100, demand={}, peers=0, peer_supply=set(),
                            goal=None, menu=None, clerk_present=lambda *args: True,
                            person=lambda snap, key, label, place, script: SimpleNamespace(
                                key=key, label=label, map=place, script=script))
    for name, value in policy.items():
        setattr(state, name, value)
    if data.game == 'crystal' and not phone:
        # Crystal phone trainers give stones too. Unless asked for, they have already been tried.
        for name in PHONE_GIFTS:
            stand_down(state, phone_key(name))
    return state, snapshot


def test_setting_off_buys_and_injects_nothing(real_data, monkeypatch):
    monkeypatch.setattr(config, 'EXTRA_STORE_ITEMS', False, raising=False)
    policy, snapshot = case(real_data, party=[mon(102)])
    assert store_stock.needs(policy, snapshot) == {}
    assert store_stock.journey(policy, snapshot, None) is None
    assert not store_stock.shortfall(policy, snapshot)
    shop = next(shop for entry in real_data.maps.values() for shop in entry['shops'] if shop['mart'] == 'MART_GOLDENROD_4F')
    assert store_stock.stock(real_data, shop) == list(shop['items'])


def test_only_needed_items_are_bought(real_data, on):
    leaf, thunder = real_data.items['LEAF_STONE'], real_data.items['THUNDERSTONE']
    # Exeggcute and Gloom both need a Leaf Stone, Pikachu is already evolved in the Pokédex.
    policy, snapshot = case(real_data, party=[mon(102), mon(44)], stored=[mon(25)], owned={25, 26, 44, 102, 182})
    assert store_stock.needs(policy, snapshot) == {leaf: 2}
    snapshot.items = [(leaf, 1)]
    assert store_stock.needs(policy, snapshot) == {leaf: 1}
    snapshot.items = [(leaf, 2)]
    assert store_stock.needs(policy, snapshot) == {}
    # Raichu is registered, so Pikachu never asks for a Thunderstone.
    assert thunder not in store_stock.needs(policy, snapshot)
    snapshot.owned = frozenset({25, 44, 102, 182})
    assert store_stock.needs(policy, snapshot) == {thunder: 1}


def test_journey_buys_the_needed_count_at_goldenrod(real_data, on):
    leaf = real_data.items['LEAF_STONE']
    policy, snapshot = case(real_data, party=[mon(102)], owned={102})
    goal = store_stock.journey(policy, snapshot, None)
    assert goal.key == 'collection_store' and goal.map == 'GOLDENROD_DEPT_STORE_4F'
    assert policy.collection['store']['item'] == leaf and policy.collection['store']['amount'] == 1
    policy.goal = goal
    assert store_stock.arrive(policy, snapshot) == 'wait'
    assert policy.menu.item == leaf and policy.menu.amount == 1


def test_legitimate_sources_win(real_data, on):
    leaf, moon = real_data.items['LEAF_STONE'], real_data.items['MOON_STONE']
    # Bill's grandfather still owes a Leaf Stone for showing Oddish, which is held.
    policy, snapshot = case(real_data, party=[mon(102), mon(43)], owned={43, 102},
                            events={'EVENT_GOT_LEAF_STONE_FROM_BILLS_GRANDPA'})
    assert leaf not in store_stock.needs(policy, snapshot)
    # The Tohjo Falls Moon Stone is still on the ground.
    policy, snapshot = case(real_data, party=[mon(35)], owned={35}, events={'EVENT_TOHJO_FALLS_MOON_STONE'})
    assert moon not in store_stock.needs(policy, snapshot)
    # A linked peer offers Exeggutor, so the trade comes first.
    policy, snapshot = case(real_data, party=[mon(102)], owned={102}, peer_supply={103})
    assert store_stock.needs(policy, snapshot) == {}
    # A stone in the bag is used before buying another.
    policy, snapshot = case(real_data, party=[mon(102)], owned={102}, items=[(leaf, 1)])
    assert store_stock.needs(policy, snapshot) == {}
    # In Crystal, Picnicker Gina still calls with a Leaf Stone. Gold and Silver have no such call.
    policy, snapshot = case(real_data, party=[mon(102)], owned={102}, phone=True)
    assert store_stock.needs(policy, snapshot) == ({} if real_data.game == 'crystal' else {leaf: 1})


def test_trade_items_wait_for_a_linked_peer(real_data, on):
    rock = real_data.items['KINGS_ROCK']
    policy, snapshot = case(real_data, party=[mon(61)], owned={61, 62})
    assert rock not in store_stock.needs(policy, snapshot)
    policy.peers = 1
    assert store_stock.needs(policy, snapshot) == {rock: 1}
    snapshot.party = (mon(61, held_item=rock),)
    assert rock not in store_stock.needs(policy, snapshot)


def test_short_money_funds_a_league_run_instead_of_walking(real_data, on):
    policy, snapshot = case(real_data, party=[mon(102)], owned={102}, money=1190)
    assert store_stock.journey(policy, snapshot, None) is None
    assert store_stock.shortfall(policy, snapshot)
    snapshot.money = 2100
    assert not store_stock.shortfall(policy, snapshot)


def test_a_purchase_that_never_lands_stands_down(real_data, on):
    leaf = real_data.items['LEAF_STONE']
    policy, snapshot = case(real_data, party=[mon(102)], owned={102})
    policy.goal = store_stock.journey(policy, snapshot, None)
    for _ in range(store_stock.STORE_TRIES):
        assert store_stock.arrive(policy, snapshot) == 'wait'
    assert store_stock.arrive(policy, snapshot) == 'b'
    assert standing_down(policy, store_stock.store_key(leaf))
    assert store_stock.journey(policy, snapshot, None) is None
    assert not store_stock.shortfall(policy, snapshot)
    # An errand that runs too long also stands down.
    policy, snapshot = case(real_data, party=[mon(102)], owned={102})
    store_stock.journey(policy, snapshot, None)
    policy.decisions += store_stock.STORE_DECISIONS + 1
    assert store_stock.journey(policy, snapshot, None) is None
    assert standing_down(policy, store_stock.store_key(leaf))


class Memory:
    def __init__(self):
        self.bytes = {}

    def __getitem__(self, key):
        span = key[1] if isinstance(key, tuple) else key
        return [self.bytes.get(address, 0) for address in range(span.start, span.stop)]

    def __setitem__(self, key, values):
        span = key[1] if isinstance(key, tuple) else key
        for offset, value in enumerate(values):
            self.bytes[span.start + offset] = value


class Emulator:
    def __init__(self, data):
        self.memory, self.hooks = Memory(), {}
        self.register_file = SimpleNamespace(D=0, E=98)
        bank, address = data.symbols['SelectQuantityToBuy']
        self.memory[bank, address:address + 7] = [0x3E, 4, 0x21, 0, 0x40, 0xCF, 0x7A]
        # push hl / ld hl, hMoneyTemp / ldh a, [hProduct + 1], then the landed purchase in BuyMenuLoop.
        bank, address = data.symbols['BuySell_DisplaySubtotal']
        money, product = data.symbols['hMoneyTemp'][1], data.symbols['hProduct'][1] + 1
        self.memory[bank, address:address + 6] = [0xE5, 0x21, money & 0xFF, money >> 8, 0xF0, product & 0xFF]
        bank, address = data.symbols['BuyMenuLoop']
        item = data.symbols['wMartItemID'][1]
        self.memory[bank, address + 87:address + 93] = [0xFA, item & 0xFF, item >> 8, 0x5F, 0x16, 0x00]

    def hook_register(self, bank, address, callback, context):
        self.hooks[bank, address] = lambda: callback(context)


def open_list(data, emulator, items):
    symbols = data.symbols
    bank, label = data.symbols['MartGoldenrod4F']
    emulator.memory[0, slice(symbols['wMartPointerBank'][1], symbols['wMartPointerBank'][1] + 1)] = [bank]
    emulator.memory[0, slice(symbols['wMartPointer'][1], symbols['wMartPointer'][1] + 2)] = [label & 0xFF, label >> 8]
    count = symbols['wCurMartCount'][1]
    emulator.memory[0, slice(count, count + 1)] = [len(items)]
    start = symbols['wCurMartItems'][1]
    emulator.memory[0, slice(start, start + len(items) + 1)] = list(items) + [0xFF]
    emulator.hooks[tuple(symbols['BuyMenu'])]()
    length = emulator.memory[0, slice(count, count + 1)][0]
    return emulator.memory[0, slice(start, start + length)]


def test_buy_list_gains_the_stones_once_and_charges_2100(real_data, monkeypatch):
    shop = next(shop for entry in real_data.maps.values() for shop in entry['shops'] if shop['mart'] == 'MART_GOLDENROD_4F')
    stones = [real_data.items[name] for name in store_stock.STONES]
    monkeypatch.setattr(config, 'EXTRA_STORE_ITEMS', False, raising=False)
    emulator = Emulator(real_data)
    assert store_stock.StoreStock(real_data).attach(emulator)
    assert open_list(real_data, emulator, shop['items']) == list(shop['items'])
    monkeypatch.setattr(config, 'EXTRA_STORE_ITEMS', True, raising=False)
    extended = open_list(real_data, emulator, shop['items'])
    assert extended == list(shop['items']) + stones
    # Reopening an already extended list adds nothing.
    assert open_list(real_data, emulator, extended) == extended
    prices = real_data.symbols['wMartItem1BCD'][1] + 3 * len(shop['items'])
    assert emulator.memory[0, slice(prices, prices + 3)] == [0x00, 0x21, 0x00]
    current = real_data.symbols['wCurItem'][1]
    emulator.memory[0, slice(current, current + 1)] = [real_data.items['MOON_STONE']]
    bank, address = real_data.symbols['SelectQuantityToBuy']
    emulator.hooks[bank, address + 6]()
    assert (emulator.register_file.D, emulator.register_file.E) == (2100 >> 8, 2100 & 0xFF)


def test_a_cartridge_with_other_code_is_refused(real_data):
    emulator = Emulator(real_data)
    bank, address = real_data.symbols['SelectQuantityToBuy']
    emulator.memory[bank, address:address + 7] = [0] * 7
    with pytest.raises(ValueError):
        store_stock.StoreStock(real_data).attach(emulator)


def test_runtime_default_is_off_and_new_adventures_default_on():
    import dataclasses
    from pokesim.runtime.settings import SimulationSettings
    field = next(field for field in dataclasses.fields(SimulationSettings) if field.name == 'extra_store_items')
    assert field.default is False
    from pathlib import Path
    source = Path(__file__).resolve().parents[1].joinpath('pokesim/app/manager.py').read_text()
    assert "'extra_store_items': data.get('extra_store_items', True)" in source


def test_collection_demand_validates_supply_and_peers():
    from pokesim.gen2.trading import Participant
    participant = Participant.__new__(Participant)
    participant.emu = SimpleNamespace(policy=SimpleNamespace())
    assert participant.collection_demand({'requests': {'103': 1}, 'supply': [69], 'peers': 2}) == {'requests': {103: 1}}
    assert participant.emu.policy.peer_supply == {69} and participant.emu.policy.peers == 2
    participant.collection_demand({'requests': {}})
    assert participant.emu.policy.peer_supply == set() and participant.emu.policy.peers == 0
    for bad in ({'supply': 'x'}, {'supply': [0]}, {'supply': [252]}, {'supply': [True]}, {'peers': -1}, {'peers': '1'}):
        with pytest.raises(ValueError):
            participant.collection_demand({'requests': {}, **bad})
