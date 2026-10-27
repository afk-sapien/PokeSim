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
    from pokecore.gen2.clock import boot
    from pokecore.gen2.hooks import encounter_hook
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    pb = boot(io.BytesIO((Path(directory) / (real_data.game + '.gbc')).read_bytes()), sound=False)
    try:
        bank, address = encounter_hook(pb.memory, real_data)
        assert (bank, address) == (0x0F, 0x7CAA if real_data.game == 'crystal' else 0x7CBA)
    finally:
        pb.stop(save=False)


def test_a_shiny_bug_contest_catch_is_acquired_once(real_data, tmp_path):
    from pokesim.gen2.tracking import Tracker
    store = Store(tmp_path)
    tracker = Tracker(store, real_data, fresh=True)
    scyther = battle(real_data, species=123, kind=6)
    tracker.encountered(scyther)
    tracker.contest_caught(scyther)
    tracker.contest_caught(scyther)  # a reload replays the same catch
    for ignored in (battle(real_data, species=10, kind=6, dvs=PLAIN), battle(real_data, species=10, kind=7)):
        tracker.contest_caught(ignored)
    result = shiny.status(store, 2)
    assert (result['seen'], result['acquired'], result['acquired_species']) == (1, 1, [123])
    # A contest Pokémon is not a capture until it joins the team.
    assert not store.get('capture-statistics-v1')['total']
    store.close()


def test_contest_catch_hook_resolves_on_the_cartridge(real_data):
    from pokecore.gen2.clock import boot
    from pokecore.gen2.hooks import contest_hook
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    pb = boot(io.BytesIO((Path(directory) / (real_data.game + '.gbc')).read_bytes()), sound=False)
    try:
        bank, address = contest_hook(pb.memory, real_data)
        start = real_data.symbols['BugContest_SetCaughtContestMon'][1]
        # Past the swap question: two farcalls, its name, the YES/NO box and ``ret c``.
        assert (bank, address) == (3, start + 28)
    finally:
        pb.stop(save=False)


def cartridge(real_data):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    return (Path(directory) / (real_data.game + '.gbc')).read_bytes()


def rom_table(rom, data, name, width, count):
    bank, address = data.symbols[name]
    start = bank * 0x4000 + address - 0x4000
    return [rom[start + width * index:start + width * (index + 1)] for index in range(count)]


EGG_NAME = bytes.fromhex('8486865050505050505050')


def party(data, members):
    """A party of (species byte, 48-byte struct) rows on the flat test bus."""
    ram = Ram(data)
    ram.put('wPartyCount', len(members))
    ram.put('wPartySpecies', bytes(kind for kind, _ in members) + b'\xff')
    _, address = data.symbols['wPartyMons']
    for slot, (_, raw) in enumerate(members):
        ram.raw[address + slot * 48:address + (slot + 1) * 48] = raw
    return SimpleNamespace(memory=ram)


def struct(species, dvs, cycles=0):
    raw = bytearray(48)
    # The trainer ID tells individuals apart, as a trade fingerprint does.
    raw[0], raw[6], raw[21:23], raw[27], raw[31] = species, species, dvs, cycles, 5
    return bytes(raw)


def test_a_shiny_egg_is_acquired_once_when_it_hatches(real_data, tmp_path):
    from pokesim.gen2.tracking import EGG, Tracker
    store = Store(tmp_path)
    tracker = Tracker(store, real_data, fresh=True)
    members = [(130, struct(130, SHINY, 70)),           # a shiny partner already hatched or caught
               (EGG, struct(175, SHINY)),               # Togepi, cycles run out: hatches now
               (EGG, struct(246, SHINY, 5)),            # still five cycles to go
               (EGG, struct(147, PLAIN))]               # hatches, but not shiny
    hatching = party(real_data, members)
    tracker.hatching(hatching)
    tracker.hatching(hatching)  # a reload replays the same hatch
    result = shiny.status(store, 2)
    assert (result['acquired'], result['acquired_species'], result['seen']) == (1, [175], 0)
    # A later hatch of an identical Egg is a separate one.
    hatching.memory.put('wPlayerID', b'\x12\x34')
    tracker.hatching(hatching)
    assert shiny.status(store, 2)['acquired'] == 2
    # A hatch is not a capture.
    assert not store.get('capture-statistics-v1')['total']
    store.close()


def test_a_shiny_odd_egg_is_acquired_when_it_hatches(real_data, tmp_path):
    from pokesim.gen2.tracking import EGG, Tracker
    if real_data.game != 'crystal':
        pytest.skip('Only Crystal has the Odd Egg')
    eggs = rom_table(cartridge(real_data), real_data, 'OddEggs', 59, 14)
    # Each baby comes as a plain Egg and a shiny one, both named EGG.
    assert [egg[0] for egg in eggs[1::2]] == [172, 173, 174, 238, 240, 239, 236]
    assert all(shiny.shiny_bytes(egg[21:23]) and not shiny.shiny_bytes(plain[21:23]) and egg[48:] == EGG_NAME
               for plain, egg in zip(eggs[::2], eggs[1::2]))
    store = Store(tmp_path)
    tracker = Tracker(store, real_data, fresh=True)
    pichu = bytearray(eggs[1][:48])
    pichu[27] = 0
    tracker.hatching(party(real_data, [(EGG, bytes(pichu))]))
    assert shiny.status(store, 2)['acquired_species'] == [172]
    store.close()


def test_no_in_game_trade_gives_a_shiny(real_data):
    """The in-game trades give fixed DVs from the cartridge, and none of them is shiny, so they need no receipt."""
    from pokesim.gen2.npc_trades import trades
    rows = rom_table(cartridge(real_data), real_data, 'NPCTrades', 32, len(trades(real_data.game)))
    assert [(row[1], row[2]) for row in rows] == [(trade.request, trade.give) for trade in trades(real_data.game)]
    assert not any(shiny.shiny_bytes(row[14:16]) for row in rows)


def receiving(data):
    from pokesim.gen2 import trading
    participant = trading.Participant.__new__(trading.Participant)
    participant.emu = SimpleNamespace(data=data)
    return participant


def hexed(row):
    return {key: value.hex() for key, value in row.items()}


def test_a_shiny_received_in_a_pokesim_trade_is_acquired_once_on_the_receiving_side(real_data, tmp_path):
    from test_managed_participant import committed
    from pokesim.runtime.participant import _promote
    trainer = bytes.fromhex('8081825050505050505050')
    kadabra = bytearray(struct(64, SHINY))
    kadabra[1] = 0  # no Everstone, so it evolves on arrival
    store = Store(tmp_path)
    record = committed(store)
    record['cartridge_generation'] = 2
    receiving(real_data).incoming_record(record, {'incoming': hexed({'struct': bytes(kadabra), 'nickname': trainer,
                                                                     'trainer': trainer})})
    _promote(store, record)
    _promote(store, record)  # recovery retries the same commit
    assert (shiny.status(store, 2)['acquired'], shiny.status(store, 2)['acquired_species']) == (1, [65])
    # A plain Pokémon counts nothing.
    plain = committed(store)
    plain['cartridge_generation'] = 2
    receiving(real_data).incoming_record(plain, {'incoming': hexed({'struct': struct(130, PLAIN), 'nickname': trainer,
                                                                    'trainer': trainer})})
    _promote(store, plain)
    assert shiny.status(store, 2)['acquired'] == 1
    store.close()


def test_an_owner_driven_session_counts_each_shiny_received_but_not_eggs(real_data, tmp_path):
    from test_managed_participant import committed
    from pokesim.runtime.participant import _promote
    trainer = bytes.fromhex('8081825050505050505050')
    name = bytes.fromhex('8081825050505050505050')
    kept, sent = struct(1, PLAIN), struct(4, SHINY)
    got = [struct(130, SHINY), struct(25, PLAIN), struct(175, SHINY)]
    before = [{'struct': kept, 'nickname': name, 'trainer': trainer}] + [
        {'struct': sent, 'nickname': name, 'trainer': trainer}, {'struct': struct(7, PLAIN), 'nickname': name, 'trainer': trainer},
        {'struct': struct(10, PLAIN), 'nickname': name, 'trainer': trainer}]
    after = [{'struct': kept, 'nickname': name, 'trainer': trainer},
             {'struct': got[0], 'nickname': name, 'trainer': trainer},
             {'struct': got[1], 'nickname': name, 'trainer': trainer},
             {'struct': got[2], 'nickname': EGG_NAME, 'trainer': trainer}]  # an Egg counts when it hatches
    store = Store(tmp_path)
    record = committed(store)
    record.update(cartridge_generation=2, session=True)
    receiving(real_data).incoming_record(record, {'result': {'party_before': [hexed(row) for row in before],
                                                             'party_after': [hexed(row) for row in after]}})
    _promote(store, record)
    _promote(store, record)
    assert (shiny.status(store, 2)['acquired'], shiny.status(store, 2)['acquired_species']) == (1, [130])
    store.close()


def test_gen1_trades_keep_the_gen2_ledger_untouched(tmp_path):
    from test_managed_participant import committed
    from pokesim.runtime.participant import _promote
    store = Store(tmp_path)
    record = committed(store)
    record['incoming_shiny'] = [130]  # a Red, Blue or Yellow record never carries it, and never counts it
    _promote(store, record)
    assert shiny.status(store, 2)['acquired'] == 0
    store.close()


def test_pokedex_marks_shiny_species_acquired_held_and_seen(real_data, tmp_path):
    from pokesim.gen2.tracking import apply
    store = Store(tmp_path)
    with store.db:
        shiny.start(store.db, 2, available=True, fresh=True)
        shiny.record(store.db, 'acquired', 'a', 130, generation=2)  # Gyarados credits Magikarp
        shiny.record(store.db, 'seen', 'b', 41, generation=2)
        shiny.record(store.db, 'seen', 'a', 130, generation=2)
    payload = {'party': [{'dex': 175, 'species': 175, 'shiny': True, 'egg': False},
                         {'dex': 152, 'species': 152, 'shiny': True, 'egg': True}], 'storage': None}
    result = apply(payload, store, real_data)['shiny']
    assert result['collection_species'] == [129, 130, 175]
    assert (result['seen_species'], result['held'], result['held_species']) == ([41, 130], 1, [175])
    store.close()
