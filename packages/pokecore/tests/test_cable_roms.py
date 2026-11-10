"""Cable endpoints and Center checks on real cartridges.

Collected only when POKESIM_CORE_ROMS (red.gb, blue.gb, yellow.gb) or
POKESIM_CORE_GEN2_ROMS (gold.gbc, silver.gbc, crystal.gbc) names a folder of ROMs.
No two-cartridge saves are committed, so these cases check the attachment, the
parking padding and the driver's first decisions on a new game, not a whole trade.
"""
import hashlib
import os
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokecore import gen1_link_metadata, gen2_link_metadata
from pokecore.centers import location, safe_center
from pokecore.gen1_cable import CableEndpoint
from pokecore.gen2 import GameTables
from pokecore.gen2.cable import CableDriver, CableSide, TimeCapsuleSide
from pokecore.timecapsule import communication_ok
from rom_games import BEDROOM, new_gen1_game, new_gen2_game

pytest.importorskip('pyboy_rs')

CENTER_2F = 20 * 256 + 2


def _rom(variable, name):
    directory = os.environ.get(variable)
    if not directory:
        pytest.skip(f'set {variable} to a folder of cartridges to run')
    path = Path(directory) / name
    if not path.exists():
        pytest.skip(f'{name} is not in {variable}')
    return path.read_bytes()


@pytest.fixture(params=['gold', 'silver', 'crystal'])
def gen2(request):
    return request.param, _rom('POKESIM_CORE_GEN2_ROMS', f'{request.param}.gbc')


@pytest.fixture(params=['red', 'blue', 'yellow'])
def gen1(request):
    return request.param, _rom('POKESIM_CORE_ROMS', f'{request.param}.gb')


def _peer():
    return SimpleNamespace(inbox={'byte': deque(), 'nybble': deque()})


def _run_attached(endpoint, frames=120):
    endpoint.peer = _peer()
    endpoint.attach(1)
    assert bytes(endpoint.pb.memory[0, 0x3ff0:0x3ff2]) == bytes([0x18, 0xfe])
    for _ in range(frames):
        assert endpoint.tick()
    endpoint.detach()
    assert bytes(endpoint.pb.memory[0, 0x3ff0:0x3ff2]) == bytes(2)
    assert not endpoint.hooks and not endpoint.attached


def test_gen1_endpoint_attaches_and_restores_padding(gen1):
    _, rom = gen1
    sha1 = hashlib.sha1(rom).hexdigest()
    assert gen1_link_metadata.verify_signatures(rom, sha1) == []
    emulator = new_gen1_game(rom)
    try:
        _run_attached(CableEndpoint(emulator, gen1_link_metadata.build(sha1)['symbols']))
        view = location(emulator.memory)
        assert view.valid and view.started and not view.in_battle
        assert not safe_center(view, view.map, emulator.memory)    # the bedroom has no attendant
    finally:
        emulator.stop(save=False)


def test_gen2_sides_attach_and_head_for_the_center(gen2):
    version, rom = gen2
    sha1 = hashlib.sha1(rom).hexdigest()
    assert gen2_link_metadata.verify_signatures(rom, sha1) == []
    assert communication_ok(rom, version)
    data = GameTables({'game': version, 'map_ids': {'POKECENTER_2F': CENTER_2F},
                       'maps': {str(BEDROOM): {'constant': 'PLAYERS_HOUSE_2F'}}})
    symbols = gen2_link_metadata.build(sha1)['symbols']
    emulator = new_gen2_game(rom, version)
    try:
        _run_attached(CableSide(emulator, symbols, data))
        side = TimeCapsuleSide(emulator, symbols, data, rom)
        _run_attached(side)
        targets = []
        driver = CableDriver([side], SimpleNamespace(), walk=lambda side, s, target: targets.append(target))
        assert driver.button(side) is None
        assert targets == [(CENTER_2F, 13, 4)]
        side.time_capsule = False
        driver.button(side)
        assert targets[-1] == (CENTER_2F, 5, 3)
    finally:
        emulator.stop(save=False)
