"""Gen II TM shop and Champion shop, open to every Champion as in Gen I."""
import os
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.gen2 import champion_shop as shop
from pokesim.gen2 import store_stock
from pokesim.gen2.standdown import standing_down
from tests.test_gen2_store_stock import Emulator, open_list


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


def mon(species, level=100, moves=(70, 15, 29, 76), **extra):
    return SimpleNamespace(**{'species': species, 'level': level, 'moves': tuple(moves), 'egg': False, 'held_item': 0,
                              'hp': 300, 'status': 0, 'trainer_id': 1, 'nick': 'PAL', 'dvs': (5, 4, 11, 12, 5),
                              'stat_exp': (40000,) * 5, 'friendship': 200, 'pp': (10,) * len(moves),
                              'max_pp': (10,) * len(moves), 'box': None, 'position': 0, **extra})


def snap(data, party=(), items=(), money=500000, champion=1, stored=()):
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), items=list(items), money=money,
                           hall_of_fame_count=champion, in_battle=False, valid=True, started=True,
                           pockets={'items': [], 'balls': []}, data=data)


def policy_for(data, **extra):
    state = SimpleNamespace(data=data, collection={}, decisions=10000, goal=None, menu=None, shop_offers=set(),
                            clerk_present=lambda *args: True,
                            person=lambda snap, key, label, place, script: SimpleNamespace(
                                key=key, label=label, map=place, script=script))
    for name, value in extra.items():
        setattr(state, name, value)
    return state


class Store(dict):
    def set(self, key, value):
        self[key] = value


def test_limited_tms_and_prices(real_data):
    tms = shop.limited_tms(real_data)
    assert len(tms) == 34
    numbers = {shop.tm_number(real_data, item) for item in tms}
    assert not numbers & shop.RENEWABLE
    earthquake = real_data.items['TM26']
    assert real_data.moves[tms[earthquake]]['name'].upper() == 'EARTHQUAKE'
    assert shop.unit_price(real_data, earthquake) == 50000
    assert shop.unit_price(real_data, real_data.items['TM44']) == 25000
    assert shop.unit_price(real_data, real_data.items['TM04']) == 10000
    assert shop.unit_price(real_data, real_data.items['TM02']) is None
    assert shop.unit_price(real_data, real_data.items['MASTER_BALL']) == 100000
    assert shop.unit_price(real_data, real_data.items['RARE_CANDY']) == 5000
    assert shop.label(real_data, earthquake) == 'TM26 Earthquake'


def test_the_shop_opens_to_a_champion_with_extra_store_items_off(real_data, monkeypatch):
    # Red, Blue and Yellow open their Champion shop without the setting, so Gen II does too.
    monkeypatch.setattr(config, 'EXTRA_STORE_ITEMS', False, raising=False)
    tm, ball = real_data.items['TM26'], real_data.items['MASTER_BALL']
    assert shop.catalogue(real_data, {'item': tm}, set()) == {mart: {tm: 50000} for mart in shop.TM_MARTS}
    assert shop.status(Store(), real_data)['offers']
    policy = policy_for(real_data)
    assert shop.journey(policy, snap(real_data, [mon(154)]), None).map == 'GOLDENROD_DEPT_STORE_5F'
    assert type(shop.use(policy, snap(real_data, [mon(154)], [(tm, 1)]))).__name__ == 'Teach'
    # The 4F list gains the planned Master Ball but none of the setting's stones.
    emulator = Emulator(real_data)
    assert store_stock.StoreStock(real_data, champion=lambda: shop.catalogue(real_data, {'item': ball}, {ball})).attach(emulator)
    supplies = next(entry for maps in real_data.maps.values() for entry in maps['shops']
                    if entry['mart'] == 'MART_GOLDENROD_4F')
    assert open_list(real_data, emulator, supplies['items']) == list(supplies['items']) + [ball]
    # A stone left in wCurItem keeps the cartridge price while the setting is off.
    symbols = real_data.symbols
    emulator.register_file.D = emulator.register_file.E = 7
    emulator.memory[0, slice(symbols['wCurItem'][1], symbols['wCurItem'][1] + 1)] = [real_data.items['MOON_STONE']]
    bank, address = symbols['SelectQuantityToBuy']
    emulator.hooks[bank, address + 6]()
    assert (emulator.register_file.D, emulator.register_file.E) == (7, 7)


def test_catalogue_routes_tms_to_5f_and_capped_supplies_need_an_offer(real_data, on):
    tm, ball = real_data.items['TM26'], real_data.items['MASTER_BALL']
    assert shop.catalogue(real_data, {'item': tm}, set()) == {mart: {tm: 50000} for mart in shop.TM_MARTS}
    assert shop.catalogue(real_data, {'item': ball}, set()) == {}
    assert shop.catalogue(real_data, {'item': ball}, {ball}) == {'MART_GOLDENROD_4F': {ball: 100000}}
    assert shop.catalogue(real_data, {'item': tm, 'bought': True}, set()) == {}


def test_walking_offers_start_at_champion_and_renew_after_a_purchase(real_data, on):
    store = Store()
    walking = {'available': True, 'total': 5000}
    shop.observe(store, snap(real_data, champion=0), walking)
    assert store == {}
    shop.observe(store, snap(real_data), walking)
    assert shop.ready(store, real_data, walking) == set()
    later = {'available': True, 'total': 5000 + shop.INTERVAL}
    ball, candy = real_data.items['MASTER_BALL'], real_data.items['RARE_CANDY']
    assert shop.ready(store, real_data, later) == {ball, candy}
    assert shop.consume(store, real_data, ball, later)
    assert shop.ready(store, real_data, later) == {candy}
    assert not shop.consume(store, real_data, real_data.items['ELIXER'], later)
    row = next(row for row in shop.status(store, real_data, later)['offers'] if row['item'] == ball)
    assert row['purchased'] == 1 and row['remaining'] == shop.INTERVAL
    assert 'Goldenrod' in shop.status(store, real_data, later)['counter']


def test_best_tm_buys_earthquake_for_typhlosion_and_keeps_hms(real_data, on):
    snapshot = snap(real_data, [mon(154)])
    plan = shop.best_tm(real_data, snapshot, owned=False)
    assert plan['item'] == real_data.items['TM26'] and plan['target'] == 0
    assert plan['replace'] not in (70, 15)
    # Too little money above the reserve buys nothing.
    assert shop.best_tm(real_data, snap(real_data, [mon(154)], money=60000), owned=False)['item'] != plan['item']
    assert shop.best_tm(real_data, snap(real_data, [mon(154)], money=20000), owned=False) is None
    # Partners under level 50 and a run before the Hall of Fame are left alone.
    assert shop.best_tm(real_data, snap(real_data, [mon(154, level=40)]), owned=False) is None
    assert shop.choose(real_data, snap(real_data, [mon(154)], champion=0), set()) is None


def test_journey_and_arrive_buy_the_planned_tm_then_teach_it(real_data, on):
    tm = real_data.items['TM26']
    policy = policy_for(real_data)
    snapshot = snap(real_data, [mon(154)])
    goal = shop.journey(policy, snapshot, None)
    assert goal.key == 'collection_champion_shop' and goal.map == 'GOLDENROD_DEPT_STORE_5F'
    assert 'TM26 Earthquake' in goal.label
    policy.goal = goal
    assert shop.arrive(policy, snapshot) == 'wait'
    assert policy.menu.item == tm and policy.menu.amount == 1
    bought = snap(real_data, [mon(154)], [(tm, 1)])
    assert shop.journey(policy, bought, None) is None and policy.collection[shop.PLAN]['bought']
    task = shop.use(policy, bought)
    assert type(task).__name__ == 'Teach' and task.move == shop.limited_tms(real_data)[tm] and task.slot == 0


def test_a_purchase_that_never_lands_stands_down(real_data, on):
    policy = policy_for(real_data)
    snapshot = snap(real_data, [mon(154)])
    policy.goal = shop.journey(policy, snapshot, None)
    item = policy.collection[shop.PLAN]['item']
    for _ in range(shop.PLAN_TRIES):
        assert shop.arrive(policy, snapshot) == 'wait'
    assert shop.arrive(policy, snapshot) == 'b'
    assert standing_down(policy, shop.plan_key(item))


def test_supplies_follow_the_capped_offers_then_held_items(real_data, on):
    ball, candy = real_data.items['MASTER_BALL'], real_data.items['RARE_CANDY']
    leftovers, egg = real_data.items['LEFTOVERS'], real_data.items['LUCKY_EGG']
    party = [mon(154, moves=(70, 15)), mon(18, level=60, moves=(17,))]
    snapshot = snap(real_data, party)
    assert shop.best_supply(real_data, snapshot, {ball, candy})['item'] == ball
    plan = shop.best_supply(real_data, snapshot, {candy})
    assert plan['item'] == candy and plan['quantity'] == 5 and plan['target'] == 1
    plan = shop.best_supply(real_data, snapshot, set())
    assert plan['item'] == leftovers and plan['target'] == 0
    # One Leftovers anywhere is enough; the Lucky Egg goes to the lower level partner.
    snapshot = snap(real_data, party, stored=[mon(25, held_item=leftovers)])
    plan = shop.best_supply(real_data, snapshot, set())
    assert plan['item'] == egg and plan['target'] == 1
    # PP Up waits for Core to drive the Gen II move list.
    assert 'PP_UP' not in shop.ORDER


def test_bought_supplies_are_used_or_given(real_data, on):
    candy, leftovers = real_data.items['RARE_CANDY'], real_data.items['LEFTOVERS']
    party = [mon(154), mon(18, level=60, moves=(17,))]
    policy = policy_for(real_data)
    policy.collection[shop.PLAN] = {'item': candy, 'target': 1, 'signature': shop.signature(party[1]),
                                    'quantity': 5, 'bought': True}
    task = shop.use(policy, snap(real_data, party, [(candy, 5)]))
    assert type(task).__name__ == 'UseOn' and task.slot == 1 and task.initial == 5
    policy = policy_for(real_data)
    policy.collection[shop.PLAN] = {'item': leftovers, 'target': 0, 'signature': shop.signature(party[0]),
                                    'quantity': 1, 'bought': True}
    task = shop.use(policy, snap(real_data, party, [(leftovers, 1)]))
    assert type(task).__name__ == 'Give' and task.slot == 0 and shop.PLAN not in policy.collection


def test_elixir_restores_a_partner_out_of_attacking_pp(real_data):
    elixir = real_data.items['ELIXER']
    partner = mon(154, moves=(53, 15), pp=(0, 30))
    assert shop.elixir(real_data, snap(real_data, [partner], [(elixir, 1)]), partner) == elixir
    partner = mon(154, moves=(53, 15), pp=(5, 30))
    assert shop.elixir(real_data, snap(real_data, [partner], [(elixir, 1)]), partner) is None


def test_buy_list_adds_the_planned_item_and_charges_above_65535(real_data, on):
    tm, ball = real_data.items['TM26'], real_data.items['MASTER_BALL']
    emulator = Emulator(real_data)
    plan = {'value': {'item': ball}}
    stock = store_stock.StoreStock(real_data, champion=lambda: shop.catalogue(real_data, plan['value'], {ball}))
    assert stock.attach(emulator)
    supplies = next(entry for maps in real_data.maps.values() for entry in maps['shops']
                    if entry['mart'] == 'MART_GOLDENROD_4F')
    listed = open_list(real_data, emulator, supplies['items'])
    assert ball in listed and tm not in listed
    symbols = real_data.symbols
    emulator.memory[0, slice(symbols['wCurItem'][1], symbols['wCurItem'][1] + 1)] = [ball]
    bank, address = symbols['SelectQuantityToBuy']
    emulator.hooks[bank, address + 6]()
    assert (emulator.register_file.D, emulator.register_file.E) == (0xFF, 0xFF)
    # The cartridge multiplies 0xFFFF; the subtotal hook charges the full ₽100,000 instead.
    price = symbols['wBuySellItemPrice'][1]
    emulator.memory[0, slice(price, price + 2)] = [0xFF, 0xFF]
    change = symbols['wItemQuantityChange'][1]
    emulator.memory[0, slice(change, change + 1)] = [1]
    emulator.hooks[tuple(symbols['BuySell_DisplaySubtotal'])]()
    product = symbols['hProduct'][1] + 1
    assert emulator.memory[slice(product, product + 3)] == [0x01, 0x86, 0xA0]
    bank, address = symbols['BuyMenuLoop']
    emulator.hooks[bank, address + 87]()
    assert stock.purchases == [(ball, 1, 100000)]


def test_emulator_records_a_landed_purchase_and_renews_the_offer(real_data, on):
    from pokesim.gen2.emulator import Emulator as Gen2Emulator
    ball = real_data.items['MASTER_BALL']
    emu = Gen2Emulator.__new__(Gen2Emulator)
    emu.data, emu.store = real_data, Store()
    emu.steps = SimpleNamespace(value={'available': True, 'total': 0})
    emu.policy = policy_for(real_data)
    emu.store_stock = SimpleNamespace(purchases=[])
    events = []
    emu._event = lambda event, snapshot: events.append(event)
    snapshot = snap(real_data, [mon(154)])
    emu._champion_shop(snapshot)
    assert emu.policy.shop_offers == set()
    emu.steps.value['total'] = shop.INTERVAL
    emu._champion_shop(snapshot)
    assert ball in emu.policy.shop_offers
    emu.policy.collection[shop.PLAN] = {'item': ball}
    emu.store_stock.purchases.append((ball, 1, 100000))
    emu._champion_shop(snapshot)
    assert emu.policy.collection[shop.PLAN]['bought'] and ball not in emu.policy.shop_offers
    assert emu.store_stock.purchases == [] and '₽100,000' in str(vars(events[0]))
