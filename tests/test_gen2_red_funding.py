"""Red on Mt. Silver must not be retried with an empty bag and an empty purse.

Regression for a Crystal post-game stall: every loss to Red halved the money until it reached 0, the shop
could not buy the healing items it asked for, and the policy kept walking back to Mt. Silver to lose again
until the level 100 lead stopped gaining experience and the runtime reloaded saves.
"""
from types import SimpleNamespace

from pokesim.gen2 import kanto
from pokesim.gen2.policy import Goal

ITEMS = {'FULL_RESTORE': 1, 'MAX_POTION': 2, 'HYPER_POTION': 3, 'REVIVE': 4}
EVENTS_FALSE = {'EVENT_TRAINERS_IN_CERULEAN_GYM', 'EVENT_VIRIDIAN_GYM_BLUE', 'EVENT_RED_IN_MT_SILVER',
                'EVENT_WILLS_ROOM_ENTRANCE_CLOSED'}


def make(money, items, hall_of_fame_count=1, league=False, beaten=()):
    data = SimpleNamespace(items=ITEMS, maps={1: {'constant': 'SILVER_CAVE_ROOM_3'}})
    policy = SimpleNamespace(data=data, collection={}, completed={},
                             in_league=lambda snapshot: league,
                             person=lambda snapshot, key, *args: key)
    snapshot = SimpleNamespace(map=1, badges=65535, frame=100, money=money, items=items,
                               hall_of_fame_count=hall_of_fame_count,
                               event=lambda name: name not in EVENTS_FALSE or name in beaten)
    return policy, snapshot


def journey(policy, snapshot):
    return kanto.journey(policy, snapshot, SimpleNamespace(byte=lambda name: 10), Goal)


def test_broke_and_out_of_potions_funds_the_league_before_red():
    policy, snapshot = make(money=3, items=[(ITEMS['REVIVE'], 3)])
    assert journey(policy, snapshot) == 'funds_will'
    assert policy.collection['funding'] == 2


def test_funding_finishes_the_league_run_once_started():
    policy, snapshot = make(money=6000, items=[], league=True, beaten={'EVENT_BEAT_ELITE_4_WILL'})
    policy.collection['funding'] = 2
    snapshot.event = lambda name: name in {'EVENT_BEAT_ELITE_4_WILL', 'EVENT_BEAT_ELITE_4_KOGA'} or (
        name not in EVENTS_FALSE and not name.startswith('EVENT_BEAT_'))
    assert journey(policy, snapshot) == 'funds_bruno'


def test_new_hall_of_fame_entry_clears_funding_and_returns_to_red():
    policy, snapshot = make(money=17000, items=[], hall_of_fame_count=2)
    policy.collection['funding'] = 2
    assert journey(policy, snapshot) == 'red'
    assert 'funding' not in policy.collection


def test_stocked_bag_or_purse_goes_straight_to_red():
    policy, snapshot = make(money=0, items=[(ITEMS['FULL_RESTORE'], 5), (ITEMS['HYPER_POTION'], 3)])
    assert journey(policy, snapshot) == 'red'
    policy, snapshot = make(money=20000, items=[])
    assert journey(policy, snapshot) == 'red'
    assert 'funding' not in policy.collection
