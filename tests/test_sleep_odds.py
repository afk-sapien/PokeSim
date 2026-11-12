"""The static legendary sleeper's odds count the turns Safeguard is up."""
import pytest

from pokesim.gen2.quests import sleep_odds


def test_without_safeguard_the_odds_are_one_try_a_turn_until_the_sleeper_faints():
    for hits in range(1, 12):
        for faster in (True, False):
            tries = min(8, hits if faster else hits - 1)
            assert sleep_odds(0.6, hits, 0, faster) == pytest.approx(1 - 0.4 ** tries)


def test_safeguard_turns_cost_the_sleeper_its_tries():
    # Lugia and Ho-Oh know Safeguard as one move in four. A sleeper that lasts a few hits loses tries to it.
    for hits in (3, 4, 6):
        for faster in (True, False):
            assert sleep_odds(0.6, hits, 0.25, faster) < sleep_odds(0.6, hits, 0, faster)
    # A legendary that only casts Safeguard holds a slower sleeper off for good, and gives a faster one a
    # try each time it lapses.
    assert sleep_odds(0.6, 1, 1, False) == 0
    assert sleep_odds(0.6, 1, 1, True) == pytest.approx(1 - 0.4 ** 8)
    # One hit still faints a slower sleeper before it moves.
    assert sleep_odds(0.6, 1, 0.25, False) == 0
