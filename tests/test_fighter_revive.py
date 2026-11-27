"""A fighter that faints in a trainer battle is revived once no other fighter stands."""
from pokesim.policies.battle import choose_battle
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_strategy import mon

BAG = ((ITEMS['MAX_REVIVE'], 1), (ITEMS['REVIVE'], 2))
FOE = mon(level=60, hp=200, max_hp=200)


def decide(party, in_battle=2, foe=FOE):
    return choose_battle(snap(party=party, in_battle=in_battle, items=BAG), party[0], foe, 0)


def test_the_last_fighter_close_to_falling_revives_the_strongest_fainted_fighter():
    party = (mon(hp=12, level=50), mon(hp=0, level=48), mon(hp=0, level=55), mon(hp=30, level=20))
    decision = decide(party)
    assert (decision.kind, decision.index, decision.target) == ('item', 1, 2)
    # A low member left standing alone revives a fighter too.
    low = (mon(hp=30, level=20), mon(hp=0, level=55), mon(hp=0, level=50))
    assert (decide(low).kind, decide(low).target) == ('item', 1)


def test_no_revive_while_a_fighter_stands_or_the_battler_is_healthy_or_its_attack_ends_the_foe():
    fainted = mon(hp=0, level=55)
    assert decide((mon(hp=12, level=50), fainted, mon(hp=40, level=45))).kind != 'item'
    assert decide((mon(hp=400, max_hp=400, level=50), fainted)).kind != 'item'
    assert decide((mon(hp=12, level=50), fainted), foe=mon(level=60, hp=1, max_hp=200)).kind != 'item'
    assert decide((mon(hp=12, level=50), fainted), in_battle=1).kind != 'item'
