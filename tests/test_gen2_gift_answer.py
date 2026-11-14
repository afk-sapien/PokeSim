"""A Gen II gift whose giver is not at the spot the run talks from, or always turns the run away.

A Crystal run bred at the Day Care and wanted the Odd Egg. While a bred egg waits, the Day Care man
stands outside on Route 34 and his spot inside is empty, so the run pressed A there for hours and
reloaded three times without a hatch.
"""
from types import SimpleNamespace

import pytest

from pokesim.gen2.policy import Goal

TAKEN = {'EVENT_GOT_MASTER_BALL_FROM_ELM', 'EVENT_GOT_EEVEE'}


def snapshot(egg_ready=False, flags=TAKEN, party=4, species=()):
    party = [SimpleNamespace(egg=False, species=0, box=None)] * (party - len(species))
    return SimpleNamespace(party=party + [SimpleNamespace(egg=False, species=s, box=None) for s in species],
                           stored=[], box_counts=(0,) * 14, active_box=0, map=0, egg_ready=egg_ready,
                           event=lambda flag: flag in flags)


def policy(game='crystal'):
    storage = Goal('storage', 'PC', 'CHERRYGROVE_POKECENTER_1F', 9, 2, 'up')
    people = []
    return SimpleNamespace(storage_goal=lambda snap: storage, people=people, monitor_tables={}, clock=0,
                           collection={}, data=SimpleNamespace(game=game, map_ids={'SLOWPOKE_WELL_B1F': 1, 'BILLS_HOUSE': 2}),
                           person=lambda snap, key, label, map_name, script:
                           people.append((key, map_name, script)) or Goal(key, label, map_name, 0, 0))


def set_aside(run, key, map_name):
    from pokesim.gen2.quests import GIFT_PRESSES, pressed
    for _ in range(GIFT_PRESSES):
        pressed(run, key, map_name)


def test_the_odd_egg_takes_the_waiting_day_care_egg_from_the_man_outside_first():
    from pokesim.gen2.quests import gifts
    run = policy()
    goal = gifts(run, snapshot(egg_ready=True), Goal)
    assert goal.key == 'collection_breed_egg'
    assert run.people == [('collection_breed_egg', 'ROUTE_34', 'DayCareManScript_Outside')]


def test_the_odd_egg_is_asked_for_inside_once_no_egg_waits():
    from pokesim.gen2.quests import gifts
    run = policy()
    assert gifts(run, snapshot(), Goal).key == 'gift_odd_egg'
    assert run.people == [('gift_odd_egg', 'DAY_CARE', 'DayCareManScript_Inside')]


def test_the_waiting_egg_needs_party_room_like_any_gift():
    from pokesim.gen2.quests import gifts
    assert gifts(policy(), snapshot(egg_ready=True, party=6), Goal).key == 'collection_gift_room'


@pytest.mark.parametrize(('game', 'flags', 'key', 'map_name', 'then'), [
    ('crystal', TAKEN, 'gift_odd_egg', 'DAY_CARE', 'gift_dratini'),
    ('silver', {'EVENT_GOT_MASTER_BALL_FROM_ELM'}, 'gift_eevee', 'BILLS_FAMILYS_HOUSE', 'gift_tyrogue'),
    ('gold', set(), 'gift_master_ball', 'ELMS_LAB', 'gift_eevee'),
])
def test_a_gift_whose_giver_never_answers_stands_down_and_the_next_gift_goes_on(game, flags, key, map_name, then):
    from pokesim.gen2.quests import GIFT_PRESSES, gift_key, gifts, pressed
    from pokesim.gen2.standdown import STAND_DOWN, monitor
    from pokesim.planning import decide
    run = policy(game)
    view = snapshot(flags=flags)
    for _ in range(GIFT_PRESSES - 1):
        pressed(run, key, map_name)
    assert gifts(run, view, Goal).key == key
    pressed(run, key, map_name)
    assert gifts(run, view, Goal).key == then
    assert monitor(run).failure(gift_key(key, map_name), run.clock) == decide.NO_GIFT.kind
    assert decide.FAILURES[decide.NO_GIFT.kind] is decide.NO_GIFT
    # The gift comes back once its stand-down runs out.
    run.clock = STAND_DOWN + 1
    assert gifts(run, view, Goal).key == key


def test_a_set_aside_master_ball_does_not_hold_the_legends_either(monkeypatch):
    from pokesim.gen2 import celebi
    from pokesim.gen2.quests import legends
    monkeypatch.setattr(celebi, 'journey', lambda *args: None)
    run = policy('gold')
    run.returned = set()
    run.data.items = {'SILVER_WING': 1}
    view = SimpleNamespace(owned=set(), can_catch=True, items=(), event=lambda flag: flag == 'EVENT_RELEASED_THE_BEASTS')
    assert legends(run, view, Goal).key == 'gift_master_ball'
    set_aside(run, 'gift_master_ball', 'ELMS_LAB')
    assert legends(run, view, Goal).key == 'pewter_wing'


def test_an_item_gift_turned_away_for_a_full_pocket_sets_aside_only_that_gift():
    from pokesim.gen2.quests import trade_items
    run = policy()
    assert trade_items(run, snapshot(), Goal).map_name == 'SILPH_CO_1F'
    set_aside(run, 'collection_trade_item', 'SILPH_CO_1F')
    assert trade_items(run, snapshot(), Goal).map_name == 'SLOWPOKE_WELL_B2F'


def test_a_set_aside_stone_gift_lets_the_grandfather_go_on_and_then_sets_him_aside():
    from pokesim.gen2.quests import stones
    run = policy()
    view = snapshot(species=(108,))
    assert stones(run, view, Goal).key == 'collection_stone'
    set_aside(run, 'collection_stone', 'TOHJO_FALLS')
    assert stones(run, view, Goal).key == 'collection_stone_show'
    set_aside(run, 'collection_stone_show', 'BILLS_HOUSE')
    assert stones(run, view, Goal) is None
