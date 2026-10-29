"""Randomized runs: share codes, the in-memory patched cartridge, and the planner's effective tables."""
import hashlib
import io
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from pokesim import randomized
from pokesim.planning import cost
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import Registry, identifier

ROOT = Path(__file__).resolve().parents[1]
RED_ROM = Path(os.environ.get('ROM_PATH', ROOT / 'roms' / 'pokered.gb'))
RED_SHA1 = 'ea9bcae617fdf159b045185467ae58b2e4a48b9a'


def red_rom():
    if not RED_ROM.is_file() or hashlib.sha1(RED_ROM.read_bytes()).hexdigest() != RED_SHA1:
        pytest.skip('needs a clean Pokémon Red ROM in ROM_PATH')
    return RED_ROM


def fake_run(monkeypatch, generation, version, encounters=None, wild=True, trainers=False, clean=None, effective=None):
    run = SimpleNamespace(version=version, options=SimpleNamespace(wild=wild, starters=True, trainers=trainers),
                          clean=clean, effective=effective or SimpleNamespace(generation=generation, encounters=encounters or {}))
    monkeypatch.setattr(randomized, 'current', lambda rom_path=None: run)
    return run


def test_share_codes_are_canonical_and_tied_to_the_cartridge():
    assert randomized.validate('') == ''
    assert randomized.validate(None) == ''
    assert randomized.validate(' psr1-red-ws-42 ') == 'PSR1-RED-WS-42'
    assert randomized.validate('PSR1-CRYSTAL-WST-18446744073709551615', 'crystal') == 'PSR1-CRYSTAL-WST-18446744073709551615'
    for code in ('PSR1-RED-SW-42', 'PSR1-RED-WS-18446744073709551616', 'PSR1-RED--42', 'PSR2-RED-W-1', 'PSR1-RED-W-01'):
        with pytest.raises(ValueError, match='not valid'):
            randomized.validate(code)
    with pytest.raises(ValueError, match='Pokémon Gold, not Red'):
        randomized.validate('PSR1-GOLD-W-1', 'red')
    with pytest.raises(ValueError, match='text'):
        randomized.validate(42)


def test_off_is_stored_as_absent_and_codes_are_stored_canonical():
    assert Manager.validate_adventure_settings({'randomizer': 'psr1-blue-w-7'})['randomizer'] == 'PSR1-BLUE-W-7'
    assert 'randomizer' not in Manager.validate_adventure_settings({'randomizer': ''})
    with pytest.raises(ValueError):
        Manager.validate_adventure_settings({'randomizer': 'nope'})


def test_registry_refuses_a_code_for_another_game(tmp_path):
    registry = Registry(tmp_path)
    registry.add_rom('red-rom', 'sha1', 'red')
    row = registry.create('Red', 'red-rom', {'randomizer': 'PSR1-RED-WST-5'}, identifier())
    assert registry.adventure(row['id'])['settings']['randomizer'] == 'PSR1-RED-WST-5'
    with pytest.raises(ValueError, match='Pokémon Yellow, not Red'):
        registry.create('Wrong', 'red-rom', {'randomizer': 'PSR1-YELLOW-W-5'}, identifier())


def test_the_seed_is_chosen_at_creation_and_cannot_change(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    with TestClient(create_app(manager)) as client:
        headers = {'X-PokeSim-CSRF': client.get('/api/v1/session').json()['csrf_token']}
        manager.registry.add_rom('red-rom', 'sha1', 'red')
        plain = client.post('/api/v1/adventures', headers=headers, json={'name': 'Plain', 'rom_id': 'red-rom'}).json()
        assert 'randomizer' not in plain['settings']
        game = client.post('/api/v1/adventures', headers=headers,
                           json={'name': 'Shuffled', 'rom_id': 'red-rom', 'randomizer': 'psr1-red-ws-99'}).json()
        assert game['settings']['randomizer'] == 'PSR1-RED-WS-99'
        route = f"/api/v1/adventures/{game['id']}"
        for change in ('PSR1-RED-WS-100', '', 'PSR1-RED-W-99'):
            refused = client.patch(route, headers=headers, json={'settings': {'randomizer': change}})
            assert refused.status_code == 409 and 'chosen when creating' in refused.text
        same = client.patch(route, headers=headers, json={'settings': {'randomizer': 'PSR1-RED-WS-99', 'speed': 2}})
        assert same.status_code == 200 and same.json()['settings']['randomizer'] == 'PSR1-RED-WS-99'
        refused = client.patch(f"/api/v1/adventures/{plain['id']}", headers=headers,
                               json={'settings': {'randomizer': 'PSR1-RED-WS-99'}})
        assert refused.status_code == 409
        wrong = client.post('/api/v1/adventures', headers=headers,
                            json={'name': 'Wrong', 'rom_id': 'red-rom', 'randomizer': 'PSR1-GOLD-W-1'})
        assert wrong.status_code == 409 and 'Pokémon Gold' in wrong.text


def test_an_unrandomized_worker_boots_the_clean_file(monkeypatch, tmp_path):
    monkeypatch.delenv(randomized.ENV, raising=False)
    assert randomized.rom_stream(tmp_path / 'rom.gb') == str(tmp_path / 'rom.gb')
    assert randomized.status() is None


def test_the_patched_cartridge_lives_only_in_memory(monkeypatch):
    rom = red_rom()
    before = hashlib.sha1(rom.read_bytes()).hexdigest()
    monkeypatch.setenv(randomized.ENV, 'PSR1-RED-S-1234')
    stream = randomized.rom_stream(rom)
    assert isinstance(stream, io.BytesIO)
    patched = stream.getvalue()
    assert len(patched) == rom.stat().st_size and patched != rom.read_bytes()
    assert hashlib.sha1(rom.read_bytes()).hexdigest() == before
    run = randomized.current(rom)
    assert run.effective.starters != run.clean.starters
    from pokecore import romdata
    assert romdata.load(patched, 'red').starters == run.effective.starters
    from pokesim import config
    monkeypatch.setattr(config, 'ROM_PATH', rom, raising=False)
    assert randomized.status() == {'code': 'PSR1-RED-S-1234', 'wild': False, 'starters': True, 'trainers': False}


# Recorded with pokecore 0.9.5 for the share code of a stored adventure. Core 0.10.0 changed the digest of
# GameData.canonical(), which now holds the fishing tables. PokeSim stores and compares no canonical()
# digest, only the share code, so an older adventure must still boot the same cartridge and plan with the
# same wild and trainer tables.
BEFORE_0_10 = {'canonical': '6f1325b59eeeacb2ec8ddef1009f509d0a811e9787c8990e0c76bab38eff3fe1',
               'patched': '4b6ecb0584d0fbe86295b3ab38686ca5629a500ba53152af2a6efe403b8ce8b9',
               'encounters': '351710c52a26c8792b9aefc6bb51f389dc086c1cfb0ec8b173bae11b7d1b0df8',
               'trainers': '307f5da7d394e41f2a4bc75a253f089474ce3af94db996951b919fbc7ce8106f'}


def test_an_older_share_code_replays_the_same_run(monkeypatch):
    import json
    rom = red_rom()
    monkeypatch.setenv(randomized.ENV, 'PSR1-RED-WST-4242')
    assert randomized.validate('PSR1-RED-WST-4242', 'red') == 'PSR1-RED-WST-4242'
    run = randomized.current(rom)

    def digest(table):
        return hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()

    assert hashlib.sha256(run.rom).hexdigest() == BEFORE_0_10['patched']
    assert digest(run.effective.encounters) == BEFORE_0_10['encounters']
    assert digest(run.effective.trainers) == BEFORE_0_10['trainers']
    # Only the canonical digest moved, and nothing in PokeSim keeps one.
    assert hashlib.sha256(run.clean.canonical()).hexdigest() != BEFORE_0_10['canonical']


def test_gen1_strategy_and_collection_follow_the_wild_tables(monkeypatch):
    fake_run(monkeypatch, 1, 'red', {
        'grass:12': {'kind': 'grass', 'map': 12, 'rate': 25, 'slots': [[3, 36], [4, 36], [3, 112]]},
        'water:12': {'kind': 'water', 'map': 12, 'rate': 5, 'slots': [[20, 23]]},
        'grass:217': {'kind': 'grass', 'map': 217, 'rate': 30, 'slots': [[22, 9]]},
    })
    monkeypatch.setattr(randomized, '_strategy_world', lambda: {'12': {'symbol': 'ROUTE_1'}, '217': {'symbol': 'SAFARI_ZONE_EAST'}})
    strategy = randomized.gen1_game_data('strategy.json', {'world': {'12': {'encounters': [[165, 2]]}, '13': {}}}, 'red')
    assert strategy['world']['12']['encounters'] == [[36, 3], [36, 4], [112, 3]]
    assert 'encounters' not in strategy['world']['13']
    collection = randomized.gen1_game_data('collection.json', {'versions': {'red': {
        '165': [{'map': 12, 'method': 'grass', 'level': 2}],
        '133': [{'map': 0, 'method': 'gift', 'level': 25}],
    }, 'blue': {'165': [{'map': 12, 'method': 'grass', 'level': 2}]}}}, 'red')
    red = collection['versions']['red']
    assert '165' not in red and red['133'] == [{'map': 0, 'method': 'gift', 'level': 25}]
    assert red['36'] == [{'map': 12, 'method': 'grass', 'level': 3}, {'map': 12, 'method': 'grass', 'level': 4}]
    assert red['23'] == [{'map': 12, 'method': 'surf', 'level': 20}]
    assert red['9'] == [{'map': 217, 'method': 'safari', 'level': 22}]
    assert collection['versions']['blue']['165']
    # Yellow tables never leak into Red data, and an unshuffled wild leaves the file alone.
    assert randomized.gen1_game_data('strategy.json', {'world': {}}, 'yellow') == {'world': {}}
    fake_run(monkeypatch, 1, 'red', wild=False)
    untouched = {'world': {'12': {'encounters': [[165, 2]]}}}
    assert randomized.gen1_game_data('strategy.json', untouched, 'red')['world']['12']['encounters'] == [[165, 2]]


def test_gen1_leader_aces_follow_a_trainer_shuffle(monkeypatch):
    species = {74: {'name': 'geodude'}, 95: {'name': 'onix'}, 25: {'name': 'pikachu'}, 6: {'name': 'charizard'}}
    clean = SimpleNamespace(trainers={'34:1': {'class': 34, 'party': [{'level': 12, 'species': 74}, {'level': 14, 'species': 95}]}})
    effective = SimpleNamespace(generation=1, trainers={'34:1': {'class': 34, 'party': [{'level': 12, 'species': 25}, {'level': 14, 'species': 6}]}})
    opponents = {1: ('Brock', 'onix', 14), 2: ('Misty', 'starmie', 21)}
    fake_run(monkeypatch, 1, 'red', trainers=False, clean=clean, effective=effective)
    assert randomized.gen1_opponents(opponents, species) == opponents
    fake_run(monkeypatch, 1, 'red', trainers=True, clean=clean, effective=effective)
    assert randomized.gen1_opponents(opponents, species) == {1: ('Brock', 'charizard', 14), 2: ('Misty', 'starmie', 21)}


def test_gen2_rows_follow_the_wild_tables_and_skip_swarms(monkeypatch):
    grass = {time: [[level, 16 + i] for i, level in enumerate(range(2, 9))] for time in ('morn', 'day', 'nite')}
    run = fake_run(monkeypatch, 2, 'gold', {
        'johto_grass:6151': {'kind': 'johto_grass', 'map': 6151, 'slots': grass},
        'johto_water:6151': {'kind': 'johto_water', 'map': 6151, 'slots': [[20, 60], [15, 118], [10, 129]]},
        'swarm_grass:6152': {'kind': 'swarm_grass', 'map': 6152, 'slots': grass},
    })
    old = [{'map': 6151, 'species': 161, 'level': 2, 'method': 'grass', 'time': 'day', 'chance': 30},
           {'map': 6151, 'species': 129, 'level': 10, 'method': 'old_rod', 'time': 'any', 'chance': 70}]
    rows = cost.gen2_cartridge_rows('gold.gbc', 'gold', old)
    assert rows == cost.gen2_rows(run.effective, old)
    # The cartridge's grass and surf rows come first, the bundle's other rows after them.
    assert rows[-1]['method'] == 'old_rod'
    assert not any(row['species'] == 161 for row in rows)
    night = [row for row in rows if row['time'] == 'night']
    assert [row['chance'] for row in night] == list(cost.GEN2_GRASS) and night[0] == \
        {'map': 6151, 'species': 16, 'level': 2, 'method': 'grass', 'time': 'night', 'chance': 30}
    assert {row['time'] for row in rows if row['method'] == 'grass'} == {'morning', 'day', 'night'}
    assert [(row['species'], row['chance']) for row in rows if row['method'] == 'surf'] == [(60, 60), (118, 30), (129, 10)]
    assert not any(row['map'] == 6152 for row in rows)
    # A run of another version, or a file core cannot read, keeps the bundle's rows.
    assert cost.gen2_cartridge_rows('silver.gbc', 'silver', old) == old


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_a_clean_gen2_cartridge_gives_the_bundle_rows_in_order(version):
    cartridges = os.environ.get('GEN2_CARTRIDGE_DIR')
    rom = Path(cartridges or '') / f'{version}.gbc'
    if not cartridges or not rom.exists() or not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR to compare a real cartridge with the bundle')
    from pokesim.gen2.data import GameData
    bundle = GameData.load(Path(os.environ['GEN2_DATA_DIR']), version).encounters
    assert cost.gen2_cartridge_rows(rom, version, bundle) == bundle
