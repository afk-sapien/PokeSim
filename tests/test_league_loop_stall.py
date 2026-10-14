"""A champion with no money must still reach the League, and a full party of keepers must not wait at a PC."""
from pokesim.policies.collection import Collection
from pokesim.policies.team import reserve_to_deposit
from pokesim.strategy_data import MAPS
from test_collection import sid, state
from test_strategy import mon

CAVE = MAPS['DIGLETTS_CAVE']


def rematch():
    c = Collection()
    c.project = {'method': 'rematch', 'hof_count': 250, 'key': '0:rematch:0:'}
    c.remaining = 300000
    c.project_maps = [CAVE]
    return c


def test_wild_battles_on_the_way_to_a_rematch_do_not_use_up_its_idle_budget():
    # Diglett's Cave without Repels: about 300 frames of walking, then a 1,400 frame wild battle.
    c = rematch()
    frame = 0
    for _ in range(12):
        for battle in (0,) * 3 + (1,) * 12:
            frame += 120
            c.observe(state(frame=frame, map=CAVE, in_battle=battle, hall_of_fame_count=250))
    assert c.project is not None
    assert c.idle_frames < 7200


def test_a_rematch_that_only_walks_is_still_given_up_after_two_minutes():
    c = rematch()
    for frame in range(0, 7500, 120):
        c.observe(state(frame=frame, map=CAVE, hall_of_fame_count=250))
    assert c.project is None
    assert 'No encounter' in c.history[-1]


def test_a_gift_is_not_offered_when_no_party_member_may_be_deposited():
    # The strongest battler plus one sole holder of each field move: nothing can go to the PC.
    party = (mon(level=100, moves=(52, 0, 0, 0)),) + tuple(
        mon(level=55, moves=(move, 0, 0, 0)) for move in (15, 19, 57, 70, 148))
    s = state(party=party, map=MAPS['CERULEAN_CITY'], box_counts=(19,) + (20,) * 11)
    assert reserve_to_deposit(s) is None
    c = Collection()
    assert c.goal(s, {'method': 'gift', 'species': sid(106), 'map': MAPS['FIGHTING_DOJO']}) is None


def test_a_gift_still_asks_for_room_when_a_reserve_can_be_deposited():
    party = (mon(level=100),) + tuple(mon(level=55, moves=(move, 0, 0, 0)) for move in (15, 19, 57, 70)) + (mon(level=30),)
    s = state(party=party, map=MAPS['CERULEAN_CITY'], box_counts=(19,) + (20,) * 11)
    goal = Collection().goal(s, {'method': 'gift', 'species': sid(106), 'map': MAPS['FIGHTING_DOJO']})
    assert goal is not None and goal.key == 'party_collection_space'
