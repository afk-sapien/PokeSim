"""Shiny wild encounters and catches on the 251-species cartridges."""
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pokesim import adventure_records, shiny
from pokesim.gen2.data import GameData
from pokesim.store import Store

SHINY, PLAIN = b'\x2a\xaa', b'\xff\xff'


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


class Ram:
    """A flat 64 KiB bus that answers both banked and unbanked reads."""
    def __init__(self, data):
        self.data, self.raw = data, bytearray(0x10000)

    def __getitem__(self, key):
        return self.raw[key[1] if isinstance(key, tuple) else key]

    def __setitem__(self, key, value):
        self.raw[key[1] if isinstance(key, tuple) else key] = value

    def put(self, name, value):
        _, address = self.data.symbols[name]
        value = bytes([value]) if isinstance(value, int) else value
        self.raw[address:address + len(value)] = value


def battle(data, *, species=130, mode=1, kind=7, dvs=SHINY):
    ram = Ram(data)
    for name, value in (('wBattleMode', mode), ('wBattleType', kind), ('wEnemyMonSpecies', species),
                        ('wWildMon', species), ('wEnemyMonDVs', dvs)):
        ram.put(name, value)
    return SimpleNamespace(memory=ram)


def test_shiny_wild_encounters_and_catches_are_counted_once(real_data, tmp_path):
    from pokesim.gen2.tracking import Tracker
    store = Store(tmp_path)
    tracker = Tracker(store, real_data, fresh=True)
    gyarados = battle(real_data)
    tracker.encountered(gyarados)
    tracker.encountered(gyarados)
    tracker.captured(gyarados)
    tracker.captured(gyarados)
    for ignored in (battle(real_data, dvs=PLAIN), battle(real_data, mode=2), battle(real_data, kind=3)):
        tracker.encountered(ignored)
        tracker.captured(ignored)
    result = shiny.status(store, 2)
    assert (result['seen'], result['acquired'], result['seen_species'], result['acquired_species']) == (1, 1, [130], [130])
    assert result['available'] and result['complete_history']
    assert shiny.status(store)['seen'] == 0
    tracker.reset()
    assert shiny.status(store, 2)['seen'] == 0
    store.close()


def test_gen2_ledger_counts_all_251_species_without_touching_gen1(tmp_path):
    store = Store(tmp_path)
    with store.db:
        shiny.start(store.db, 2, available=True)
        assert shiny.record(store.db, 'acquired', 'a', 251, generation=2)
        assert not shiny.record(store.db, 'acquired', 'a', 251, generation=2)
        for dex, generation in ((252, 2), (152, 1)):
            with pytest.raises(ValueError):
                shiny.record(store.db, 'acquired', 'b', dex, generation=generation)
    assert shiny.status(store, 2)['acquired_species'] == [251]
    assert shiny.status(store)['acquired'] == 0
    store.close()


def test_transformed_ditto_reports_its_own_dvs(real_data):
    from pokesim.gen2.ram import read_snapshot
    mon = battle(real_data, species=132, dvs=PLAIN)
    mon.memory.put('wEnemyBackupDVs', SHINY)
    assert not read_snapshot(mon.memory, real_data, cache=False).enemy_shiny
    mon.memory.put('wEnemySubStatus5', 8)
    assert read_snapshot(mon.memory, real_data, cache=False).enemy_shiny
    mon.memory.put('wBattleMode', 2)
    assert not read_snapshot(mon.memory, real_data, cache=False).enemy_shiny


def test_gen2_statistics_and_first_shiny_milestone_use_receipts(tmp_path):
    from tests.test_visual_pass_fixes import gen2_emulator
    from pokesim.web.app import create_app
    store = Store(tmp_path)
    with store.db:
        shiny.start(store.db, 2, available=True, fresh=True)
        shiny.record(store.db, 'seen', 'a', 130, generation=2)
        shiny.record(store.db, 'acquired', 'a', 130, generation=2)
    record = TestClient(create_app(gen2_emulator(), store)).get('/api/statistics').json()['collection_records']['shiny']
    assert (record['available'], record['seen'], record['acquired'], record['held']) == (True, 1, 1, 0)
    tracker = adventure_records.RecordTracker(store, generation=2)
    snapshot = SimpleNamespace(badges=0, hall_of_fame_count=0, owned=frozenset(), party=(), stored=())
    assert tracker.conditions(snapshot)[5]


def test_wild_shiny_hook_resolves_on_the_cartridge(real_data):
    from pokesim.gen2.core import boot
    from pokesim.gen2.tracking import encounter_hook
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    pb = boot(io.BytesIO((Path(directory) / (real_data.game + '.gbc')).read_bytes()), sound=False)
    try:
        bank, address = encounter_hook(pb, real_data)
        assert (bank, address) == (0x0F, 0x7CAA if real_data.game == 'crystal' else 0x7CBA)
    finally:
        pb.stop(save=False)
