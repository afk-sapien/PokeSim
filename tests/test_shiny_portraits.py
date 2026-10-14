"""Shiny Pokémon show their shiny portrait, drawn from the cartridge's own shiny palette."""
import hashlib
import io
import os
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from pokesim.app.assets import portrait_url
from pokesim.app.manager import Manager, create_app
from pokesim.app.registry import identifier


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = Manager(tmp_path, 'http://testserver')
    monkeypatch.setattr(manager, 'start', lambda: None)
    try:
        yield manager
    finally:
        manager.close()


def colour(data):
    """Mean (red, green, blue) over the opaque, non-white pixels of a portrait."""
    image = Image.open(io.BytesIO(data)).convert('RGBA')
    raw = image.tobytes()
    pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 4) if raw[i + 3] and raw[i:i + 3] != b'\xff\xff\xff']
    return tuple(sum(channel) / len(pixels) for channel in zip(*pixels))


def test_portrait_addresses_name_the_shiny_variant():
    assert portrait_url('a1', 130) == '/games/a1/sprites/130.png?v=rom-portraits-1'
    assert portrait_url('a1', 130, True) == '/games/a1/sprites/shiny/130.png?v=rom-portraits-1'
    assert portrait_url('a1', 0, True) is None and portrait_url('a1', None) is None


def test_generation_one_answers_the_normal_portrait_for_a_shiny_address(manager):
    manager.registry.add_rom('rom', 'sha1', 'red')
    row = manager.registry.create('Red', 'rom', {}, identifier())
    defaults = manager.root / 'assets' / 'sprites'
    defaults.mkdir(parents=True)
    (defaults / '130.png').write_bytes(b'red gyarados')
    with TestClient(create_app(manager)) as client:
        shiny = client.get(f'/games/{row["id"]}/sprites/shiny/130.png?v=rom-portraits-1')
        assert shiny.status_code == 200 and shiny.content == b'red gyarados'
        assert client.get(f'/view/{row["id"]}/sprites/shiny/130.png').content == b'red gyarados'


@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_gen2_shiny_route_draws_the_shiny_palette(manager, version):
    cartridges, data = os.environ.get('GEN2_CARTRIDGE_DIR'), os.environ.get('GEN2_DATA_DIR')
    if not cartridges or not data or not (Path(cartridges) / f'{version}.gbc').is_file():
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR to private extracted cartridges and data')
    from pokesim.gen2.data import GameData
    from pokesim.gen2.sprites import portrait
    raw = (Path(cartridges) / f'{version}.gbc').read_bytes()
    rom_id = hashlib.sha256(raw).hexdigest()
    stored = manager.root / 'assets' / 'roms' / rom_id
    stored.mkdir(parents=True)
    (stored / 'rom.gb').write_bytes(raw)
    manager.registry.add_rom(rom_id, 'sha1', version)
    row = manager.registry.create(version.title(), rom_id, {}, identifier())
    manager.assets.game_data_dir = Path(data)
    folder = manager.root / 'assets' / 'sprites' / version
    folder.mkdir(parents=True)
    (folder / '130.png').write_bytes(portrait(raw, GameData.load(Path(data), version), 130))
    with TestClient(create_app(manager)) as client:
        normal = client.get(f'/games/{row["id"]}/sprites/130.png?v=rom-portraits-1')
        # Portraits extracted before shiny ones existed are drawn on first request.
        shiny = client.get(f'/games/{row["id"]}/sprites/shiny/130.png?v=rom-portraits-1')
    assert normal.status_code == shiny.status_code == 200
    assert shiny.headers['content-type'] == 'image/png'
    assert normal.content != shiny.content
    assert (folder / 'shiny' / '130.png').read_bytes() == shiny.content
    red, _, blue = colour(normal.content)
    assert blue > red  # the familiar blue Gyarados
    red, _, blue = colour(shiny.content)
    assert red > blue  # the red one
