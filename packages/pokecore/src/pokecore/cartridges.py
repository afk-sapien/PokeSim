"""One registry of the clean English cartridges PokeSim plays, with header checks.

Identity is the SHA-1 of the whole ROM, as in PokeSim. The header facts below
come from the verified retail files and the pret disassemblies. They let a
caller explain why a file was refused, but never make an unknown file
acceptable. No ROM data is bundled.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import zipfile


@dataclass(frozen=True)
class Cartridge:
    """A supported cartridge. The first five fields match PokeSim's ``Cartridge``."""

    version: str
    generation: int
    sha1: str
    title: str
    starters: tuple[str, ...]
    name: str = ""
    revision: int = 0
    header_title: str = ""
    cgb: int = 0x00
    sgb: bool = True
    rtc: bool = False
    cartridge_type: int = 0x13
    rom_size: int = 1 << 20
    ram_size: int = 32 * 1024
    layout: str = ""

    @property
    def cgb_only(self) -> bool:
        """Crystal sets header byte 0x143 to 0xC0 and does not run on an original Game Boy."""
        return self.cgb == 0xC0

    @property
    def color(self) -> bool:
        """Whether the cartridge enables Game Boy Color features."""
        return bool(self.cgb & 0x80)


class UnsupportedCartridge(ValueError):
    """The ROM is not a Pokémon cartridge Core can read. ``title`` is its header title, or None."""

    def __init__(self, message, title=None):
        super().__init__(message)
        self.title = title


@dataclass(frozen=True)
class Header:
    """Decoded cartridge header fields from 0x134 through 0x14F."""

    title: str
    manufacturer: str
    cgb: int
    licensee: str
    sgb: bool
    cartridge_type: int
    rom_size: int
    ram_size: int
    destination: int
    old_licensee: int
    version: int
    header_checksum: int
    global_checksum: int
    header_checksum_ok: bool
    global_checksum_ok: bool


KANTO_STARTERS = ('bulbasaur', 'charmander', 'squirtle')
JOHTO_STARTERS = ('chikorita', 'cyndaquil', 'totodile')
# Professor Oak gives Pikachu in Yellow. The other Kanto starters arrive as gifts later.
YELLOW_STARTERS = ('pikachu',)

RED_SHA1 = 'ea9bcae617fdf159b045185467ae58b2e4a48b9a'
BLUE_SHA1 = 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2'
YELLOW_SHA1 = 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'
GOLD_SHA1 = 'd8b8a3600a465308c9953dfa04f0081c05bdcb94'
SILVER_SHA1 = '49b163f7e57702bc939d642a18f591de55d92dae'
CRYSTAL_SHA1 = 'f2f52230b536214ef7c9924f483392993e226cfb'

_MBC3_RAM_BATTERY, _MBC5_RAM_BATTERY, _MBC3_TIMER_RAM_BATTERY = 0x13, 0x1B, 0x10

CARTRIDGES = (
    Cartridge('red', 1, RED_SHA1, 'Pokémon Red', KANTO_STARTERS, 'Pokemon Red (USA, Europe)',
              0, 'POKEMON RED', 0x00, True, False, _MBC3_RAM_BATTERY, 1 << 20, 32 * 1024, 'red'),
    Cartridge('blue', 1, BLUE_SHA1, 'Pokémon Blue', KANTO_STARTERS, 'Pokemon Blue (USA, Europe)',
              0, 'POKEMON BLUE', 0x00, True, False, _MBC3_RAM_BATTERY, 1 << 20, 32 * 1024, 'red'),
    Cartridge('yellow', 1, YELLOW_SHA1, 'Pokémon Yellow', YELLOW_STARTERS,
              'Pokemon Yellow (USA, Europe) (GBC,SGB Enhanced)',
              0, 'POKEMON YELLOW', 0x80, True, False, _MBC5_RAM_BATTERY, 1 << 20, 32 * 1024, 'yellow'),
    Cartridge('gold', 2, GOLD_SHA1, 'Pokémon Gold', JOHTO_STARTERS, 'Pokemon Gold (USA, Europe)',
              0, 'POKEMON_GLDAAUE', 0x80, True, True, _MBC3_TIMER_RAM_BATTERY, 2 << 20, 32 * 1024, 'gold'),
    Cartridge('silver', 2, SILVER_SHA1, 'Pokémon Silver', JOHTO_STARTERS, 'Pokemon Silver (USA, Europe)',
              0, 'POKEMON_SLVAAXE', 0x80, True, True, _MBC3_TIMER_RAM_BATTERY, 2 << 20, 32 * 1024, 'gold'),
    Cartridge('crystal', 2, CRYSTAL_SHA1, 'Pokémon Crystal (Rev 1)', JOHTO_STARTERS,
              'Pokemon Crystal (USA, Europe) (Rev 1)',
              1, 'PM_CRYSTAL', 0xC0, False, True, _MBC3_TIMER_RAM_BATTERY, 2 << 20, 32 * 1024, 'crystal'),
)

# Clean English releases that PokeSim deliberately refuses, from pret/pokecrystal roms.sha1.
REFUSED = {
    'f4cd194bdee0d04ca4eac29e09b8e4e9d818c133': ('crystal', 'Pokémon Crystal (Rev 0) is not supported. '
                                                 'Use the Rev 1 cartridge.'),
    'a0fc810f1d4e124434f7be2c989ab5b5892ddf36': ('crystal', 'The Australian Pokémon Crystal is not supported. '
                                                 'Use the USA/Europe Rev 1 cartridge.'),
}

# The shelf in PokeSim's Settings has one slot per game, in this order.
SLOTS = ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal')
SLOT_TITLES = {version: f'Pokémon {version.capitalize()}' for version in SLOTS}
SLOT_GENERATIONS = {'red': 1, 'blue': 1, 'yellow': 1, 'gold': 2, 'silver': 2, 'crystal': 2}

_BY_SHA1 = {cartridge.sha1: cartridge for cartridge in CARTRIDGES}
_BY_VERSION = {cartridge.version: cartridge for cartridge in CARTRIDGES}
MAX_ROM_BYTES = 2 * 1024 * 1024


def supported_versions(cartridges=CARTRIDGES):
    """The versions the registry identifies, in shelf order."""
    known = {cartridge.version for cartridge in cartridges}
    return [version for version in SLOTS if version in known] + sorted(known - set(SLOTS))


def supported_names(cartridges=CARTRIDGES):
    names = [version.capitalize() for version in supported_versions(cartridges)]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' or ' + names[-1]


def unsupported_message(app='PokeSim', cartridges=CARTRIDGES):
    """PokeSim's refusal wording. ``app`` names the program that refuses the file."""
    return (f'This file is not a game {app} can play. Add a clean English Pokémon {supported_names(cartridges)} ROM '
            '(Crystal must be Rev 1), as a .gb or .gbc file or a ZIP holding one.')


def sha1(raw) -> str:
    return hashlib.sha1(raw).hexdigest()


def identify(raw) -> Cartridge | None:
    """Return the cartridge whose SHA-1 matches ``raw`` exactly, or None."""
    return _BY_SHA1.get(sha1(raw))


def identify_sha1(digest: str) -> Cartridge | None:
    return _BY_SHA1.get(digest.lower()) if isinstance(digest, str) else None


def identify_file(path) -> Cartridge | None:
    """Hash a ROM file read-only and identify it."""
    digest = hashlib.sha1()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _BY_SHA1.get(digest.hexdigest())


def by_version(version) -> Cartridge:
    cartridge = _BY_VERSION.get(version)
    if cartridge is None:
        raise ValueError('Unknown cartridge version')
    return cartridge


def generation(version) -> int:
    return by_version(version).generation


def validate_starter(starter, version=None):
    choices = by_version(version).starters if version else (*KANTO_STARTERS, *YELLOW_STARTERS, *JOHTO_STARTERS)
    if starter != 'random' and starter not in choices:
        raise ValueError('Choose a starter from this cartridge')


def read_header(raw) -> Header:
    """Decode the cartridge header and verify both checksums without trusting the title."""
    raw = bytes(raw)
    if len(raw) < 0x150:
        raise ValueError('ROM is too small to hold a cartridge header')
    check = 0
    for value in raw[0x134:0x14D]:
        check = (check - value - 1) & 0xFF
    stored_global = int.from_bytes(raw[0x14E:0x150], 'big')
    computed_global = (sum(raw) - raw[0x14E] - raw[0x14F]) & 0xFFFF
    cgb = raw[0x143]
    # Colour cartridges give byte 0x143 to the CGB flag. The last four title bytes may hold a
    # manufacturer code, which Gold and Silver write without a separator, so keep them in the title.
    title = raw[0x134:0x143 if cgb & 0x80 else 0x144].split(b'\0', 1)[0].decode('ascii', 'replace')
    code = raw[0x13F:0x143]
    manufacturer = code.decode('ascii') if cgb & 0x80 and code.isalnum() and code.isupper() else ''
    return Header(title, manufacturer, cgb if cgb & 0x80 else 0, raw[0x144:0x146].decode('ascii', 'replace'),
                  raw[0x146] == 0x03, raw[0x147], 32768 << raw[0x148] if raw[0x148] < 9 else 0,
                  {0: 0, 2: 8192, 3: 32768, 4: 131072, 5: 65536}.get(raw[0x149], 0), raw[0x14A],
                  raw[0x14B], raw[0x14C], raw[0x14D], stored_global, raw[0x14D] == check,
                  stored_global == computed_global)


def header_matches(raw, cartridge: Cartridge) -> bool:
    """Whether the header carries the registered title, flags, mapper and sizes of ``cartridge``."""
    try:
        header = read_header(raw)
    except ValueError:
        return False
    return (header.title == cartridge.header_title and header.cgb == cartridge.cgb
            and header.sgb == cartridge.sgb and header.cartridge_type == cartridge.cartridge_type
            and header.rom_size == cartridge.rom_size == len(raw) and header.ram_size == cartridge.ram_size
            and header.version == cartridge.revision and header.header_checksum_ok and header.global_checksum_ok)


def resembles(raw) -> Cartridge | None:
    """The registered cartridge whose header ``raw`` imitates, regardless of its hash.

    Use it only to explain a refusal, such as a patched, trimmed or modified copy.
    """
    try:
        header = read_header(raw)
    except ValueError:
        return None
    return next((cartridge for cartridge in CARTRIDGES if header.title == cartridge.header_title), None)


def refusal_reason(raw, app='PokeSim') -> str | None:
    """None for a supported cartridge, otherwise the most specific explanation available."""
    digest = sha1(raw)
    if digest in _BY_SHA1:
        return None
    if digest in REFUSED:
        return REFUSED[digest][1]
    similar = resembles(raw)
    if similar is not None:
        return (f'This looks like {similar.title}, but it is not a clean, unmodified copy. '
                + unsupported_message(app))
    return unsupported_message(app)


def unpack(raw, app='PokeSim'):
    """Accept a verified cartridge or a ZIP containing exactly one cartridge, as PokeSim does."""
    if raw[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()
                           and PurePosixPath(entry.filename).suffix.lower() in {'.gb', '.gbc'}]
                if len(entries) != 1 or entries[0].file_size > MAX_ROM_BYTES:
                    raise ValueError('Choose a ZIP containing exactly one supported cartridge')
                raw = archive.read(entries[0])
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
            raise ValueError('Choose an intact, unencrypted ROM ZIP') from error
    if identify(raw) is None:
        raise ValueError(unsupported_message(app))
    return raw
