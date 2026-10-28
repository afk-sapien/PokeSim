"""Collection sources declare what they need, and the precondition check keeps the candidates it kept before."""
import itertools
from types import SimpleNamespace

from pokesim.planning.conditions import Can, Count, feasible
from pokesim.policies.collection import HUNT_BALLS, REPEATABLE, CollectionWorld, source_requires
from pokesim.policies.ledger import ledger
from pokesim.planning.ledger import MONEY
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_strategy import mon

BOX = 20


def former_candidate(s, source, owned, can_surf):
    """The checks choose() made by hand before sources declared their requirements."""
    bag = dict(s.items)
    mode = source['method']
    if mode in ('grass', 'surf', 'fish', 'safari', 'static') and (
            not s.can_catch or not any(bag.get(ITEMS[n]) for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL', 'MASTER_BALL'))):
        return False
    if mode == 'surf' and not can_surf:
        return False
    if mode == 'fish' and not bag.get(ITEMS[source['rod']]):
        return False
    if mode == 'safari' and s.money < 800:
        return False
    if mode in ('gift', 'fossil') and len(s.party) >= 6 and not (len(s.party) < 6 or not s.box_full
                                                                 or s.next_free_box is not None):
        return False
    if mode in REPEATABLE and owned:
        normal = sum(bag.get(ITEMS[n], 0) for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL'))
        if mode != 'safari' and normal < 5:
            return False
    return True


def candidate(s, source, owned, can_surf):
    books = ledger()
    books.snapshot(s, kinds=(MONEY,))
    return bool(feasible(source_requires(source, owned), CollectionWorld(s, SimpleNamespace(can_surf=can_surf)),
                         books, key='collection'))


def test_sources_are_candidates_exactly_when_the_former_checks_passed():
    sources = [dict(method=mode, rod='GOOD_ROD') for mode in ('grass', 'surf', 'fish', 'safari', 'static', 'gift',
                                                             'fossil', 'trade', 'evolve')]
    bags = [(), ((ITEMS['MASTER_BALL'], 1),), ((ITEMS['POKE_BALL'], 4),), ((ITEMS['POKE_BALL'], 3), (ITEMS['ULTRA_BALL'], 2)),
            ((ITEMS['GREAT_BALL'], 0), (ITEMS['GOOD_ROD'], 1)), ((ITEMS['GREAT_BALL'], 9), (ITEMS['OLD_ROD'], 1))]
    rooms = [dict(party=(mon(),)),
             dict(party=(mon(),) * 6),
             dict(party=(mon(),) * 6, boxed_pokemon=((1, 5),) * BOX, box_counts=(BOX, 3)),
             dict(party=(mon(),) * 6, boxed_pokemon=((1, 5),) * BOX, box_counts=(BOX,) * 12)]
    for source, items, room, money, owned, surf in itertools.product(sources, bags, rooms, (799, 800), (False, True),
                                                                     (False, True)):
        s = snap(items=items, money=money, **room)
        assert candidate(s, source, owned, surf) == former_candidate(s, source, owned, surf), (source, items, room, money)


def test_a_missing_condition_is_named_in_the_answer():
    s = snap(items=((ITEMS['POKE_BALL'], 2),), money=500)
    answer = feasible(source_requires(dict(method='grass'), True), CollectionWorld(s, SimpleNamespace(can_surf=False)))
    assert answer.missing == (HUNT_BALLS,)
    books = ledger()
    books.snapshot(s, kinds=(MONEY,))
    safari = feasible(source_requires(dict(method='safari'), False), CollectionWorld(s, None), books, key='collection')
    assert not safari.missing and safari.shortfall.missing == {MONEY: 300}
    full = snap(party=(mon(),) * 6, boxed_pokemon=((1, 5),) * BOX, items=((ITEMS['POKE_BALL'], 9),))
    answer = feasible(source_requires(dict(method='static'), False), CollectionWorld(full, None))
    assert answer.missing == (Can('catch'),)
    assert Count((ITEMS['POKE_BALL'], ITEMS['ULTRA_BALL']), 5).holds(CollectionWorld(snap(
        items=((ITEMS['POKE_BALL'], 3), (ITEMS['ULTRA_BALL'], 2))), None))
