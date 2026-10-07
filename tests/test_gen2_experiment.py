"""Gen II decoder boundaries and optional owner-supplied cartridge checks."""
import json
import os
from pathlib import Path
import zipfile

import pytest

from pokesim.experimental.gen2 import PROFILES, ROM_SIZE, decode_name, dex_flags, identify, load_rom, read_snapshot


class BankedMemory:
    """Reject implicit bank access, writes and PyBoy's unsupported empty slices."""
    def __init__(self):
        self.data = bytearray(65536)

    def __getitem__(self, key):
        bank, span = key
        assert bank == 1
        assert span.start < span.stop
        return self.data[span]


@pytest.mark.parametrize('profile', PROFILES, ids=lambda profile: profile.game)
def test_empty_party_and_distinct_map_identity(profile):
    memory = BankedMemory()
    layout = profile.layout
    memory.data[layout.player_name:layout.player_name + 5] = bytes([0x86, 0x8E, 0x8B, 0x83, 0x50])
    memory.data[layout.map_group:layout.map_group + 4] = bytes([24, 7, 3, 4])
    memory.data[layout.badges:layout.badges + 2] = bytes([0x80, 0x01])
    snapshot = read_snapshot(memory, profile)
    assert snapshot.player_name == 'GOLD'
    assert (snapshot.map_group, snapshot.map_number, snapshot.x, snapshot.y) == (24, 7, 4, 3)
    assert (snapshot.johto_badges, snapshot.kanto_badges) == (0x80, 0x01)
    assert snapshot.party == ()


@pytest.mark.parametrize('profile', PROFILES, ids=lambda profile: profile.game)
def test_party_uses_gen2_stride_split_special_and_egg_marker(profile):
    memory = BankedMemory()
    layout = profile.layout
    memory.data[layout.party_count:layout.party_count + 4] = bytes([2, 155, 0xFD, 0xFF])
    for slot, species in enumerate([155, 175]):
        start = layout.party_mons + slot * 48
        memory.data[start:start + 6] = bytes([species, 0xAD, 1, 2, 3, 4])
        memory.data[start + 31] = 5 + slot
        # Big-endian HP above 255 catches accidental one-byte or little-endian reads.
        stats = [258, 300, 10, 11, 12, 13, 14]
        memory.data[start + 34:start + 48] = b''.join(value.to_bytes(2, 'big') for value in stats)
        memory.data[layout.party_nicknames + slot * 11] = 0x50
    snapshot = read_snapshot(memory, profile)
    first, second = snapshot.party
    assert (first.species, second.species) == (155, 175)
    assert (first.level, second.level) == (5, 6)
    assert (first.hp, first.max_hp, first.attack, first.defense, first.speed) == (258, 300, 10, 11, 12)
    assert (first.special_attack, first.special_defense) == (13, 14)
    assert first.held_item == 0xAD
    assert first.moves == (1, 2, 3, 4)
    assert not first.egg and second.egg


@pytest.mark.parametrize('profile', PROFILES, ids=lambda profile: profile.game)
def test_invalid_party_count_and_species_fail_closed(profile):
    memory = BankedMemory()
    memory.data[profile.layout.party_count] = 7
    with pytest.raises(ValueError, match='party count'):
        read_snapshot(memory, profile)
    memory.data[profile.layout.party_count] = 1
    memory.data[profile.layout.party_mons] = 252
    with pytest.raises(ValueError, match='species'):
        read_snapshot(memory, profile)


def test_dex_includes_251_and_ignores_padding():
    flags = bytearray(32)
    flags[0] = 1
    flags[-1] = 0xFF
    assert dex_flags(flags) == (1, 249, 250, 251)


def test_name_terminator_and_unknown_bytes():
    assert decode_name(bytes([0x80, 0xA1, 0x7F, 0xFF, 0x50, 0x81])) == 'Ab 9'
    assert decode_name(bytes([0x01, 0x50])) == '<01>'


def test_title_is_not_enough_to_identify_a_rom():
    raw = bytearray(ROM_SIZE)
    raw[0x134:0x13F] = b'POKEMON_GLD'
    with pytest.raises(ValueError, match='Unrecognized'):
        identify(raw)


@pytest.mark.parametrize('entries', [[], ['one.gbc', 'two.gbc'], ['one.txt']])
def test_zip_requires_exactly_one_cartridge(tmp_path, entries):
    path = tmp_path / 'input.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for entry in entries:
            archive.writestr(entry, b'not a ROM')
    with pytest.raises(ValueError, match='exactly one'):
        load_rom(path)


def test_zip_does_not_extract_paths(tmp_path):
    path = tmp_path / 'input.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('../escape.gbc', bytes(ROM_SIZE))
    with pytest.raises(ValueError, match='Unrecognized'):
        load_rom(path)
    assert not (tmp_path.parent / 'escape.gbc').exists()


def test_wrong_size_is_rejected_before_emulation(tmp_path):
    for suffix in ['.gbc', '.zip']:
        path = tmp_path / ('input' + suffix)
        if suffix == '.zip':
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('game.gbc', b'short')
        else:
            path.write_bytes(b'short')
        with pytest.raises(ValueError, match='2 MiB'):
            load_rom(path)


@pytest.mark.parametrize('profile', PROFILES, ids=lambda profile: profile.game)
def test_profiles_match_recorded_upstream_symbols(profile):
    source = Path(__file__).resolve().parents[1] / 'docs/validation/gen2-symbols.json'
    symbols = json.loads(source.read_text())[profile.symbols]['addresses']
    fields = {'player_name': 'wPlayerName', 'map_group': 'wMapGroup', 'party_count': 'wPartyCount',
              'party_mons': 'wPartyMons', 'party_nicknames': 'wPartyMonNicknames', 'caught': 'wPokedexCaught',
              'seen': 'wPokedexSeen', 'badges': 'wJohtoBadges', 'battle_mode': 'wBattleMode'}
    for field, symbol in fields.items():
        bank, address = symbols[symbol].split(':')
        assert int(bank, 16) == 1
        assert getattr(profile.layout, field) == int(address, 16)
    assert int(symbols['wPartyMon2'].split(':')[1], 16) - profile.layout.party_mons == 48


@pytest.mark.parametrize('profile', PROFILES, ids=lambda profile: profile.game)
def test_real_cartridge_probe(tmp_path, profile):
    directory = os.environ.get('GEN2_CARTRIDGE_DIR')
    if not directory:
        pytest.skip('Set GEN2_CARTRIDGE_DIR to private extracted cartridges')
    from tools.probe_gen2 import probe
    source = Path(directory) / f'{profile.game}.gbc'
    result = probe(source, tmp_path / profile.game)
    assert all(result['checks'].values())
    assert result['sha1'] == profile.sha1
    assert result['production_support'] is False
