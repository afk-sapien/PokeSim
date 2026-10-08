"""Yellow joins the Red and Blue Cable Club and the Gold, Silver and Crystal Time Capsule."""
import os
from pathlib import Path

import pytest

from pokesim.interactions.cable_metadata import BUILDS, CORE_BUILDS, YELLOW_CODE
from pokesim.yellow import YELLOW_SHA1

RED_SHA1 = 'ea9bcae617fdf159b045185467ae58b2e4a48b9a'
ROM = Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc'))


def test_yellow_build_reads_red_addresses_and_runs_yellow_code():
    red, yellow = BUILDS[RED_SHA1], BUILDS[YELLOW_SHA1]
    assert yellow['version'] == 'Yellow'
    assert set(yellow['symbols']) == set(red['symbols'])
    assert set(yellow['signatures']) == set(red['signatures'])
    for name, value in red['symbols'].items():
        if name in YELLOW_CODE:
            assert yellow['symbols'][name] == YELLOW_CODE[name][0]
        else:
            # The Yellow emulator translates Red RAM, HRAM and cartridge RAM addresses.
            assert yellow['symbols'][name] == value, name
    assert all(build in BUILDS for build in CORE_BUILDS)


def test_link_code_sites_are_banked_rom_addresses():
    for name, ((bank, address), signature) in YELLOW_CODE.items():
        assert (bank == 0 and address < 0x4000) or (bank and 0x4000 <= address < 0x8000), name
        assert len(bytes.fromhex(signature)) == 8


@pytest.mark.skipif(not ROM.exists(), reason='no Yellow ROM')
def test_signatures_match_the_retail_cartridge():
    import hashlib
    raw = ROM.read_bytes()
    assert hashlib.sha1(raw).hexdigest() == YELLOW_SHA1
    for name, ((bank, address), signature) in YELLOW_CODE.items():
        offset = bank * 0x4000 + address % 0x4000
        assert raw[offset:offset + 8].hex() == signature, name
    # The cable endpoint parks the CPU on padding at 0x3FF0.
    assert raw[0x3FF0:0x3FF2] == b'\0\0'


def test_coordinator_admits_yellow_for_cable_and_time_capsule():
    source = (Path(__file__).resolve().parents[1] / 'pokesim/app/coordinator.py').read_text()
    assert source.count("{'red', 'blue', 'yellow', 'gold', 'silver', 'crystal'}") == 2
    assert "in {'red', 'blue', 'yellow'}" in source


def test_cable_and_save_paths_open_yellow_through_the_translating_emulator():
    root = Path(__file__).resolve().parents[1] / 'pokesim'
    for path in ('interactions/cable.py', 'interactions/verification.py', 'runtime/participant.py', 'trade/execute.py'):
        assert 'open_emulator(' in (root / path).read_text(), path


class _Side:
    def __init__(self, menu=0):
        from collections import Counter
        self.counts = Counter({'TradeCenter_SelectMon': 1})
        self.menu = menu
        self.spec = type('Spec', (), {'party_slot': 5})()

    def get(self, name):
        return self.menu


class _Screen:
    def __init__(self, cursor):
        self.cursor, self.text, self.top_x, self.top_y = cursor, 'PIKACHU\nCANCEL' if cursor else '', 1, 1


@pytest.mark.parametrize('cursor, expected', [(None, None), ((1, 1), 'down')])
def test_time_capsule_waits_for_the_trade_menu_cursor(monkeypatch, cursor, expected):
    # Yellow draws the menu fast enough to take a held A as a choice of the first Pokémon.
    import pokesim.screen
    from pokesim.gen2.timecapsule import MixedDriver
    monkeypatch.setattr(pokesim.screen, 'Screen', lambda memory: _Screen(cursor))
    driver = MixedDriver.__new__(MixedDriver)
    driver.gen1 = _Side()
    driver.gen1.pb = type('PB', (), {'memory': None})()
    assert driver.gen1_button(0) == expected
