"""The Pokédex plan calls a source planned only while the sim has no code for it."""
import os

import pytest


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def rows(data):
    from pokesim.gen2.dex_sources import describe
    return {row['species']: row for row in describe(data)}


def test_the_friday_lapras_is_available(real_data):
    # collection.lapras() meets the Union Cave Lapras on a Friday.
    row = rows(real_data)[131]
    assert row['status'] == 'available' and 'Union Cave Lapras' in row['reason']


def test_contest_only_species_are_available(real_data):
    # contest.journey() enters the Bug-Catching Contest for a wanted species with no wild row.
    from pokesim.gen2.contest import CONTEST_SPECIES
    wild = {row['species'] for row in real_data.encounters}
    only = [species for species in CONTEST_SPECIES if species not in wild]
    assert only
    table = rows(real_data)
    assert {species: table[species]['status'] for species in only} == dict.fromkeys(only, 'available')
    assert all(not source['planned'] for species in only for source in table[species]['sources']
               if source['kind'] == 'contest')


def test_unown_is_available(real_data):
    # ruins.journey() solves the puzzles, and the hunt and the battle policy catch each missing letter.
    row = rows(real_data)[201]
    assert row['status'] == 'available'
    assert not any(source['planned'] for source in row['sources'])
