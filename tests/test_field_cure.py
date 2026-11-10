"""A status the bag can cure is cured in the field, not walked to a Pokémon Center.

Yellow reached Route 15 with 19 bag entries and no cure, and walked to Fuchsia four times for a poison at
164 of 169 HP, about 3500 frames a trip. Any status leaves the walk no HP budget (ledger.battle_room).
"""
from dataclasses import replace

from pokesim.policies.battle import field_cure, needs_healing
from pokesim.policies.progression import story_goal
from pokesim.policies.shopping import ShoppingController
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import DATA, ITEMS, MAPS
from test_collection import state
from test_strategy import mon
from shortcut_fakes import PRESS, Recorder

POISON = 8
KEYS = tuple((item, 1) for item in (6, 5, 73, 72, 48, 69, 71, 76, 77, 75, 196, 197, 198, 199, 200))
STOCKED = ((ITEMS['ULTRA_BALL'], 15), (ITEMS['SUPER_POTION'], 3))
# Two finite TMs, which a full bag sells to make room for a story item.
FINITE_TMS = ((203, 1), (206, 1))


def poisoned(*items):
    return state(map=MAPS['ROUTE_15'], x=30, y=8, frame=1000,
                 party=(mon(hp=95, max_hp=100, level=40, status=POISON),), items=STOCKED + items)


def test_a_poison_the_bag_cures_latches_no_heal_and_is_cured_where_the_party_stands():
    s = poisoned((ITEMS['ANTIDOTE'], 1))
    assert needs_healing(s.party) and not needs_healing(s.party, s.items)
    policy = StrategicPolicy(7)
    recorder = Recorder.on(policy)
    policy.goal = story_goal(s)
    policy._update_heal_latch(s)
    assert not policy.heal_latch
    assert policy._overworld(s, bytearray(65536))[0] == PRESS
    assert (recorder.last.kind, recorder.last.item, recorder.last.target) == ('use_item', ITEMS['ANTIDOTE'], 0)


def test_a_poison_with_no_field_cure_still_latches_the_heal():
    for s in (poisoned(), poisoned((ITEMS['FULL_RESTORE'], 1)), poisoned((ITEMS['PARLYZ_HEAL'], 1))):
        policy = StrategicPolicy(7)
        policy._update_heal_latch(s)
        assert policy.heal_latch


def test_the_field_cure_is_the_cheapest_and_keeps_a_full_restore_for_the_league():
    sick = mon(status=POISON)
    bag = ((ITEMS['FULL_RESTORE'], 1), (ITEMS['FULL_HEAL'], 1), (ITEMS['ANTIDOTE'], 1))
    assert field_cure(bag, sick) == ITEMS['ANTIDOTE']
    assert field_cure(bag[:1], sick) is None
    assert field_cure(bag[:1], sick, league=True) == ITEMS['FULL_RESTORE']
    assert field_cure(bag, mon()) is None
    assert field_cure(bag, replace(sick, hp=0)) is None
    # One cure covers one Pokémon.
    two = (sick, replace(sick, level=20))
    assert needs_healing(two, ((ITEMS['ANTIDOTE'], 1),)) and not needs_healing(two, ((ITEMS['ANTIDOTE'], 2),))


def test_a_mart_with_no_antidote_sells_a_first_cure_into_a_crowded_bag():
    fuchsia = DATA['marts']['FuchsiaMart']
    shop = ShoppingController()
    crowded = poisoned(*KEYS, *FINITE_TMS)
    assert len(crowded.items) == 19
    assert shop.item_for(crowded, fuchsia, 'story', None) == ITEMS['FULL_HEAL']
    assert shop._buy_quantity(crowded, fuchsia, 'story', None, ITEMS['FULL_HEAL']) == 2
    # A Lavender bag buys its Antidote the same way.
    assert shop.item_for(crowded, DATA['marts']['LavenderMart'], 'story', None) == ITEMS['ANTIDOTE']
    # A bag that already holds a cure keeps the 18 entries rule.
    held = poisoned(*KEYS, FINITE_TMS[0], (ITEMS['PARLYZ_HEAL'], 1))
    assert shop.item_for(held, fuchsia, 'story', None) is None
    # The cure fills the bag only while a finite TM could still sell for a story item.
    locked = poisoned(*KEYS, (42, 1), (43, 1))
    assert shop.item_for(locked, fuchsia, 'story', None) is None
    assert shop.item_for(poisoned(*KEYS, (42, 1)), fuchsia, 'story', None) == ITEMS['FULL_HEAL']
    # Two Antidotes are cure enough, and a full bag takes nothing.
    stocked = poisoned((ITEMS['ANTIDOTE'], 2))
    assert shop.item_for(stocked, fuchsia, 'story', None) is None
    assert shop.item_for(poisoned(*KEYS, *FINITE_TMS, (204, 1)), fuchsia, 'story', None) is None
