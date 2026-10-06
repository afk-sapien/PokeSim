"""Verified cartridges and generation-specific settings."""
from dataclasses import dataclass
import hashlib
import io
from pathlib import PurePosixPath
import zipfile


@dataclass(frozen=True)
class Cartridge:
    version: str
    generation: int
    sha1: str
    title: str
    starters: tuple[str, ...]


KANTO_STARTERS = ('bulbasaur', 'charmander', 'squirtle')
JOHTO_STARTERS = ('chikorita', 'cyndaquil', 'totodile')
CARTRIDGES = (
    Cartridge('red', 1, 'ea9bcae617fdf159b045185467ae58b2e4a48b9a', 'Pokémon Red', KANTO_STARTERS),
    Cartridge('blue', 1, 'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2', 'Pokémon Blue', KANTO_STARTERS),
    Cartridge('gold', 2, 'd8b8a3600a465308c9953dfa04f0081c05bdcb94', 'Pokémon Gold', JOHTO_STARTERS),
    Cartridge('silver', 2, '49b163f7e57702bc939d642a18f591de55d92dae', 'Pokémon Silver', JOHTO_STARTERS),
    Cartridge('crystal', 2, 'f2f52230b536214ef7c9924f483392993e226cfb', 'Pokémon Crystal (Rev 1)', JOHTO_STARTERS),
)


def identify(raw):
    digest = hashlib.sha1(raw).hexdigest()
    return next((cartridge for cartridge in CARTRIDGES if cartridge.sha1 == digest), None)


def by_version(version):
    cartridge = next((cartridge for cartridge in CARTRIDGES if cartridge.version == version), None)
    if cartridge is None:
        raise ValueError('Unknown cartridge version')
    return cartridge


def validate_starter(starter, version=None):
    choices = by_version(version).starters if version else (*KANTO_STARTERS, *JOHTO_STARTERS)
    if starter != 'random' and starter not in choices:
        raise ValueError('Choose a starter from this cartridge')


def unpack(raw):
    """Accept a verified cartridge or a ZIP containing exactly one cartridge."""
    if raw[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()
                           and PurePosixPath(entry.filename).suffix.lower() in {'.gb', '.gbc'}]
                if len(entries) != 1 or entries[0].file_size > 2 * 1024 * 1024:
                    raise ValueError('Choose a ZIP containing exactly one supported cartridge')
                raw = archive.read(entries[0])
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
            raise ValueError('Choose an intact, unencrypted ROM ZIP') from error
    if identify(raw) is None:
        raise ValueError('Choose a clean supported Red, Blue, Gold, Silver or Crystal ROM')
    return raw
