import io
import zipfile

import pytest

from pokecore import cartridges
from pokecore.cartridges import CARTRIDGES, by_version, identify, read_header, unpack
from pokecore.rom import BLUE_SHA1, KNOWN_ROM_SHA1, RED_SHA1, inspect_rom, require_rom


def synthetic_rom(cartridge, size=None):
    """A ROM-shaped file with a valid header for ``cartridge``. Its hash never matches."""
    raw = bytearray(size or cartridge.rom_size)
    width = 15 if cartridge.cgb else 16
    raw[0x134:0x134 + width] = cartridge.header_title.encode().ljust(width, b'\0')
    raw[0x143] = cartridge.cgb or raw[0x143]
    raw[0x146] = 3 if cartridge.sgb else 0
    raw[0x147] = cartridge.cartridge_type
    raw[0x148] = (cartridge.rom_size // 32768).bit_length() - 1
    raw[0x149] = 3
    raw[0x14A], raw[0x14B], raw[0x14C] = 1, 0x33, cartridge.revision
    check = 0
    for value in raw[0x134:0x14D]:
        check = (check - value - 1) & 0xFF
    raw[0x14D] = check
    raw[0x14E:0x150] = ((sum(raw) - raw[0x14E] - raw[0x14F]) & 0xFFFF).to_bytes(2, 'big')
    return bytes(raw)


def test_registry_matches_pokesim_shelf():
    assert [c.version for c in CARTRIDGES] == list(cartridges.SLOTS)
    assert cartridges.supported_versions() == ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal']
    assert by_version('crystal').title == 'Pokémon Crystal (Rev 1)' and by_version('crystal').revision == 1
    assert by_version('yellow').starters == ('pikachu',)
    assert [c.generation for c in CARTRIDGES] == [1, 1, 1, 2, 2, 2]
    assert [c.rtc for c in CARTRIDGES] == [False, False, False, True, True, True]
    assert by_version('crystal').cgb_only and by_version('yellow').color and not by_version('red').color
    assert cartridges.unsupported_message() == (
        'This file is not a game PokeSim can play. Add a clean English Pokémon Red, Blue, Yellow, Gold, '
        'Silver or Crystal ROM (Crystal must be Rev 1), as a .gb or .gbc file or a ZIP holding one.')
    with pytest.raises(ValueError, match='Unknown cartridge version'):
        by_version('green')
    cartridges.validate_starter('pikachu', 'yellow')
    cartridges.validate_starter('random', 'gold')
    with pytest.raises(ValueError, match='Choose a starter'):
        cartridges.validate_starter('bulbasaur', 'yellow')


@pytest.mark.parametrize('cartridge', CARTRIDGES, ids=lambda c: c.version)
def test_synthetic_headers_decode_but_never_identify(cartridge):
    raw = synthetic_rom(cartridge)
    header = read_header(raw)
    assert header.title == cartridge.header_title and header.header_checksum_ok and header.global_checksum_ok
    assert identify(raw) is None and cartridges.header_matches(raw, cartridge)
    assert cartridges.resembles(raw) == cartridge
    assert 'not a clean, unmodified copy' in cartridges.refusal_reason(raw)
    with pytest.raises(ValueError, match='not a game PokeSim can play'):
        unpack(raw)


def test_header_checks_and_refusals():
    with pytest.raises(ValueError):
        read_header(b'short')
    raw = bytearray(synthetic_rom(by_version('red')))
    raw[0x14D] ^= 1
    assert not read_header(bytes(raw)).header_checksum_ok
    assert not cartridges.header_matches(bytes(raw), by_version('red'))
    assert cartridges.refusal_reason(b'\0' * 0x200) == cartridges.unsupported_message()
    assert cartridges.unsupported_message('PokeBench').startswith('This file is not a game PokeBench can play.')


def test_zip_rules():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('a.gb', b'1')
        archive.writestr('b.gbc', b'2')
    with pytest.raises(ValueError, match='exactly one'):
        unpack(buffer.getvalue())
    with pytest.raises(ValueError, match='intact'):
        unpack(b'PK\x03\x04broken')


def test_rom_module_keeps_its_red_blue_contract(tmp_path):
    assert set(KNOWN_ROM_SHA1) == {RED_SHA1, BLUE_SHA1}
    assert KNOWN_ROM_SHA1[RED_SHA1] == 'Pokemon Red (USA, Europe)'
    path = tmp_path / 'synthetic.gbc'
    path.write_bytes(synthetic_rom(by_version('yellow'), 0x8000))
    assert not inspect_rom(path).verified
    with pytest.raises(ValueError, match='Pokemon Red or Blue ROM is required'):
        require_rom(path)
    with pytest.raises(ValueError, match='Pokemon Yellow ROM is required'):
        require_rom(path, allowed_games=('yellow',))
    assert cartridges.identify_file(path) is None
