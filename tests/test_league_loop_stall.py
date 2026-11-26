"""A champion with no money must still reach the League, and a full party of keepers must not wait at a PC."""
from pokesim.policies.collection import Collection
from pokesim.policies.team import reserve_to_deposit
from pokesim.strategy_data import MAPS
from test_collection import sid, state
from test_strategy import flags, mon

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


def walk_back_after_agatha(blackout):
    """A rematch that saw Route 23, Victory Road 3F and its switch on the way to Agatha loses there, then
    walks 90 seconds of Route 23, 90 seconds of Victory Road 3F, pushes the boulder onto the switch the
    game had cleared, and walks 90 seconds more."""
    c = rematch()
    off = flags('EVENT_GOT_POKEDEX')
    on = flags('EVENT_GOT_POKEDEX', 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH1')
    c.project_maps = [CAVE, MAPS['ROUTE_23'], MAPS['VICTORY_ROAD_3F'], MAPS['AGATHAS_ROOM']]
    c.project_flags = list(on)
    frame = 0
    if blackout:
        for frame in range(120, 600, 120):
            c.observe(state(frame=frame, map=MAPS['AGATHAS_ROOM'], in_battle=2, hall_of_fame_count=250,
                            event_flags=off, party=(mon(hp=0, max_hp=100, level=40),)))
    for place, now in (('ROUTE_23', off), ('VICTORY_ROAD_3F', off), ('VICTORY_ROAD_3F', on)):
        for _ in range(45):
            frame += 120
            c.observe(state(frame=frame, map=MAPS[place], event_flags=now, hall_of_fame_count=250))
    return c


def test_after_a_blackout_the_walk_back_is_a_new_route_with_new_switches():
    c = walk_back_after_agatha(blackout=True)
    assert c.project is not None
    # The count started again at the switch.
    assert c.idle_frames <= 45 * 120


def test_without_a_blackout_seen_maps_and_switches_are_not_a_new_route():
    c = walk_back_after_agatha(blackout=False)
    assert c.project is None
    assert 'No encounter' in c.history[-1]


def test_a_gift_is_not_offered_when_no_party_member_may_be_deposited(monkeypatch):
    # The strongest battler, one sole holder of each field move and Yellow's starter Pikachu:
    # nothing can go to the PC.
    from pokesim.policies import team
    monkeypatch.setattr(team, 'STAYS_IN_PARTY', {sid(25)})
    party = (mon(level=100, moves=(52, 0, 0, 0)),) + tuple(
        mon(level=55, moves=(move, 0, 0, 0)) for move in (15, 19, 57, 70)) + (
        mon(level=55, species=sid(25), moves=(84, 0, 0, 0)),)
    s = state(party=party, map=MAPS['CERULEAN_CITY'], box_counts=(19,) + (20,) * 11)
    assert reserve_to_deposit(s) is None
    c = Collection()
    assert c.goal(s, {'method': 'gift', 'species': sid(106), 'map': MAPS['FIGHTING_DOJO']}) is None


def test_a_gift_still_asks_for_room_when_a_reserve_can_be_deposited():
    party = (mon(level=100),) + tuple(mon(level=55, moves=(move, 0, 0, 0)) for move in (15, 19, 57, 70)) + (mon(level=30),)
    s = state(party=party, map=MAPS['CERULEAN_CITY'], box_counts=(19,) + (20,) * 11)
    goal = Collection().goal(s, {'method': 'gift', 'species': sid(106), 'map': MAPS['FIGHTING_DOJO']})
    assert goal is not None and goal.key == 'party_collection_space'
