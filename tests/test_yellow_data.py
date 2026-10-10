"""Yellow data comes from a hash-pinned pret/pokeyellow checkout and stays apart from Red and Blue data."""
import hashlib

import pytest

from pokesim import cartridges, game_data
from pokesim.data_tools import collection
from pokesim.data_tools.strategy import release_source


def yellow_bundle():
    try:
        game_data.bundle_path(variant='yellow')
    except RuntimeError:
        pytest.skip('Yellow game data is not prepared')
    return {name: game_data.load(name, variant='yellow') for name in game_data.FILES}


def test_debug_blocks_are_dropped_from_sources():
    text = ('\twarp_event 7, 1, LAST_MAP, 1\n'
            'IF DEF(_DEBUG)\n\twarp_event 0, 0, SILPH_CO_11F, 1\nENDC\n'
            'IF DEF(_DEBUG)\n\tdb 1\nELSE\n\tdb 2\nENDC\n')
    cleaned = release_source(text)
    assert 'SILPH_CO_11F' not in cleaned
    assert '\tdb 2\n' in cleaned and '\tdb 1\n' not in cleaned
    assert cleaned.startswith('\twarp_event 7, 1, LAST_MAP, 1\n')


def test_yellow_source_is_pinned_separately():
    url, revision = game_data.VARIANTS['yellow']
    assert url == 'https://github.com/pret/pokeyellow'
    assert len(revision) == 40 and revision != game_data.SOURCE_REVISION
    assert game_data.variant_root('/data', 'yellow').as_posix() == '/data/yellow'
    assert game_data.variant_root('/data', 'red').as_posix() == '/data'


def test_unknown_variant_is_refused(monkeypatch):
    monkeypatch.setenv(game_data.VARIANT_ENV, 'green')
    with pytest.raises(RuntimeError):
        game_data.current_variant()


def test_cartridge_identity_and_starters():
    raw = b'not a cartridge'
    assert cartridges.identify(raw) is None
    yellow = cartridges.by_version('yellow')
    assert yellow.generation == 1 and yellow.sha1 == 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'
    assert yellow.starters == ('pikachu',)
    cartridges.validate_starter('pikachu', 'yellow')
    cartridges.validate_starter('random', 'yellow')
    with pytest.raises(ValueError):
        cartridges.validate_starter('bulbasaur', 'yellow')
    with pytest.raises(ValueError):
        cartridges.validate_starter('pikachu', 'red')


def test_yellow_trades_and_gifts_name_their_npcs():
    received = {row[1] for row in collection.YELLOW_TRADES}
    assert received == {'MR_MIME', 'DUGTRIO', 'PARASECT', 'MACHOKE', 'MUK', 'RHYDON', 'DEWGONG'}
    assert all(row[3] for row in collection.YELLOW_TRADES)
    assert {row[0] for row in collection.YELLOW_GIFTS} == {'BULBASAUR', 'CHARMANDER', 'SQUIRTLE'}


def test_prepared_yellow_bundle():
    data = yellow_bundle()
    strategy, sources = data['strategy.json'], data['collection.json']
    world = strategy['world']
    bedroom = world[str(strategy['maps']['REDS_HOUSE_2F'])]
    # pokeyellow's debug build adds warps from the bedroom to late dungeons.
    assert bedroom['warps'] == [[7, 1, 37, 2]]
    assert list(sources['versions']) == ['yellow']
    names = {int(key): value['name'] for key, value in strategy['species'].items()}
    found = {(names[int(sid)], row['method']) for sid, rows in sources['versions']['yellow'].items() for row in rows}
    for name in ('BULBASAUR', 'CHARMANDER', 'SQUIRTLE'):
        assert (name, 'gift') in found
    assert ('MR_MIME', 'trade') in found and ('JYNX', 'trade') not in found
    lab = world[str(strategy['maps']['OAKS_LAB'])]
    assert any(obj[2] == 'SPRITE_POKE_BALL' and 'EEVEE' in str(obj) for obj in lab['objects'])


def test_red_bundle_is_unaffected():
    try:
        strategy = game_data.load('strategy.json', variant='red')
    except RuntimeError:
        pytest.skip('Red game data is not prepared')
    sources = game_data.load('collection.json', variant='red')
    assert set(sources['versions']) == {'red', 'blue'}
    assert strategy['revision'] == game_data.SOURCE_REVISION


def test_bundles_hash_their_files():
    yellow_bundle()
    root = game_data.bundle_path(variant='yellow')
    import json
    manifest = json.loads((root / 'manifest.json').read_text())
    assert manifest['variant'] == 'yellow'
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


def test_retail_rom_is_identified():
    import os
    from pathlib import Path
    from pokesim.yellow import is_yellow
    rom = Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc'))
    if not rom.exists():
        pytest.skip('no Yellow ROM')
    raw = rom.read_bytes()
    assert cartridges.identify(raw).version == 'yellow'
    assert is_yellow(raw) and raw[0x134:0x142].rstrip(b'\0') == b'POKEMON YELLOW'
    assert cartridges.unpack(raw) == raw
