"""Smoke tests that need a ROM (skipped when none is configured)."""
import os
import hashlib
from pathlib import Path

import pytest

from pokesim.ram import read_snapshot

ROM = Path(os.environ.get("ROM_PATH", "roms/pokered.gb"))
pytestmark = pytest.mark.skipif(not ROM.exists(), reason="no ROM")


def test_boot_and_snapshot():
    from pyboy import PyBoy
    pb = PyBoy(str(ROM), window="null", sound_emulated=False)
    try:
        pb.set_emulation_speed(0)
        assert pb.cartridge_title.startswith("POKEMON")
        pb.tick(300, render=False)
        s = read_snapshot(pb.memory, 300)
        assert s.map == 0 and not s.started and s.valid
        # mash through the title into the intro: the player name gets a preset value
        for _ in range(120):
            pb.button("a", delay=2)
            pb.tick(8, render=False)
        s = read_snapshot(pb.memory, 1260)
        assert s.player_name != ""
    finally:
        pb.stop(save=False)


def test_strategic_replay_is_repeatable_from_power_on():
    from pokesim.benchmark import run
    from pokesim.config import KNOWN_ROM_SHA1
    if hashlib.sha1(ROM.read_bytes()).hexdigest() not in KNOWN_ROM_SHA1:
        pytest.skip("strategic opening scenario requires a recognized Red or Blue ROM")
    # Allow time to enter full trainer names and the starter's nickname.
    first = run(ROM, "strategic", 1, 12000)
    second = run(ROM, "strategic", 1, 12000)
    assert first == second
    assert "starter" in first["milestones"]
    assert first["frames"] == 12000
    from pokesim.policies.naming import POKEMON_NAMES, TRAINER_NAMES
    game = first["final"]
    assert game["player_name"] in TRAINER_NAMES
    assert game["rival_name"] in TRAINER_NAMES
    assert game["player_name"] != game["rival_name"]
    assert game["party"][0]["nick"] in POKEMON_NAMES


@pytest.mark.parametrize('starter,dex', [('bulbasaur', 1), ('charmander', 4), ('squirtle', 7)])
def test_all_starters_complete_the_opening_with_the_requested_partner(monkeypatch, starter, dex):
    from pokesim import config
    from pokesim.benchmark import run
    from pokesim.strategy_data import SPECIES
    if hashlib.sha1(ROM.read_bytes()).hexdigest() not in config.KNOWN_ROM_SHA1:
        pytest.skip('Opening scenario requires a recognized Red or Blue ROM')
    monkeypatch.setattr(config, 'STARTER', starter)
    result = run(ROM, 'strategic', 1, 96000, target='pokedex')
    assert result['success'], result['final_screen']
    assert SPECIES[result['final']['party'][0]['species']]['dex'] == dex
    assert result['recovery_reloads'] == 0
