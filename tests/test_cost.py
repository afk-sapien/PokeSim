"""The shared cost model gives Gold, Silver and Crystal the same search costs they had before it moved."""
import itertools

import pytest

from pokesim.gen2 import standdown
from pokesim.planning import cost


def former_search_expected(chance, maps=0, odds=1.0):
    """gen2/standdown.py search_expected before it moved to planning/cost.py."""
    battles = 1 / (min(100, max(1, chance)) / 100 * odds)
    return maps * 150 + battles * 75


def test_gen2_search_expected_returns_what_it_did():
    assert standdown.search_expected is cost.search_expected
    assert (standdown.DECISIONS_PER_BATTLE, standdown.DECISIONS_PER_MAP) == (75, 150)
    for chance, maps, odds in itertools.product((0, 0.5, 1, 5, 10, 30, 50, 70, 90, 100, 150), (0, 1, 3, 12),
                                                (1.0, 0.75, 0.5, 0.1, 1 / 3)):
        assert cost.search_expected(chance, maps, odds) == former_search_expected(chance, maps, odds)
        assert cost.search_expected(chance, maps=maps, odds=odds) == former_search_expected(chance, maps, odds)
    assert cost.search_expected(10) == former_search_expected(10)


def test_a_search_can_need_several_catches_and_count_in_frames():
    assert cost.search_expected(20, needed=3) == pytest.approx(3 * cost.search_expected(20))
    assert cost.search_expected(50, maps=2, per_map=1000, per_battle=600) == 2 * 1000 + 2 * 600


def test_a_catch_pays_its_encounters_and_a_fixed_overhead_per_catch():
    class Odds:
        def encounter(self, method, map_id, species):
            return 20, 8

        def cast(self, rod, map_id, species):
            return 40, 0.8
    per_battle = cost.FRAMES_PER_BATTLE + 8 * cost.FRAMES_PER_TILE
    assert cost.catch_frames(Odds(), 'grass', 1, 16) == 5 * per_battle + cost.FRAMES_PER_CATCH
    assert cost.catch_frames(Odds(), 'surf', 1, 16, needed=3) == pytest.approx(3 * (5 * per_battle + cost.FRAMES_PER_CATCH))
    rod = cost.FRAMES_PER_CAST + 0.8 * cost.FRAMES_PER_BATTLE
    assert cost.catch_frames(Odds(), 'fish', 1, 129, rod='OLD_ROD') == 2.5 * rod + cost.FRAMES_PER_CATCH
    # With no cartridge, a catch meets its target in one encounter of ten, ten steps apart.
    unpriced = cost.catch_frames(None, 'grass', 1, 16)
    assert unpriced == 10 * (cost.FRAMES_PER_BATTLE + 10 * cost.FRAMES_PER_TILE) + cost.FRAMES_PER_CATCH
    # A species the table never holds costs as much as the rarest slot can.
    class Absent(Odds):
        def encounter(self, method, map_id, species):
            return 0, 8
    assert cost.catch_frames(Absent(), 'grass', 1, 16) == 100 * per_battle + cost.FRAMES_PER_CATCH


@pytest.mark.parametrize('version', ['red', 'blue', 'yellow'])
def test_gen1_odds_come_from_the_cartridge(version):
    import os
    from pathlib import Path
    rom = os.environ.get({'red': 'ROM_PATH', 'blue': 'BLUE_ROM_PATH', 'yellow': 'YELLOW_ROM_PATH'}[version])
    if not rom or not Path(rom).exists():
        pytest.skip('Set ROM_PATH, BLUE_ROM_PATH and YELLOW_ROM_PATH to read real cartridges')
    from pokesim.strategy_data import MAPS, SPECIES
    sid = {row['dex']: species for species, row in SPECIES.items()}
    odds = cost.wild_odds(rom, version)
    chance, steps = odds.encounter('grass', MAPS['ROUTE_1'], sid[16])
    # Route 1 holds Pidgey in its first slots, more of them in Yellow, and meets one every ten steps.
    assert chance == (69.921875 if version == 'yellow' else 50.0) and steps == 256 / 25
    assert odds.encounter('surf', MAPS['ROUTE_1'], sid[16]) == (0, None)
    # Every Old Rod bite is a Magikarp.
    assert odds.cast('OLD_ROD', MAPS['ROUTE_1'], sid[129]) == (100.0, 1.0)
    # Another version's tables are refused rather than read at the wrong addresses.
    other = 'yellow' if version != 'yellow' else 'red'
    assert cost.wild_odds(rom, other) is None


def test_a_cartridge_that_is_not_a_pokemon_game_gives_unpriced_odds(monkeypatch, caplog):
    from pokecore import emulator
    from pokesim import randomized
    monkeypatch.delenv(randomized.ENV, raising=False)
    monkeypatch.setattr(cost, '_WARNED', set())
    # Core refuses the demo ROM before reading it, so the planner falls back to unpriced costs.
    rom = emulator.demo_rom()
    with caplog.at_level('WARNING', logger=cost.__name__):
        assert cost.wild_odds(rom, 'red') is None
        assert cost.wild_odds(rom, 'red') is None
    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1 and str(rom) in warnings[0] and 'header title' in warnings[0]


def test_a_recognised_game_whose_tables_fail_to_read_raises(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    from pokesim import randomized
    rom = os.environ.get('ROM_PATH')
    if not rom or not Path(rom).exists():
        pytest.skip('Set ROM_PATH to a clean Red cartridge')
    monkeypatch.delenv(randomized.ENV, raising=False)
    # A trimmed Red keeps its header, so it is a Pokémon game whose plan would be wrong without its tables.
    trimmed = tmp_path / 'trimmed.gb'
    trimmed.write_bytes(Path(rom).read_bytes()[:0x8000])
    with pytest.raises(IndexError):
        cost.wild_odds(trimmed, 'red')


def test_slot_chance_adds_the_shares_of_every_slot_holding_the_species():
    slots = ((3, 'PIDGEY'), (3, 'RATTATA'), (4, 'PIDGEY'))
    assert cost.slot_chance(slots, 'PIDGEY', (2, 1, 1)) == 75
    assert cost.slot_chance(slots, 'ZUBAT', (2, 1, 1)) == 0
