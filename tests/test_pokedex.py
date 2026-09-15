from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pokesim import config
from pokesim.ram import PartyMon
from pokesim.store import Store
from pokesim.web.app import create_app
from pokesim.web.pokedex import DEFAULT_VERSION, live_status, reference
from test_events import snap


@pytest.fixture(scope='module')
def dex():
    return {entry['dex']: entry for entry in reference()['entries']}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'VIEWER_ONLY', False)
    store = Store(tmp_path)
    emu = Mock()
    emu.health.return_value = {'ok': True}
    emu.status.return_value = {'game': None, 'strategy': {}}
    try:
        with TestClient(create_app(emu, store)) as client:
            yield client, emu
    finally:
        store.close()


def test_reference_covers_every_kanto_number(dex):
    assert sorted(dex) == list(range(1, 152))
    assert [entry['dex'] for entry in reference()['entries']] == list(range(1, 152))
    assert reference()['version'] == DEFAULT_VERSION


def test_entry_carries_the_cartridge_numbers(dex):
    pikachu = dex[25]
    assert pikachu['name'] == 'Pikachu'
    assert pikachu['types'] == ['Electric']
    assert pikachu['stats'] == {'HP': 35, 'Attack': 55, 'Defense': 30, 'Speed': 90, 'Special': 50}
    assert pikachu['total'] == 260
    assert pikachu['catch_rate'] == 190
    assert pikachu['growth'] == 'Medium fast'
    assert [(move['name'], move['level']) for move in pikachu['moves']][:3] == [
        ('Thundershock', None), ('Growl', None), ('Thunder Wave', 9)]


def test_psychic_moves_drop_the_disassembly_suffix(dex):
    agility = next(move for move in dex[25]['moves'] if move['name'] == 'Agility')
    assert agility['type'] == 'Psychic'
    assert not any(move['type'].endswith(' Type') for entry in dex.values() for move in entry['moves'])


def test_a_starting_move_is_not_repeated_by_the_learnset(dex):
    bubble = [move for move in dex[8]['moves'] if move['name'] == 'Bubble']
    assert len(bubble) == 1 and bubble[0]['level'] is None
    for entry in dex.values():
        names = [move['name'] for move in entry['moves']]
        assert len(names) == len(set(names)), entry['name']


def test_single_type_species_is_not_listed_twice(dex):
    assert dex[19]['types'] == ['Normal']
    assert dex[1]['types'] == ['Grass', 'Poison']


def test_encounters_group_by_place_with_a_level_range(dex):
    forest = next(p for p in dex[25]['locations'] if p['map_name'] == 'Viridian Forest')
    assert forest['method_label'] == 'Tall grass'
    assert forest['level_range'] == 'Lv. 3–5'
    assert forest['rod'] is None


def test_fishing_water_and_trade_sources_keep_their_context(dex):
    fishing = next(p for p in dex[54]['locations'] if p['method'] == 'fish')
    assert fishing['rod'] == 'Super Rod'
    trade = dex[122]['locations'][0]
    assert (trade['method_label'], trade['gives']) == ('In-game trade', 'Abra')
    fossil = dex[138]['locations'][0]
    assert fossil['item'] == 'Helix Fossil'


def test_species_without_a_wild_source_still_has_an_entry(dex):
    assert dex[151]['locations'] == []
    assert dex[151]['name'] == 'Mew'


def test_evolution_family_reads_in_both_directions(dex):
    assert [(step['name'], step['label']) for step in dex[133]['evolves_to']] == [
        ('Flareon', 'Fire Stone'), ('Jolteon', 'Thunder Stone'), ('Vaporeon', 'Water Stone')]
    assert [(step['name'], step['label']) for step in dex[6]['evolves_from']] == [('Charmeleon', 'Level 36')]
    assert dex[64]['evolves_to'][0]['label'] == 'Link trade'


def test_outside_links_escape_the_name(dex):
    assert dex[122]['links']['bulbapedia'].endswith('Mr.%20Mime_(Pok%C3%A9mon)')
    assert dex[1]['links']['serebii'].endswith('/001.shtml')
    assert 'Nidoran' in dex[29]['links']['wikipedia']


def test_unknown_version_is_rejected():
    with pytest.raises(ValueError):
        reference('gold')


def test_live_status_without_a_running_game():
    status = live_status(None)
    assert status == {'started': False, 'owned': [], 'seen': [], 'party': [], 'storage': None,
                      'plan': [], 'phase': '', 'version': DEFAULT_VERSION, 'hunting': None, 'protected_species': []}


def test_live_status_reports_records_party_and_boxes():
    game = snap(owned=frozenset({1, 4}), seen=frozenset({1, 4, 25}),
                party=(PartyMon(0x99, 20, 22, 5, 'BULBASAUR'),),
                stored_pokemon=((0, 0x54, 12, 'SPARKY'),), box_counts=(1, 0)).to_dict()
    status = live_status(game, {'entries': [{'dex': 25, 'species': 0x54, 'status': 'available',
                                             'reason': 'Available in the grass', 'methods': ['grass']}],
                                'phase': 'Thorough adventure', 'hunt': {'species': 0x54}})
    assert status['owned'] == [1, 4] and status['seen'] == [1, 4, 25]
    assert status['party'][0] == {'dex': 1, 'species': 0x99, 'name': 'Bulbasaur', 'nick': 'BULBASAUR',
                                  'level': 5, 'hp': 20, 'max_hp': 22, 'status_label': 'Healthy', 'slot': 1,
                                  'moves': (), 'dvs': (), 'stat_exp': (), 'experience': 0}
    assert status['storage']['pokemon'][0]['dex'] == 25
    assert list(status['storage']['box_counts']) == [1, 0]
    assert status['phase'] == 'Thorough adventure' and status['hunting'] == 0x54
    assert status['plan'] == [{'dex': 25, 'species': 0x54, 'status': 'available', 'reason': 'Available in the grass'}]


def test_pokedex_page_and_reference_are_served(api):
    client, _ = api
    page = client.get('/pokedex')
    assert page.status_code == 200 and 'pokedex.js' in page.text
    body = client.get('/api/pokedex').json()
    assert len(body['entries']) == 151
    assert client.get('/api/pokedex?version=gold').status_code == 400


def test_pokedex_status_follows_the_running_game(api):
    client, emu = api
    assert client.get('/api/pokedex/status').json()['started'] is False
    emu.status.return_value = {'game': snap(owned=frozenset({7})).to_dict(),
                               'strategy': {'collection': {'entries': [{'dex': 7}], 'phase': 'Badge journey'}}}
    status = client.get('/api/pokedex/status').json()
    assert status['owned'] == [7] and status['phase'] == 'Badge journey'
    assert status['plan'] == [{'dex': 7, 'species': None, 'status': None, 'reason': None}]


def test_viewer_only_instances_still_serve_the_pokedex(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.get('/pokedex').status_code == 200
    assert client.get('/api/pokedex').status_code == 200
    assert client.get('/api/pokedex/status').status_code == 200

def test_pokedex_follows_the_running_cartridge(api):
    client, emu = api
    emu.status.return_value = {'game': None, 'strategy': {'collection': {'version': 'blue'}}}
    body = client.get('/api/pokedex').json()
    assert body['version'] == 'blue'
    entries = {e['dex']: e for e in body['entries']}
    # Sandshrew is a Blue exclusive and Ekans is Red's counterpart.
    assert entries[27]['locations'] and not entries[23]['locations']
    red = {e['dex']: e for e in client.get('/api/pokedex?version=red').json()['entries']}
    assert red[23]['locations'] and not red[27]['locations']
    assert client.get('/api/pokedex/status').json()['version'] == 'blue'


def test_a_blue_cartridge_is_a_known_rom():
    assert 'Pokemon Blue (USA, Europe)' in config.KNOWN_ROM_SHA1.values()
