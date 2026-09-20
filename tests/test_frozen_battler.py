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


def test_a_league_attempt_is_checkpointed_on_entry_and_restarted_when_a_battle_repeats_unending(tmp_path):
    import time
    from types import SimpleNamespace
    from pokesim import emulator
    from pokesim.checkpoints import CheckpointStore
    store = CheckpointStore(tmp_path)
    store.write_checkpoint(b'entry', {'policy_state': {}, 'run_memory': {}}, name=emulator.LEAGUE_CHECKPOINT)
    assert store.autosaves() == [], 'the entry checkpoint is not a rotating autosave'
    assert store.checkpoint_metadata(store.state_path(emulator.LEAGUE_CHECKPOINT))['sha256']
    recent = store.write_checkpoint(b'doomed', {'policy_state': {}, 'run_memory': {}})
    restored = []
    game = SimpleNamespace(store=SimpleNamespace(autosaves=store.autosaves, state_path=store.state_path),
                           snapshot=SimpleNamespace(map=emulator.MAPS['LANCES_ROOM']), reloads=0,
                           _restore_first_valid=lambda paths: restored.append(paths[0].name), _tick=lambda n: None)
    emulator.Emulator._unstick(game, time.time() + 3600, 'battle never ended')
    emulator.Emulator._unstick(game, time.time() + 3600, 'battle never ended')
    assert restored == [recent.name, emulator.LEAGUE_CHECKPOINT]
    game.snapshot.map, game.unstick_streak = emulator.MAPS['ROUTE_1'], 5
    emulator.Emulator._unstick(game, time.time() + 3600, 'battle never ended')
    assert restored[-1] == recent.name, 'outside the League the entry checkpoint is never used'


def lorelei_dewgong():
    # Growl, Aurora Beam, Rest, Take Down. Rest is Psychic, which the trainer routine favours against Poison.
    return mon(level=54, moves=(45, 62, 156, 36), types=(21, 25))


def test_a_foe_that_favours_a_powerless_move_never_attacks():
    from pokesim.policies.battle import foe_never_attacks
    muk, graveler, lapras = mon(types=(3, 3)), mon(types=(5, 4)), mon(types=(21, 25))
    assert foe_never_attacks(lorelei_dewgong(), muk)
    assert not foe_never_attacks(lorelei_dewgong(), graveler)      # Aurora Beam is favoured too, and it hurts
    assert not foe_never_attacks(lorelei_dewgong(), lapras)        # nothing is favoured, so it attacks some turns


def test_a_party_that_cannot_act_hands_over_to_someone_the_foe_will_knock_out():
    from pokesim.policies.battle import HOPELESS
    muk, graveler = mon(status=FROZEN, types=(3, 3)), mon(status=FROZEN, types=(5, 4), level=100)
    state = snap(party=(muk, graveler, mon(hp=0)), in_battle=2, items=())
    decision = choose_battle(state, muk, lorelei_dewgong(), 0, can_switch=False)
    assert (decision.kind, decision.index) == ('switch', 1)
    # The partner being attacked stays in, and a lone battler the foe ignores says the battle cannot end.
    assert choose_battle(state, graveler, lorelei_dewgong(), 1, can_switch=False).kind == 'fight'
    alone = snap(party=(muk, mon(hp=0)), in_battle=2, items=())
    assert choose_battle(alone, muk, lorelei_dewgong(), 0, can_switch=False).reason == HOPELESS


def test_a_hopeless_battle_is_reloaded_without_waiting_for_the_timeout():
    import time
    from types import SimpleNamespace
    from pokesim.emulator import Emulator
    reloaded = []
    game = SimpleNamespace(last_reload=0, invalid_since=None, stuck_since=time.time(), battle_since=time.time() - 90,
                           policy=SimpleNamespace(hopeless_battle=True), _check_stall=lambda now: None,
                           _unstick=lambda since, why: reloaded.append(why))
    Emulator._check_guards(game)
    game.policy.hopeless_battle = False
    Emulator._check_guards(game)
    assert reloaded == ['battle cannot end']
