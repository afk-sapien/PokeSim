"""ROM identity without importing the emulator or modifying user files.

The cartridge registry in ``cartridges`` is the source of truth. This module keeps
the 0.1.x Red and Blue surface: ``KNOWN_ROM_SHA1`` and ``inspect_rom`` describe
only Red and Blue, so existing consumers never treat another cartridge as a
verified Red/Blue layout. ``require_rom`` accepts any registered version that
the caller names in ``allowed_games``.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from .cartridges import BLUE_SHA1 as BLUE_SHA1, CARTRIDGES, RED_SHA1 as RED_SHA1, identify_sha1

LEGACY_GAMES = ("red", "blue")
KNOWN_ROM_SHA1 = {cartridge.sha1: cartridge.name for cartridge in CARTRIDGES if cartridge.version in LEGACY_GAMES}
_GAMES = {cartridge.sha1: cartridge.version for cartridge in CARTRIDGES if cartridge.version in LEGACY_GAMES}


@dataclass(frozen=True)
class RomInfo:
    sha1: str
    sha256: str
    game: str | None
    name: str
    verified: bool


def rom_offset(bank, address):
    """File offset of a banked ROM address. Bank 0 is the fixed home bank."""
    return address if bank == 0 else bank * 0x4000 + address % 0x4000


def _hashes(path):
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha1.update(chunk)
            sha256.update(chunk)
    return sha1.hexdigest(), sha256.hexdigest()


def inspect_rom(path: str | Path) -> RomInfo:
    """Hash a ROM in read-only mode. Unknown ROMs are described without acceptance.

    Only Red and Blue are reported as verified, as in every 0.1.x release. Use
    ``cartridges.identify_file`` to recognize Yellow, Gold, Silver and Crystal.
    """
    identity, digest = _hashes(path)
    return RomInfo(identity, digest, _GAMES.get(identity),
                   KNOWN_ROM_SHA1.get(identity, "Unknown ROM"), identity in KNOWN_ROM_SHA1)


def require_rom(path: str | Path, *, allowed_games=LEGACY_GAMES) -> RomInfo:
    """Require a verified supported ROM before starting an emulator.

    ``allowed_games`` may name any registered version, such as ``("yellow",)``.
    """
    identity, digest = _hashes(path)
    cartridge = identify_sha1(identity)
    if cartridge is None or cartridge.version not in allowed_games:
        raise ValueError("Unsupported ROM hash. A clean supported Pokemon Red or Blue ROM is required."
                         if set(allowed_games) <= set(LEGACY_GAMES) else
                         "Unsupported ROM hash. A clean supported Pokemon "
                         + " or ".join(version.capitalize() for version in allowed_games) + " ROM is required.")
    return RomInfo(identity, digest, cartridge.version, cartridge.name, True)
