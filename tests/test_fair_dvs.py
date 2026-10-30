"""Fair wild DVs: the optional Generation I setting that replaces correlated wild DVs."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from pokesim import config, fair_dvs
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import Registry, identifier
from pokesim.runtime.settings import SimulationSettings
from pokesim.shiny import ShinyTracker, status
from pokesim.store import Store

RED = 'ea9bcae617fdf159b045185467ae58b2e4a48b9a'
ROOT = Path(__file__).resolve().parents[1]
ROM = Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb'))
REROLL = fair_dvs.reroll
CHECKPOINT = Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios' / 'mt-moon-side-project' / 'start.state'


def wild_memory(dvs=b'\x98\x88'):
    memory = bytearray(65536)
    memory[0xcfe5] = 153
    memory[0xcff1:0xcff3] = dvs
    memory[0xd057] = 1
    return memory


def test_setting_defaults_off_and_must_be_a_boolean(tmp_path):
    from dataclasses import fields
    assert next(field for field in fields(SimulationSettings) if field.name == 'fair_wild_dvs').default is False
    assert Manager.validate_adventure_settings({'fair_wild_dvs': True})['fair_wild_dvs'] is True
    # Off is stored as absent, so releases without the setting still open the adventure.
    assert 'fair_wild_dvs' not in Manager.validate_adventure_settings({'fair_wild_dvs': False})
    with pytest.raises(ValueError, match='boolean'):
        Manager.validate_adventure_settings({'fair_wild_dvs': 1})


def test_registry_keeps_the_setting_and_refuses_it_for_generation_ii(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('red-rom', 'sha1', 'red')
    registry.add_rom('gold-rom', 'sha2', 'gold')
    row = registry.create('Red', 'red-rom', {'fair_wild_dvs': True}, identifier())
    registry.close()
    assert Registry(tmp_path).adventure(row['id'])['settings']['fair_wild_dvs'] is True
    with pytest.raises(ValueError, match='Red, Blue and Yellow'):
        Registry(tmp_path).create('Gold', 'gold-rom', {'fair_wild_dvs': True}, identifier())


def test_library_api_turns_it_on_and_off_only_for_generation_i(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        manager.registry.add_rom('red-rom', 'sha1', 'red')
        manager.registry.add_rom('gold-rom', 'sha2', 'gold')
        red = client.post('/api/v1/adventures', headers=headers, json={'name': 'Red', 'rom_id': 'red-rom'}).json()
        assert 'fair_wild_dvs' not in red['settings']
        route = f"/api/v1/adventures/{red['id']}"
        on = client.patch(route, headers=headers, json={'settings': {'fair_wild_dvs': True}}).json()
        assert on['settings']['fair_wild_dvs'] is True
        off = client.patch(route, headers=headers, json={'settings': {'fair_wild_dvs': False}}).json()
        assert 'fair_wild_dvs' not in off['settings']
        gold = client.post('/api/v1/adventures', headers=headers, json={'name': 'Gold', 'rom_id': 'gold-rom'}).json()
        refused = client.patch(f"/api/v1/adventures/{gold['id']}", headers=headers,
                               json={'settings': {'fair_wild_dvs': True}})
        assert refused.status_code == 409 and 'Red, Blue and Yellow' in refused.text


def test_generation_ii_refuses_a_policy_it_cannot_play(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('red-rom', 'sha1', 'red')
    registry.add_rom('gold-rom', 'sha2', 'gold')
    assert registry.create('Red', 'red-rom', {'policy': 'smart_random'}, identifier())['settings']['policy'] == 'smart_random'
    assert registry.create('Gold', 'gold-rom', {'policy': 'strategic'}, identifier())
    with pytest.raises(ValueError, match='strategic policy only'):
        registry.create('Gold', 'gold-rom', {'policy': 'guided_random'}, identifier())


def test_chosen_at_creation_and_changed_while_running_but_the_randomizer_stays_locked(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    pushed = []
    monkeypatch.setattr(manager.supervisor, 'push_fair_wild_dvs', lambda aid: pushed.append(aid) or False)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        manager.registry.add_rom('red-rom', 'sha1', 'red')
        red = client.post('/api/v1/adventures', headers=headers,
                          json={'name': 'Red', 'rom_id': 'red-rom', 'fair_wild_dvs': True, 'randomizer': 'PSR1-RED-W-5'}).json()
        assert red['settings']['fair_wild_dvs'] is True and red['settings']['randomizer'] == 'PSR1-RED-W-5'
        route = f"/api/v1/adventures/{red['id']}"
        manager.registry.update(red['id'], state='running')
        off = client.patch(route, headers=headers, json={'settings': {'fair_wild_dvs': False}})
        assert off.status_code == 200 and 'fair_wild_dvs' not in off.json()['settings']
        assert off.json()['fair_wild_dvs_pending'] is False and pushed == [red['id']]
        # Other rewards still wait for a stop, and the randomizer never changes.
        assert client.patch(route, headers=headers, json={'settings': {'league_rewards': False}}).status_code == 409
        for change in ('', 'PSR1-RED-WS-5'):
            refused = client.patch(route, headers=headers, json={'settings': {'randomizer': change}})
            assert refused.status_code == 409 and 'creating an adventure' in refused.text
        assert manager.registry.adventure(red['id'])['settings']['randomizer'] == 'PSR1-RED-W-5'


def test_a_live_change_takes_effect_on_the_next_encounter(tmp_path, monkeypatch):
    from pokesim.emulator import Emulator
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', False, raising=False)
    with closing(Store(tmp_path)) as store:
        emu = object.__new__(Emulator)
        emu.shiny_tracker = ShinyTracker(store, RED)
        assert emu.set_fair_wild_dvs(True) == {'fair_wild_dvs': True}
        memory = wild_memory()
        emu.shiny_tracker.encounter(SimpleNamespace(memory=memory))
        assert memory[0xcff1:0xcff3] != b'\x98\x88'
        assert emu.set_fair_wild_dvs(False) == {'fair_wild_dvs': False}
        memory = wild_memory()
        emu.shiny_tracker.encounter(SimpleNamespace(memory=memory))
        assert memory[0xcff1:0xcff3] == b'\x98\x88'


def test_off_leaves_the_cartridge_dvs_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', False, raising=False)
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, RED)
        memory = wild_memory()
        tracker.encounter(SimpleNamespace(memory=memory))
        assert memory[0xcff1:0xcff3] == b'\x98\x88'
        assert store.get(fair_dvs.KEY) is None


def test_on_replaces_wild_dvs_before_the_shiny_check(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', True, raising=False)
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, RED)
        memory = wild_memory()
        before = bytes(memory)
        tracker.encounter(SimpleNamespace(memory=memory))
        written = bytes(memory[0xcff1:0xcff3])
        assert written != b'\x98\x88'
        # The same saved moment gives the same Pokémon, as on the cartridge.
        assert ShinyTracker(store, RED).fair_key == tracker.fair_key
        again = bytearray(before)
        fair_dvs.reroll(again, tracker.fair_key)
        assert bytes(again[0xcff1:0xcff3]) == written
        # A shiny the reroll produces is counted as seen.
        monkeypatch.setattr(fair_dvs, 'reroll', lambda mem, key: mem.__setitem__(slice(0xcff1, 0xcff3), b'\x2a\xaa'))
        tracker.encounter(SimpleNamespace(memory=wild_memory()))
        assert status(store)['seen'] == 1


@pytest.mark.parametrize('address,value', [
    (0xd057, 2),     # trainer battle, fixed DVs
    (0xd069, 8),     # Transform restoring the original DVs
    (0xd12b, 5),     # cable battle
    (0xd05a, 1),     # the old man's catching tutorial
])
def test_on_never_touches_trainer_transform_link_or_tutorial_dvs(tmp_path, monkeypatch, address, value):
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', True, raising=False)
    with closing(Store(tmp_path)) as store:
        tracker = ShinyTracker(store, RED)
        memory = wild_memory()
        memory[address] = value
        tracker.encounter(SimpleNamespace(memory=memory))
        assert memory[0xcff1:0xcff3] == b'\x98\x88'


def test_rerolled_bytes_cover_the_whole_range():
    key = bytes(32)
    firsts, seconds = set(), set()
    for n in range(4096):
        memory = wild_memory()
        memory[0xd000:0xd002] = n.to_bytes(2, 'big')
        a, b = fair_dvs.reroll(memory, key)
        firsts.add(a)
        seconds.add(b)
    assert len(firsts) == len(seconds) == 256


def test_unverified_cartridges_never_reroll(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', True, raising=False)
    with closing(Store(tmp_path)) as store:
        assert ShinyTracker(store, 'unknown').fair_key is None


def wild_encounters(tmp_path, monkeypatch, count=3, headless=None):
    """Play from a private Viridian Forest checkpoint and return the DVs at each storeDVs and in battle.
    ``headless`` is a key the headless run rerolls with instead of an adventure's tracker."""
    from pokesim.headless import HeadlessRun
    from pokesim.ram import read_snapshot
    monkeypatch.setattr(config, 'FAIR_WILD_DVS', headless is None, raising=False)
    run = HeadlessRun(ROM, CHECKPOINT, seed=5, fair_wild_dvs=headless)
    hooked, battled = [], set()

    def spy(mem, key):
        result = REROLL(mem, key)
        hooked.append((result, bytes(mem[0xcff1:0xcff3])))
        return result
    monkeypatch.setattr(fair_dvs, 'reroll', spy)
    with closing(Store(tmp_path)) as store:
        store.set(fair_dvs.KEY, {'seed': '11' * 32})
        tracker = ShinyTracker(store, hashlib.sha1(ROM.read_bytes()).hexdigest())
        if headless is None:
            tracker.attach(run.pb)
        start = run.frame
        wild = lambda: [written for written, _ in hooked if written]
        while run.frame - start < 216000 and not (len(wild()) >= count and set(wild()) <= battled):
            snapshot = read_snapshot(run.pb.memory, run.frame)
            if snapshot.in_battle == 1:
                battled.add(bytes(run.pb.memory[0xcff1:0xcff3]))
            run.step(snapshot)
    run.pb.stop(save=False)
    return hooked, battled


@pytest.mark.skipif(not ROM.is_file() or not CHECKPOINT.is_file(), reason='private ROM and checkpoint unavailable')
def test_rom_wild_battles_keep_the_dvs_the_hook_wrote(tmp_path, monkeypatch):
    hooked, battled = wild_encounters(tmp_path / 'on', monkeypatch)
    wild = [stored for written, stored in hooked if written]
    assert len(wild) == 3
    assert all(written == stored for written, stored in hooked if written)
    # The battle that follows still holds them, so CalcStats and the capture used them too.
    assert set(wild) <= battled
    # Rerolls are fixed by the adventure key, so the same run repeats exactly.
    assert wild_encounters(tmp_path / 'again', monkeypatch)[0] == hooked


@pytest.mark.skipif(not ROM.is_file() or not CHECKPOINT.is_file(), reason='private ROM and checkpoint unavailable')
def test_a_headless_run_with_the_adventure_key_meets_the_adventure_encounters(tmp_path, monkeypatch):
    live = wild_encounters(tmp_path / 'live', monkeypatch)[0]
    assert wild_encounters(tmp_path / 'headless', monkeypatch, headless=bytes.fromhex('11' * 32))[0] == live
    # Keyed by the seed instead, the rerolls still land and the run repeats exactly.
    seeded = wild_encounters(tmp_path / 'seeded', monkeypatch, headless=True)[0]
    assert sum(1 for written, _ in seeded if written) == 3
    assert wild_encounters(tmp_path / 'seeded-again', monkeypatch, headless=True)[0] == seeded


def test_a_headless_run_refuses_fair_dvs_on_an_unverified_cartridge():
    with pytest.raises(ValueError, match='only for verified'):
        fair_dvs.attach(SimpleNamespace(), 'unknown', bytes(32))


def test_the_audit_takes_fair_dvs_as_a_flag_or_an_adventure_key(monkeypatch):
    from tools import replay_audit
    seen = []
    monkeypatch.setattr(replay_audit, 'run_one', seen.append)
    replay_audit.main(['run', 'red.gb', 'a.state', '60', 'out.json', '--fair-wild-dvs'])
    replay_audit.main(['run', 'red.gb', 'a.state', '60', 'out.json', '--fair-wild-dvs', '11' * 32])
    replay_audit.main(['run', 'red.gb', 'a.state', '60', 'out.json'])
    assert [args.fair_wild_dvs for args in seen] == [True, bytes.fromhex('11' * 32), None]
    with pytest.raises(ValueError, match='only for Red'):
        replay_audit._open(Path('gold.gbc'), None, None, 7, True)


def test_yellow_rerolls_its_own_shifted_addresses():
    from pokesim import yellow
    from test_yellow_memory import Owner
    memory = yellow.YellowMemory(Owner())
    raw = memory.raw.data
    raw[0xcff0:0xcff2] = b'\x98\x88'    # Yellow wEnemyMonDVs
    raw[0xd056] = 1                     # Yellow wIsInBattle
    dvs = fair_dvs.reroll(memory, bytes(32))
    assert bytes(raw[0xcff0:0xcff2]) == dvs != b'\x98\x88'
    raw[0xd068] = 8                     # Yellow wEnemyBattleStatus3, transformed
    assert fair_dvs.reroll(memory, bytes(32)) is None
