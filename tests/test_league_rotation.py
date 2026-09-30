from dataclasses import asdict, replace
import json

from pokesim.policies.collection import Collection
from pokesim.policies.league_rotation import select_reserve, deposit_target
from pokesim.policies.storage import StorageController
from pokesim.ram import StoredMon
from pokesim.strategy_data import MAPS
from pokesim.trade.preferences import identity
from test_events import snap
from test_strategy import mon


def partner(index, **changes):
    return mon(species=131, level=80, nick=f'TEAM{index}', trainer_id=index,
               dvs=(15, 15, 15, 15, 15), stat_exp=(50000,) * 5, moves=(33,), pp=(35,), **changes)


def fixture():
    party = tuple(partner(i) for i in range(6))
    reserve = StoredMon(2, 0, 131, 80, 'RESERVE', (33,), 512000,
                        (15,) * 5, (50000,) * 5, 99)
    return with_storage(snap(party=party, hall_of_fame_count=2), [reserve])


def with_storage(s, entries):
    return replace(s, stored_details=tuple(entries),
                   stored_pokemon=tuple((m.box, m.species, m.level, m.nick) for m in entries))


def test_rematch_selects_distinct_reserve_and_uses_normal_pc_menus():
    s = fixture()
    c = Collection()
    c.completed_champion = True
    c.project = {'method': 'rematch', 'hof_count': 2}
    c.prepare_league_rotation(s)
    assert c.goal(s).key == 'party_league'
    assert c.project['box'] == 2
    pc = StorageController(operation='deposit')
    outgoing = pc.target(s, 'party_league', c.project, {}, c)
    assert outgoing is not None and outgoing != 0
    five = replace(s, party=tuple(p for i, p in enumerate(s.party) if i != outgoing))
    pc.operation = 'withdraw'
    assert pc.target(five, 'party_league', c.project, {}, c) is None
    opened = replace(five, active_box=2, boxed_pokemon=((131, 80),))
    assert pc.target(opened, 'party_league', c.project, {}, c) == 0
    incoming = partner(99)
    incoming = replace(incoming, nick='RESERVE')
    ready = with_storage(replace(opened, party=opened.party + (incoming,)), [])
    assert c.goal(ready).key == 'collect_rematch'
    assert c.project['rotation_ready']
    counts = c.league_appearances.copy()
    c.goal(ready)
    assert c.league_appearances == counts
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    assert restored.league_appearances == counts
    assert restored.goal(ready).key == 'collect_rematch'


def test_rotation_respects_field_moves_strongest_and_trade_reservations():
    s = fixture()
    s = replace(s, party=(replace(s.party[0], level=100),
                          replace(s.party[1], moves=(57, 33)),
                          replace(s.party[2], moves=(70, 33)), *s.party[3:]))
    preferences = {identity(asdict(s.party[3])): {'state': 'locked'},
                   identity(asdict(s.party[4])): {'state': 'offered'}}
    assert deposit_target(s, preferences, {}) == 5
    key = identity(s.storage_entries()[0])
    assert select_reserve(s, {key: {'state': 'offered'}}, {}) is None
    assert select_reserve(s, {key: {'state': 'locked'}}, {}) is None


def test_rotation_skips_weak_unknown_and_ambiguous_reserves():
    s = fixture()
    reserve = s.stored_details[0]
    assert select_reserve(with_storage(s, [replace(reserve, level=49)]), {}, {}) is None
    assert select_reserve(with_storage(s, [replace(reserve, dvs=())]), {}, {}) is None
    assert select_reserve(with_storage(s, [reserve, replace(reserve, box=3)]), {}, {}) is None
    assert select_reserve(with_storage(s, [replace(reserve, moves=(45,))]), {}, {}) is None


def test_less_used_reserve_wins_and_missing_target_does_not_block_rematch():
    s = fixture()
    second = replace(s.stored_details[0], box=3, trainer_id=100, nick='SECOND')
    s = with_storage(s, [*s.stored_details, second])
    used = {identity(s.storage_entries()[0]): 3}
    assert select_reserve(s, {}, used)['nick'] == 'SECOND'
    c = Collection()
    c.project = {'method': 'rematch', 'hof_count': 2}
    c.prepare_league_rotation(s)
    assert c.goal(with_storage(s, [])).key == 'collect_rematch'
    assert c.project['rotation_ready']


def test_no_rotation_inside_league_or_when_all_storage_is_full():
    s = fixture()
    c = Collection()
    c.project = {'method': 'rematch', 'hof_count': 2}
    full = replace(s, boxed_pokemon=((131, 80),) * 20, box_counts=(20,) * 12)
    c.prepare_league_rotation(full)
    assert not c.project.get('league_rotation')
    c.prepare_league_rotation(s)
    assert c.goal(replace(s, map=MAPS['LORELEIS_ROOM'])).key != 'party_league'
