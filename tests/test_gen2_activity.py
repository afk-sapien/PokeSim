"""Gold, Silver and Crystal action counts in the shared activity ledger."""
import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim import trade_statistics
from pokesim.activity_ledger import KEY, gen2_status, status
from pokesim.gen2 import activity
from pokesim.store import Store

WRAM = {'wBattleMode': 0xD22D, 'wCurPartyMon': 0xD109, 'wNumItems': 0xD892, 'wItemQuantityChange': 0xD10C,
        'wTempTMHM': 0xD265, 'wTMsHMs': 0xD859, 'wTempEnemyMonSpecies': 0xD204, 'wOTPartyCount': 0xD288,
        'wOTPartySpecies': 0xD289, 'wCurItem': 0xD106, 'wLinkMode': 0xC2DC, 'wBattleType': 0xD230,
        'wWildMon': 0xD20C, 'wEnemyMonDVs': 0xD206, 'wScriptBank': 0xD160, 'wScriptPos': 0xD161,
        'wContestMonSpecies': 0xDCE7}
CODE = {'InitEnemyWildmon': (0x0F, 0x5000), 'LoadEnemyMonToSwitchTo': (0x0F, 0x5100),
        'FaintEnemyPokemon': (0x0F, 0x5200), 'UseDisposableItem': (0x03, 0x5300), 'ConsumeTM': (0x03, 0x5400),
        'PokeBallEffect': (0x03, 0x5500), 'TossItem': (0, 0x2F66), 'WaitSFX': (0, 0x3C55),
        'ConvertCurItemIntoCurTMHM': (0, 0x2F20), 'Script_takemoney': (0x25, 0x5600),
        'GetMoneyAccount': (0x25, 0x5700), 'LoadMoneyAmountToMem': (0x25, 0x5710), 'TakeMoney': (0x05, 0x6250),
        'CheckPartyFullAfterContest': (0x13, 0x5800)}
POKE_BALL, POTION, BICYCLE, TM01, HM01 = 5, 18, 7, 191, 243


def word(value):
    return [value & 0xFF, value >> 8]


class Ram:
    """A flat bus where every symbol has its own address."""
    def __init__(self):
        self.raw = bytearray(0x10000)

    def __getitem__(self, key):
        return self.raw[key[1] if isinstance(key, tuple) else key]

    def __setitem__(self, key, value):
        self.raw[key[1] if isinstance(key, tuple) else key] = value

    def put(self, name, *values):
        address = WRAM[name]
        self.raw[address:address + len(values)] = bytes(values)


def fake_data():
    symbols = {**{name: (1, address) for name, address in WRAM.items()}, **CODE}
    names = {POKE_BALL: 'Poké Ball', POTION: 'Potion', BICYCLE: 'Bicycle', TM01: 'Tm01', HM01: 'Hm01',
             6: 'Teru-Sama', 256: '?'}
    pockets = {POKE_BALL: 'BALL', POTION: 'ITEM', BICYCLE: 'KEY_ITEM', TM01: 'TM_HM', HM01: 'TM_HM', 6: 'ITEM'}
    return SimpleNamespace(game='gold', symbols=symbols, item_names=names,
                           item_attributes={item: {'pocket': pocket} for item, pocket in pockets.items()},
                           species={dex: {'name': f'Species {dex}', 'dex': dex} for dex in range(1, 252)})


def cartridge():
    """The opening bytes each hook checks, as the pret sources assemble them."""
    ram = Ram()

    def put(name, values, offset=0):
        address = CODE[name][1] + offset
        ram.raw[address:address + len(values)] = bytes(values)
    put('InitEnemyWildmon', [0x3E, 0x01, 0xEA, *word(WRAM['wBattleMode'])])
    put('LoadEnemyMonToSwitchTo', [0x78, 0xEA, *word(WRAM['wCurPartyMon'])])
    put('FaintEnemyPokemon', [0xCD, *word(CODE['WaitSFX'][1])])
    put('UseDisposableItem', [0x21, *word(WRAM['wNumItems']), 0x3E, 0x01, 0xEA, *word(WRAM['wItemQuantityChange']),
                              0xC3, *word(CODE['TossItem'][1])])
    put('ConsumeTM', [0xCD, *word(CODE['ConvertCurItemIntoCurTMHM'][1]), 0xFA, *word(WRAM['wTempTMHM']), 0x3D,
                      0x21, *word(WRAM['wTMsHMs']), 0x06, 0x00, 0x4F, 0x09, 0x7E, 0xA7, 0xC8, 0x3D, 0x77])
    put('PokeBallEffect', [0x21, *word(WRAM['wNumItems']), 0x3C, 0xEA, *word(WRAM['wItemQuantityChange']),
                           0xC3, *word(CODE['TossItem'][1])], offset=0x80)
    put('Script_takemoney', [0xCD, *word(CODE['GetMoneyAccount'][1]), 0xCD, *word(CODE['LoadMoneyAmountToMem'][1]),
                             0x3E, CODE['TakeMoney'][0], 0x21, *word(CODE['TakeMoney'][1]), 0xCF])
    put('CheckPartyFullAfterContest', [0xFA, *word(WRAM['wContestMonSpecies']), 0xA7, 0xCA])
    return ram


class Emulator:
    def __init__(self):
        self.memory, self.hooks = cartridge(), {}
        self.register_file = SimpleNamespace(B=0)

    def hook_register(self, bank, address, callback, context):
        assert (bank, address) not in self.hooks, 'Hook already registered'
        self.hooks[bank, address] = lambda: callback(context)

    def run(self, name, offset=0):
        bank, address = CODE[name]
        self.hooks[bank, address + offset]()


@pytest.fixture
def ledger(tmp_path):
    store, data, pb = Store(tmp_path), fake_data(), Emulator()
    tracker = activity.Ledger(store, data, fresh=True)
    tracker.attach(pb)
    return SimpleNamespace(store=store, data=data, pb=pb, tracker=tracker)


def counts(store, kind):
    return dict(store.db.execute('SELECT subject, total FROM activity_counts WHERE kind=?', (kind,)).fetchall())


def test_hooks_sit_at_the_seven_checked_sites():
    rows = activity.hooks(cartridge(), fake_data())
    assert [kind for kind, _, _ in rows] == ['wild', 'trainer', 'defeated', 'used', 'used', 'used', 'vended']
    assert (0x03, 0x5400 + 17) in [(bank, address) for _, bank, address in rows]
    assert (0x03, 0x5580) in [(bank, address) for _, bank, address in rows]
    assert ('vended', 0x25, 0x5600) in rows


def test_a_cartridge_with_other_code_counts_nothing_and_still_plays(tmp_path):
    store, pb = Store(tmp_path), Emulator()
    pb.memory.raw[0x5000] = 0
    activity.Ledger(store, fake_data(), fresh=True).attach(pb)
    assert not pb.hooks
    value = store.get(KEY)
    assert value['available'] is False and value['started_at'] is None


def test_wild_trainer_and_defeated_battles_are_counted_once_per_moment(ledger):
    ram, pb = ledger.pb.memory, ledger.pb
    ram.put('wBattleMode', 1)
    ram.put('wTempEnemyMonSpecies', 16)
    pb.run('InitEnemyWildmon')
    pb.run('InitEnemyWildmon')
    ram.put('wTempEnemyMonSpecies', 161)
    pb.run('InitEnemyWildmon')
    pb.run('FaintEnemyPokemon')
    ram.put('wBattleMode', 2)
    ram.put('wOTPartyCount', 3)
    ram.put('wOTPartySpecies', 74, 95, 208)
    pb.register_file.B = 2
    pb.run('LoadEnemyMonToSwitchTo')
    pb.register_file.B = 5
    pb.run('LoadEnemyMonToSwitchTo')
    ram.put('wTempEnemyMonSpecies', 208)
    pb.run('FaintEnemyPokemon')
    assert counts(ledger.store, 'wild') == {16: 1, 161: 1}
    assert counts(ledger.store, 'trainer') == {208: 1}
    assert counts(ledger.store, 'defeated') == {161: 1, 208: 1}


@pytest.mark.parametrize('name, value', [('wLinkMode', 1), ('wBattleType', 3), ('wBattleType', 2)])
def test_link_battles_the_catching_tutorial_and_debug_battles_are_not_counted(ledger, name, value):
    ram = ledger.pb.memory
    ram.put('wBattleMode', 1)
    ram.put('wTempEnemyMonSpecies', 16)
    ram.put(name, value)
    ledger.pb.run('InitEnemyWildmon')
    ledger.pb.run('FaintEnemyPokemon')
    assert not counts(ledger.store, 'wild') and not counts(ledger.store, 'defeated')


def test_used_items_count_consumables_only_and_purchases_count_the_quantity(ledger):
    ram, pb = ledger.pb.memory, ledger.pb
    for item, site, offset in ((POKE_BALL, 'PokeBallEffect', 0x80), (POTION, 'UseDisposableItem', 0),
                               (TM01, 'ConsumeTM', 17), (BICYCLE, 'UseDisposableItem', 0), (HM01, 'ConsumeTM', 17)):
        ram.put('wCurItem', item)
        pb.run(site, offset)
    assert counts(ledger.store, 'used') == {POKE_BALL: 1, POTION: 1, TM01: 1}
    ram.put('wCurItem', POTION)
    ram.put('wItemQuantityChange', 3)
    ledger.tracker.bought(pb)
    ledger.tracker.bought(pb)
    assert counts(ledger.store, 'bought') == {POTION: 3}


def charge(ram, script):
    """Place a map script at 0x6000, run up to its last command, takemoney, as Script_takemoney sees it."""
    ram.raw[0x6000:0x6000 + len(script)] = bytes(script)
    ram.put('wScriptBank', 0x15)
    # takemoney is the last five bytes, and the engine has read its command byte.
    ram.put('wScriptPos', *word(0x6000 + len(script) - 4))


def takemoney(account=0):
    return [0x23, account, 0x00, 0x00, 0x02]


def test_script_sales_count_as_purchases_and_other_payments_do_not(ledger):
    ram, pb = ledger.pb.memory, ledger.pb
    # The last battle's type stays in RAM out on the map and does not stop a sale.
    ram.put('wBattleType', 3)
    no_space = [0x08, 0x34, 0x12]
    # A drink machine or Moomoo Milk: giveitem / iffalse .NoSpace / takemoney YOUR_MONEY.
    charge(ram, [0x1F, POTION, 1, *no_space, *takemoney()])
    pb.run('Script_takemoney')
    pb.run('Script_takemoney')  # a reload replays the same sale
    # The RageCandyBar seller in Gold and Silver: waitsfx and playsound SFX_TRANSACTION before paying.
    charge(ram, [0x1F, POTION, 1, *no_space, 0x85, 0x84, 0x22, 0x00, *takemoney()])
    pb.run('Script_takemoney')
    # The item can come from wCurItem.
    ram.put('wCurItem', TM01)
    charge(ram, [0x1F, 0xFF, 2, *no_space, *takemoney()])
    pb.run('Script_takemoney')
    assert counts(ledger.store, 'bought') == {POTION: 2, TM01: 2}
    # A haircut or the Route 43 toll charges for no item, and a sale from another account is not one.
    for script in ([0x22, 0x00, 0x00, 0x05, 0x00, 0x06, 0x02, 0x34, 0x12, *takemoney()],
                   [0x1F, POTION, 1, *no_space, 0x84, 0x84, 0x22, 0x00, *takemoney()],
                   [0x1F, POTION, 1, *no_space, *takemoney(account=1)]):
        charge(ram, script)
        pb.run('Script_takemoney')
    assert counts(ledger.store, 'bought') == {POTION: 2, TM01: 2}


def test_the_contest_pokemon_kept_counts_as_caught_once_beside_other_catches(tmp_path):
    from pokesim.gen2.tracking import CAPTURES, Tracker, contest_keep_hook
    store, data, pb = Store(tmp_path), fake_data(), Emulator()
    activity.start(store, fresh=True)
    tracker = Tracker(store, data, fresh=True)
    assert contest_keep_hook(pb.memory, data) == CODE['CheckPartyFullAfterContest']
    pb.hook_register(*contest_keep_hook(pb.memory, data), tracker.contest_kept, pb)
    ram = pb.memory
    pb.run('CheckPartyFullAfterContest')  # the player caught nothing
    # A contest catch is not a capture until the contest ends with it.
    for name, value in (('wWildMon', 123), ('wBattleMode', 1), ('wBattleType', 6)):
        ram.put(name, value)
    tracker.captured(pb)
    ram.put('wContestMonSpecies', 123)
    pb.run('CheckPartyFullAfterContest')
    pb.run('CheckPartyFullAfterContest')  # a reload replays the same moment
    assert counts(store, 'caught') == {123: 1}
    assert (store.get(CAPTURES)['counts'], store.get(CAPTURES)['total']) == ({'123': 1}, 1)
    # An adventure that starts counting later counts it from its receipt, once.
    later = Store(tmp_path / 'later')
    with later.lock, later.db:
        later.db.execute('CREATE TABLE capture_receipts '
                         '(fingerprint TEXT PRIMARY KEY, dex INTEGER NOT NULL, recorded_at REAL NOT NULL)')
        later.db.executemany('INSERT INTO capture_receipts VALUES (?,?,?)',
                             store.db.execute('SELECT * FROM capture_receipts').fetchall())
    activity.start(later, fresh=False)
    assert counts(later, 'caught') == {123: 1}
    ram.raw[CODE['CheckPartyFullAfterContest'][1]] = 0
    with pytest.raises(ValueError):
        contest_keep_hook(ram, data)


def test_store_stock_reports_every_landed_purchase(real_data, monkeypatch):
    from pokesim.gen2.store_stock import StoreStock
    seen = []
    stock = StoreStock(real_data, on_bought=seen.append)
    # A plain mart that carries no Champion stock still reports the purchase.
    monkeypatch.setattr(stock, 'mart', lambda pb: None)
    stock.bought('pb')
    assert seen == ['pb']


def test_gifts_and_npc_trades_count_once(ledger):
    store = ledger.store
    with store.lock, store.db:
        activity.gift(store.db, 'abc', 151)
        activity.gift(store.db, 'abc', 151)
    trade = SimpleNamespace(index=2, request=16, give=95)
    activity.npc_trade(store, trade)
    activity.npc_trade(store, trade)
    assert counts(store, 'gift') == {151: 1}
    assert counts(store, 'traded_out') == {16: 1} and counts(store, 'traded_in') == {95: 1}


def managed_receipt(identity, sent, received):
    struct = bytes([sent]) + bytes(47)
    return {'id': identity, 'decision': 'COMMIT', 'phase': 'released', 'outgoing': {'struct': struct.hex()},
            'staged': {'evidence': {'received_species': received}}}


def test_gen2_cable_trades_are_recorded_by_national_number(tmp_path):
    store = Store(tmp_path)
    with store.lock, store.db:
        trade_statistics.managed(store.db, managed_receipt('one', 152, 251))
        trade_statistics.managed(store.db, managed_receipt('one', 152, 251))
        assert not trade_statistics.record_gen2(store.db, 'bad', 0, 252)
    assert counts(store, 'traded_out') == {152: 1} and counts(store, 'traded_in') == {251: 1}


def test_an_adventure_under_way_counts_from_now_and_keeps_its_history(tmp_path):
    store = Store(tmp_path)
    with store.lock, store.db:
        store.db.execute('CREATE TABLE capture_receipts '
                         '(fingerprint TEXT PRIMARY KEY, dex INTEGER NOT NULL, recorded_at REAL NOT NULL)')
        for index, dex in enumerate((19, 19, 41)):
            store.db.execute('INSERT INTO capture_receipts VALUES (?,?,?)', (f'catch-{index}', dex, 1.0))
        store.db.execute('INSERT INTO capture_receipts VALUES (?,?,?)', ('gift-event:x', 151, 1.0))
        store.db.execute('INSERT INTO kv VALUES (?,?)', ('managed_interaction:old',
                                                         json.dumps(managed_receipt('old', 4, 7))))
    before = time.time()
    activity.start(store, fresh=False)
    activity.start(store, fresh=True)
    assert counts(store, 'caught') == {19: 2, 41: 1}
    assert counts(store, 'traded_out') == {4: 1} and counts(store, 'traded_in') == {7: 1}
    result = gen2_status(fake_data(), {'party': [], 'items': [{'id': POTION, 'qty': 2}]}, store)
    assert result['counting_since'] >= before and result['started_at'] == result['counting_since']
    assert result['trade_records']['missing_history'] == 0
    rows = {row['id']: row for row in result['pokemon']}
    assert rows[19]['caught'] == 2 and rows[16]['wild'] == 0 and rows[4]['traded_out'] == 1
    items = {row['id']: row for row in result['items']}
    assert set(items) == {POKE_BALL, POTION, BICYCLE, TM01, HM01}
    assert items[POTION] == {'id': POTION, 'name': 'Potion', 'bought': 0, 'used': 0, 'bag': 2}
    assert items[BICYCLE]['used'] is None and items[HM01]['used'] is None and items[TM01]['used'] == 0


def test_a_new_adventure_has_its_whole_history(ledger):
    result = gen2_status(ledger.data, None, ledger.store)
    assert result['started_at'] and result['counting_since'] is None and result['available']
    assert result['pokemon'][0]['held'] is None and result['pokemon'][0]['wild'] == 0


def test_before_tracking_starts_counts_stay_unknown(tmp_path):
    result = gen2_status(fake_data(), None, Store(tmp_path))
    assert result['started_at'] is None and result['counting_since'] is None
    assert result['pokemon'][0]['wild'] is None and result['items'][0]['bought'] is None


def test_catches_are_counted_as_they_are_kept(tmp_path):
    from pokesim.gen2.tracking import Tracker
    store, data, pb = Store(tmp_path), fake_data(), Emulator()
    activity.start(store, fresh=True)
    ram = pb.memory
    for name, value in (('wWildMon', 19), ('wBattleMode', 1), ('wBattleType', 0)):
        ram.put(name, value)
    tracker = Tracker(store, data, fresh=True)
    tracker.captured(pb)
    tracker.captured(pb)
    assert counts(store, 'caught') == {19: 1}


def test_red_blue_and_yellow_adventures_counted_from_an_earlier_release_show_when(tmp_path):
    store = Store(tmp_path)
    store.set(KEY, {'started_at': 1_700_000_000, 'available': True})
    assert status(store)['counting_since'] is None
    with store.db:
        store.db.execute("INSERT INTO events(ts,type,title) VALUES (1600000000,'map','Pallet Town')")
    assert status(store)['counting_since'] == 1_700_000_000
    store.set(KEY, {'started_at': 1_700_000_000, 'available': True, 'complete_history': True})
    assert status(store)['counting_since'] is None


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def test_real_cartridges_take_every_hook_beside_the_others(real_data, tmp_path):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    from pokecore.gen2.clock import boot
    from pokesim.gen2.steps import StepTracker
    from pokesim.gen2.store_stock import StoreStock
    from pokesim.gen2.tracking import Tracker
    pb = boot(io.BytesIO((Path(directory) / (real_data.game + '.gbc')).read_bytes()), sound=False)
    try:
        store = Store(tmp_path)
        assert len(activity.hooks(pb.memory, real_data)) == 7
        # In the emulator's own order. A placed hook changes the code it sits on, so a later
        # signature that overlapped it would fail here, as would a second hook at one address.
        Tracker(store, real_data, fresh=True).attach(pb)
        ledger = activity.Ledger(store, real_data, fresh=True)
        ledger.attach(pb)
        StepTracker(store, real_data).attach(pb)
        assert StoreStock(real_data, on_bought=ledger.bought).attach(pb)
        assert store.get(KEY)['available'] is True and store.get(KEY)['started_at']
    finally:
        pb.stop(save=False)


def test_a_bargain_shop_purchase_counts_through_the_buy_menu_hook(real_data, tmp_path):
    from test_gen2_shiny import Ram as Bus
    from pokesim.gen2.store_stock import StoreStock
    store, ram = Store(tmp_path), Bus(real_data)
    activity.start(store, True)
    ledger = activity.Ledger(store, real_data, fresh=True)
    stock = StoreStock(real_data, on_bought=ledger.bought)
    # BargainShop opens the same BuyMenu, so its purchases land at the same hook as a mart's.
    bank, address = real_data.symbols['BargainShopData']
    ram.put('wMartPointerBank', bank)
    ram.put('wMartPointer', bytes(word(address)))
    nugget = real_data.items['NUGGET']
    ram.put('wCurItem', nugget)
    ram.put('wItemQuantityChange', 1)
    pb = SimpleNamespace(memory=ram)
    stock.bought(pb)
    stock.bought(pb)
    assert stock.mart(pb) is None and counts(store, 'bought') == {nugget: 1}


def release_session(store, data):
    """Verify, stage and release a two-trade cable session through the code a real one runs."""
    from test_gen2_shiny import PLAIN, hexed, receiving, struct
    from test_managed_participant import committed
    from pokesim.gen2.manual_session import verify_parties
    from pokesim.runtime.participant import PREFIX, Participant
    name, mine, theirs = (bytes.fromhex(code + '5050505050505050') for code in ('808182', '808182', '909192'))

    def row(species, trainer):
        return {'struct': struct(species, PLAIN), 'nickname': name, 'trainer': trainer}
    left, right = [row(1, mine), row(4, mine), row(7, mine)], [row(152, theirs), row(155, theirs), row(158, theirs)]
    # Two trades: Charmander for Chikorita, then Squirtle for Cyndaquil.
    after = ([left[0], right[0], right[1]], [left[1], left[2], right[2]])
    evidence = verify_parties((left, right), after, (2, 2))
    record = committed(store)
    record.update(cartridge_generation=2, session=True)
    receiving(data).incoming_record(record, {'result': {'party_before': [hexed(item) for item in left],
                                                        'party_after': [hexed(item) for item in after[0]]}})
    record['staged']['evidence'] = evidence[0]
    record['phase'] = 'applied'
    store.set(PREFIX + record['id'], record)
    participant = Participant(SimpleNamespace(store=store, emulator=None), SimpleNamespace())
    participant.emu = SimpleNamespace(paused=True, policy=SimpleNamespace(on_restore=lambda: None), stuck_since=0)
    participant.release({'id': record['id']})
    participant.release({'id': record['id']})


def test_every_pokemon_a_cable_session_trades_is_counted_once(real_data, tmp_path):
    store = Store(tmp_path)
    activity.start(store, True)
    release_session(store, real_data)
    assert counts(store, 'traded_out') == {4: 1, 7: 1} and counts(store, 'traded_in') == {152: 1, 155: 1}
    # The backfill of released history finds the same receipts and counts nothing twice.
    with store.lock, store.db:
        assert trade_statistics._history(store.db) == 0
    assert counts(store, 'traded_out') == {4: 1, 7: 1} and counts(store, 'traded_in') == {152: 1, 155: 1}


class CartridgeBus:
    """Cartridge ROM banks, with a flat RAM for the script engine's own bytes."""
    def __init__(self, rom, data):
        from test_gen2_shiny import Ram as Bus
        self.rom, self.ram = rom, Bus(data)

    def __getitem__(self, key):
        bank, where = key
        if where.start >= 0x8000:
            return self.ram[key]
        start = (bank * 0x4000 + where.start - 0x4000) if where.start >= 0x4000 else where.start
        return self.rom[start:start + where.stop - where.start]


def sales(bus, data, label, span=0xC0):
    """What activity.vended reads at each ``takemoney YOUR_MONEY`` in the script at label."""
    from pokecore.gen2.ram import Memory
    bank, start = data.symbols[label]
    found = []
    for position in range(start, start + span):
        if bus[bank, position - 1:position + 1] == b'\x23\x00':
            bus.ram.put('wScriptBank', bank)
            bus.ram.put('wScriptPos', bytes(word(position)))
            found.append(activity.vended(bus, Memory(bus, data)))
    return found


def test_the_cartridge_sale_scripts_read_as_purchases_and_the_other_payments_do_not(real_data):
    from pokecore.gen2.hooks import mart_hooks
    from pokesim.gen2.tracking import contest_keep_hook
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    bus = CartridgeBus((Path(directory) / (real_data.game + '.gbc')).read_bytes(), real_data)
    items = real_data.items
    drinks = [(items[name], 1) for name in ('FRESH_WATER', 'SODA_POP', 'LEMONADE')]
    for label, sold in (('GoldenrodVendingMachine', drinks), ('CeladonDeptStore6FVendingMachine', drinks),
                        ('FarmerMScript_SellMilk', [(items['MOOMOO_MILK'], 1)]),
                        ('MahoganyTownPokefanMScript', [(items['RAGECANDYBAR'], 1)])):
        assert [sale for sale in sales(bus, real_data, label) if sale] == sold, label
    for label in ('OlderHaircutBrotherScript', 'YoungerHaircutBrotherScript', 'RocketScript_TollSouth',
                  'RocketScript_TollNorth'):
        charges = sales(bus, real_data, label)
        assert charges and not any(charges), label
    # BargainShop calls BuyMenu, whose loop holds the hook that counts every BUY menu purchase.
    bank, address = real_data.symbols['BargainShop']
    assert b'\xcd' + bytes(word(real_data.symbols['BuyMenu'][1])) in bus[bank, address:address + 0x20]
    hook = mart_hooks(bus, real_data)['bought']
    assert hook[0] == real_data.symbols['BuyMenuLoop'][0] and 0 < hook[1] - real_data.symbols['BuyMenuLoop'][1] < 160
    assert contest_keep_hook(bus, real_data) == tuple(real_data.symbols['CheckPartyFullAfterContest'])
