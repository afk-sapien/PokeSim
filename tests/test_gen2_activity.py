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
        'wWildMon': 0xD20C, 'wEnemyMonDVs': 0xD206}
CODE = {'InitEnemyWildmon': (0x0F, 0x5000), 'LoadEnemyMonToSwitchTo': (0x0F, 0x5100),
        'FaintEnemyPokemon': (0x0F, 0x5200), 'UseDisposableItem': (0x03, 0x5300), 'ConsumeTM': (0x03, 0x5400),
        'PokeBallEffect': (0x03, 0x5500), 'TossItem': (0, 0x2F66), 'WaitSFX': (0, 0x3C55),
        'ConvertCurItemIntoCurTMHM': (0, 0x2F20)}
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


def test_hooks_sit_at_the_six_checked_sites():
    rows = activity.hooks(cartridge(), fake_data())
    assert [kind for kind, _, _ in rows] == ['wild', 'trainer', 'defeated', 'used', 'used', 'used']
    assert (0x03, 0x5400 + 17) in [(bank, address) for _, bank, address in rows]
    assert (0x03, 0x5580) in [(bank, address) for _, bank, address in rows]


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
        assert len(activity.hooks(pb.memory, real_data)) == 6
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
