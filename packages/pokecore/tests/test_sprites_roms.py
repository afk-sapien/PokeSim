"""Portraits and species tables on real cartridges.

Collected only when POKESIM_CORE_ROMS (red.gb, blue.gb, yellow.gb) or POKESIM_CORE_GEN2_ROMS
(gold.gbc, silver.gbc, crystal.gbc) names a folder of ROMs. The digests cover every portrait's
colour indices (and, for Gold, Silver and Crystal, both palettes). They were checked against
PokeSim's decoders, whose Red, Blue and Yellow output matches pret's reference art pixel for pixel.
"""
import hashlib
import os
from pathlib import Path

import pytest

from pokecore import identity, sprites
from pokecore.gen2 import sprites as gen2_sprites

DIGESTS = {
    'red': '0ad28e77fe18a2f9a8f717ad836f198ad3c228d8adaf0d6fb96c83833ca985dd',
    'blue': '0ad28e77fe18a2f9a8f717ad836f198ad3c228d8adaf0d6fb96c83833ca985dd',
    'yellow': 'efe1b8d622e8032c97350a74f509ef58895b19342baf75fef642b884d22fa2fd',
    'gold': '3122a9f81cbead2080e84f2da5cf2e6971fd408c4e5f4ae28e2ee935d8836b80',
    'silver': '9627d1a9b95c5cfd0be0a3db450a8f9f54b230c590f26c85d3fb142a175ebb2b',
    'crystal': '1aabc1e8d54648d5e716a4f8253a6b26d0a3a7da4b877d5dc0468f8715e5697e',
}
# PokedexOrder, species index to Pokédex number, from pret/pokered and pret/pokeyellow.
POKEDEX_ORDER = {'red': 0x41024, 'blue': 0x41024, 'yellow': 0x410B1}
# EvosAttacksPointers from the pinned pret symbol files.
EVOS = {'gold': (0x10, 0x67BD), 'silver': (0x10, 0x67BD), 'crystal': (0x10, 0x65B1)}
EVOLVE_STAT = 5


def _rom(variable, name):
    directory = os.environ.get(variable)
    if not directory:
        pytest.skip(f'set {variable} to a folder of cartridges to run')
    path = Path(directory) / name
    if not path.exists():
        pytest.skip(f'{name} is not in {variable}')
    return path.read_bytes()


@pytest.fixture(params=['red', 'blue', 'yellow'])
def gen1(request):
    return request.param, _rom('POKESIM_CORE_ROMS', f'{request.param}.gb')


@pytest.fixture(params=['gold', 'silver', 'crystal'])
def gen2(request):
    return request.param, _rom('POKESIM_CORE_GEN2_ROMS', f'{request.param}.gbc')


def test_every_gen1_portrait_decodes_to_the_known_pictures(gen1):
    version, rom = gen1
    portraits = sprites.portraits(rom)
    assert sorted(portraits) == list(range(1, 152))
    digest = hashlib.sha256()
    for dex, rows in portraits.items():
        assert 8 <= len(rows) <= 56 and len(rows) % 8 == 0 and len(rows[0]) % 8 == 0, dex
        digest.update(bytes(value for row in rows for value in row))
    assert digest.hexdigest() == DIGESTS[version]
    assert sprites.png(portraits[25])[:8] == b'\x89PNG\r\n\x1a\n'


def test_mew_is_read_from_its_own_header(gen1):
    _, rom = gen1
    pixels, width, height = sprites.front_sprite(rom, sprites.MEW_DEX)
    assert (width, height) == (5, 5)
    assert any(value for row in pixels for value in row), 'Mew decoded to an empty picture'


def test_gen1_index_table_matches_the_cartridge(gen1):
    version, rom = gen1
    order = rom[POKEDEX_ORDER[version]:POKEDEX_ORDER[version] + 190]
    assert {index: dex for index, dex in enumerate(order, 1) if dex} == identity.GEN1_DEX


def test_every_gen2_portrait_decodes_to_the_known_pictures(gen2):
    version, rom = gen2
    digest = hashlib.sha256()
    for dex in range(1, 252):
        for shiny in (False, True):
            rows, palette = gen2_sprites.portrait(rom, version, dex, shiny=shiny)
            digest.update(bytes(value for row in rows for value in row))
            digest.update(bytes(channel for colour in palette for channel in colour))
    assert digest.hexdigest() == DIGESTS[version]
    letters = {tuple(map(tuple, gen2_sprites.picture(rom, version, 201, unown=letter)[0])) for letter in range(26)}
    assert len(letters) == 26, 'each Unown letter is its own picture'


def test_families_match_gen2_evolutions(gen2):
    version, rom = gen2
    table = gen2_sprites.offset(*EVOS[version])
    linked = set()
    for dex in range(1, 252):
        address = int.from_bytes(rom[table + (dex - 1) * 2:table + dex * 2], 'little')
        at = gen2_sprites.offset(EVOS[version][0], address)
        while rom[at]:
            size = 4 if rom[at] == EVOLVE_STAT else 3
            target = rom[at + size - 1]
            assert identity.family(dex) == identity.family(target), (dex, target)
            linked |= {dex, target}
            at += size
    # Every listed family is a real evolution line, and every evolving species is listed.
    assert linked == set(identity.FAMILY_ROOTS)
