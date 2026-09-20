"""Freeze never thaws in these games, so a frozen battler hands over or revives a partner."""
from pokesim.policies.battle import FROZEN, choose_battle
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_strategy import mon


def frozen_party(*others):
    return (mon(status=FROZEN, hp=12),) + others


def test_a_frozen_last_partner_revives_the_strongest_fainted_partner():
    # Lance's Aerodactyl had only Normal attacks against a frozen Gengar: neither side could end it.
    party = frozen_party(mon(hp=0, level=30), mon(hp=0, level=57))
    state = snap(party=party, in_battle=2, items=((ITEMS['POKE_BALL'], 8), (ITEMS['REVIVE'], 5)))
    decision = choose_battle(state, party[0], mon(level=60), 0, can_switch=False)
    assert (decision.kind, decision.index, decision.target) == ('item', 1, 2)


def test_a_frozen_battler_hands_over_to_any_partner_who_can_act():
    party = frozen_party(mon(hp=0), mon(hp=5, level=9), mon(hp=40, status=FROZEN))
    state = snap(party=party, in_battle=2, items=((ITEMS['REVIVE'], 1),))
    decision = choose_battle(state, party[0], mon(level=60), 0, can_switch=False)
    assert (decision.kind, decision.index) == ('switch', 2)


def test_an_ice_heal_is_preferred_and_a_wild_battle_is_left_without_options():
    party = frozen_party(mon(hp=0))
    cured = choose_battle(snap(party=party, in_battle=2, items=((ITEMS['ICE_HEAL'], 1), (ITEMS['REVIVE'], 1))),
                          party[0], mon(level=60), 0)
    assert (cured.kind, cured.index, cured.target) == ('item', 0, 0)
    assert choose_battle(snap(party=party, in_battle=1, items=()), party[0], mon(level=5), 0).kind == 'run'
    assert choose_battle(snap(party=party, in_battle=2, items=()), party[0], mon(level=5), 0).kind == 'fight'


def test_the_league_shopping_list_includes_a_cure_for_freeze():
    from pokesim.policies.battle import shopping_item
    stock = [ITEMS[name] for name in ('ULTRA_BALL', 'GREAT_BALL', 'FULL_RESTORE', 'MAX_POTION', 'FULL_HEAL', 'REVIVE', 'MAX_REPEL')]
    stocked = ((ITEMS['REVIVE'], 5), (ITEMS['FULL_RESTORE'], 10), (ITEMS['ULTRA_BALL'], 15))
    assert shopping_item(stocked, stock, 20000, league=True, collecting=True) == ITEMS['FULL_HEAL']
    assert shopping_item(stocked + ((ITEMS['FULL_HEAL'], 3),), stock, 20000, league=True, collecting=True) is None


def test_autosaves_stop_rotating_during_a_battle_that_may_never_end():
    import time
    from types import SimpleNamespace
    from pokesim import config
    from pokesim.emulator import Emulator
    writes = []
    store = SimpleNamespace(get=lambda key: None, set=lambda *a: None, write_checkpoint=lambda *a: writes.append(1),
                            prune_autosaves=lambda n: None, prune_events=lambda n: None)
    game = SimpleNamespace(store=store, play_clock=SimpleNamespace(state_dict=dict), snapshot=None,
                           battle_since=time.time() - config.BATTLE_TIMEOUT_SECONDS)
    Emulator._autosave(game)
    assert writes == [], 'the save from before the battle must survive until the timeout reloads it'
