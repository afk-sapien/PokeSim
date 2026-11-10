import hashlib

import pytest

from pokecore.rom import BLUE_SHA1, KNOWN_ROM_SHA1, RED_SHA1, inspect_rom, require_rom


def test_unknown_rom_is_hashed_without_modifying_it(tmp_path):
    path = tmp_path / "synthetic.gb"
    path.write_bytes(bytes(range(256)))
    before = path.read_bytes()
    info = inspect_rom(path)
    assert info.sha1 == hashlib.sha1(before).hexdigest()
    assert info.sha256 == hashlib.sha256(before).hexdigest()
    assert info.game is None and not info.verified
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="Unsupported ROM"):
        require_rom(path)


def test_known_identity_table_and_missing_rom(tmp_path):
    assert set(KNOWN_ROM_SHA1) == {RED_SHA1, BLUE_SHA1}
    with pytest.raises(FileNotFoundError):
        inspect_rom(tmp_path / "missing.gb")
