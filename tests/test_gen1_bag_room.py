"""Gen I bag room: a wanted fetch into a full bag first stores key items whose use is over in the PC."""
from pokecore.shortcuts import DepositItem
from pokesim.planning.monitor import hold_key
from pokesim.policies import kinds
from pokesim.policies.collection import Collection
from pokesim.policies.progression import LAPRAS_DEX, SPENT_KEY_ITEMS, bicycle_goal, fly_goal, spent_items
from pokesim.policies.storage import StorageController
from pokesim.policies.strategic import ROOM_GOALS, StrategicPolicy
from pokesim.replay.rung import _goal_events
from pokesim.runtime.policy import PolicyContext
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_gen1_fly import ACE, CARRIER, PARTY
from test_replay_audit_rows import _mon, _snapshot
from test_strategy import flags

TICKET, CARD_KEY, FLUTE = ITEMS['S_S_TICKET'], ITEMS['CARD_KEY'], ITEMS['POKE_FLUTE']
SPENT_IDS = {ITEMS[name] for name in SPENT_KEY_ITEMS}
FILLER = tuple((item, 1) for item in range(1, 100) if item in ITEMS.values() and item not in SPENT_IDS
               and item not in (ITEMS['BICYCLE'], ITEMS['BIKE_VOUCHER'], ITEMS['HM02'], FLUTE))
SAILED = flags('EVENT_SS_ANNE_LEFT')


def bag(*items, kinds=20):
    """``items`` as single entries, topped up with fillers to ``kinds`` entries."""
    entries = tuple((item, 1) for item in items)
    return entries + FILLER[:kinds - len(entries)]


def test_a_key_item_is_spent_only_once_nothing_reads_it_again():
    assert spent_items(snap(items=bag(TICKET))) == ()
    assert spent_items(snap(items=bag(TICKET), event_flags=SAILED)) == (TICKET,)
    # The rescued worker's Lapras waits behind a Card Key door, so the key stays until Lapras is owned.
    beaten = flags('EVENT_BEAT_SILPH_CO_GIOVANNI')
    assert spent_items(snap(items=bag(CARD_KEY), event_flags=beaten)) == ()
    assert spent_items(snap(items=bag(CARD_KEY), event_flags=beaten, owned=frozenset({1, LAPRAS_DEX}))) == (CARD_KEY,)
    # A walking return puts the Route 12 Snorlax back on the road after both are beaten, and only the
    # flute wakes it, so the flute is never stored.
    both_snorlax = flags('EVENT_BEAT_ROUTE12_SNORLAX', 'EVENT_BEAT_ROUTE16_SNORLAX')
    assert spent_items(snap(items=bag(FLUTE), event_flags=both_snorlax)) == ()
    assert bicycle_goal(snap(items=bag(ITEMS['BIKE_VOUCHER'], FLUTE), event_flags=both_snorlax)) is None
    # Table order, and an item with a use left (the Silph Scope, an HM, the Bicycle) is never in it.
    both = flags('EVENT_SS_ANNE_LEFT', 'EVENT_BEAT_SILPH_CO_GIOVANNI')
    owned = frozenset({1, LAPRAS_DEX})
    assert spent_items(snap(items=bag(CARD_KEY, TICKET), event_flags=both, owned=owned)) == (TICKET, CARD_KEY)
    assert not {'SILPH_SCOPE', 'HM01', 'BICYCLE', 'COIN_CASE', 'DOME_FOSSIL', 'OLD_AMBER'} & set(SPENT_KEY_ITEMS)


def test_hm02_into_a_full_bag_waits_on_a_visit_that_stores_a_spent_key_item():
    full = snap(party=PARTY, items=bag(TICKET), event_flags=SAILED)
    goal = fly_goal(full)
    assert goal.key == 'bag_room' and goal.interact and goal.targets
    assert fly_goal(full, room=False) is None
    # Nothing spent to store, so HM02 waits as before, and a free entry fetches it.
    assert fly_goal(snap(party=PARTY, items=bag(TICKET))) is None
    assert fly_goal(snap(party=PARTY, items=bag(TICKET, kinds=19), event_flags=SAILED)).key == 'fly'
    assert fly_goal(snap(party=(ACE, CARRIER), items=bag(ITEMS['HM02']))).key == 'teach_fly'


def test_the_bicycle_and_its_voucher_make_as_many_entries_as_they_need():
    voucher = ITEMS['BIKE_VOUCHER']
    assert bicycle_goal(snap(items=bag(voucher, TICKET), event_flags=SAILED)).key == 'bag_room'
    assert bicycle_goal(snap(items=bag(voucher, TICKET), event_flags=SAILED), room=False) is None
    # The voucher wants two entries. One spent item makes the second of them, never the first.
    assert bicycle_goal(snap(items=bag(TICKET, kinds=19), event_flags=SAILED)).key == 'bag_room'
    assert bicycle_goal(snap(items=bag(TICKET), event_flags=SAILED)) is None
    assert bicycle_goal(snap(items=bag(TICKET, kinds=18), event_flags=SAILED)).key == 'bike_voucher'


def test_a_gift_into_a_full_bag_waits_on_a_visit_that_stores_a_spent_key_item():
    # A Red run after the League walked to each Fishing Guru with a full bag and was turned away.
    projects = {'collect_rod': {'method': 'rod', 'item': 'GOOD_ROD', 'map': 140, 'room': 'FUCHSIA_GOOD_ROD_HOUSE'},
                'collect_amber': {'method': 'amber', 'item': 'OLD_AMBER', 'map': 104},
                'collect_coins': {'method': 'prize', 'species': 137, 'map': 0},
                'collect_pickup': {'method': 'return_fossil', 'map': 166, 'item': 'OLD_AMBER', 'event_return': 'fossil'}}
    for key, project in projects.items():
        collection = Collection()
        goal = lambda s: kinds.rules(project['method']).step(kinds.View(collection, s), project)
        assert goal(snap(party=PARTY, items=bag(TICKET), event_flags=SAILED)).key == 'bag_room'
        assert goal(snap(party=PARTY, items=bag(TICKET, kinds=19), event_flags=SAILED)).key == key
        # Nothing spent to store, so the gift waits, and so it does once a stall set the visit aside.
        assert goal(snap(party=PARTY, items=bag(TICKET))) is None
        collection.director.monitor.stand_down(hold_key('bag_room'), collection.clock)
        assert goal(snap(party=PARTY, items=bag(TICKET), event_flags=SAILED)) is None


def test_the_pc_stores_the_first_spent_item_and_no_other_goal_stores_any():
    pc = StorageController()
    full = snap(items=bag(TICKET), event_flags=SAILED)
    decision = pc.step(full, None, 'pc_root', 'bag_room', None, {})
    assert decision.request == ('deposit_item', TICKET)
    assert pc.step(full, None, 'pc_root', 'collect_plan', None, {}).request is None
    assert pc.step(snap(items=bag(TICKET)), None, 'pc_root', 'bag_room', None, {}).request is None


def test_the_deposit_runs_as_the_core_shortcut():
    policy = StrategicPolicy(7)
    started = []
    policy._start_shortcut = lambda s, machine, key, purpose: started.append((machine, key)) or ['a']
    assert policy._request(snap(), ('deposit_item', TICKET), 'Make room') == ['a']
    (machine, key), = started
    assert isinstance(machine, DepositItem) and machine.item == TICKET and key == ('deposit_item', TICKET)


def test_a_run_past_the_league_makes_room_for_hm02_and_a_stall_sets_the_visit_aside():
    assert 'bag_room' in ROOM_GOALS
    policy = StrategicPolicy(7)
    policy.collection.completed_champion = True
    policy.nav.guided = lambda *args, **kwargs: 'up'
    full = bag(ITEMS['BICYCLE'], TICKET)
    for frame in (0, 60):
        policy.step(PolicyContext(snap(frame=frame, party=PARTY, items=full, event_flags=SAILED), frame, bytearray(65536)))
    assert policy.goal.key == 'bag_room'
    policy._room_parked = lambda key: key == 'bag_room'
    policy.step(PolicyContext(snap(frame=120, party=PARTY, items=full, event_flags=SAILED), 120, bytearray(65536)))
    assert policy.goal.key != 'bag_room'


def test_a_visit_that_stores_a_spent_item_is_support_in_the_rung_audit():
    full, stored = _snapshot([_mon('Pikachu')], []), _snapshot([_mon('Pikachu')], [])
    full.items = tuple((item, 1) for item in range(20))
    stored.items = full.items[1:]
    assert [(event.kind, event.detail) for event in _goal_events('bag_room', full, stored)] == [('sold', 1)]
    assert _goal_events('bag_room', full, full) == []
