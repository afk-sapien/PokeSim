"""Place, item and evolution text reads as the games spell it, not as raw constants."""
import json
import os

import pytest

from pokesim.display_names import place_name, title_name


def test_place_names_restore_possessive_apostrophes_only_before_another_word():
    assert place_name('Digletts Cave') == "Diglett's Cave"
    assert place_name('Vermilion Digletts Cave Speech House') == "Vermilion Diglett's Cave Speech House"
    assert place_name('Mr Fujis House') == "Mr. Fuji's House"
    assert place_name('Players Neighbors House') == "Player's Neighbor's House"
    assert place_name('Dragons Den B1F') == "Dragon's Den B1F"
    assert place_name('Seafoam Islands B1F') == 'Seafoam Islands B1F'
    assert place_name('Route 30') == 'Route 30'


def test_title_name_keeps_letters_after_apostrophes_lowercase():
    assert title_name("KING'S ROCK") == "King's Rock"
    assert title_name("FARFETCH'D") == "Farfetch'd"
    assert title_name('UP-GRADE') == 'Up-Grade'


def test_gen1_map_names_read_with_apostrophes():
    from pokesim.ram import MAP_NAMES
    assert "Diglett's Cave" in MAP_NAMES.values()
    assert 'Digletts Cave' not in MAP_NAMES.values()


@pytest.fixture
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'crystal')


def test_gen2_evolutions_name_items_instead_of_constants(crystal):
    from pokesim.gen2.web import Reference
    entries = {row['name']: row for row in json.loads(Reference(crystal).json('crystal'))['entries']}
    labels = {(row['name'], step['name']): step['label'] for row in entries.values() for step in row['evolves_to']}
    assert labels['Scyther', 'Scizor'] == 'Trade holding Metal Coat'
    assert labels['Poliwhirl', 'Politoed'] == "Trade holding King's Rock"
    assert labels['Slowpoke', 'Slowking'] == "Trade holding King's Rock"
    assert labels['Seadra', 'Kingdra'] == 'Trade holding Dragon Scale'
    assert labels['Porygon', 'Porygon2'] == 'Trade holding Up-Grade'
    assert labels['Kadabra', 'Alakazam'] == 'Link trade'
    assert labels['Clefairy', 'Clefable'] == 'Moon Stone'
    assert labels['Eevee', 'Espeon'] == 'High friendship by day'
    assert labels['Tyrogue', 'Hitmonlee'] == 'Level 20, Attack above Defense'
    assert labels['Chikorita', 'Bayleef'] == 'Level 16'
    every = [step['label'] for row in entries.values() for step in row['evolves_to'] + row['evolves_from']]
    assert not [label for label in every if '_' in label or label.isupper()]


def test_gen2_place_and_source_text_use_display_spelling(crystal):
    assert "Diglett's Cave" in {row['name'] for row in crystal.maps.values()}
    from pokesim.gen2.dex_sources import _evolution_text
    scyther = next(sid for sid, row in crystal.species.items() if row['name'] == 'Scyther')
    evo = next(row for row in crystal.species[scyther]['evolutions'] if row['method'] == 'trade')
    assert _evolution_text(crystal, scyther, evo) == 'Trade Scyther holding a Metal Coat'
