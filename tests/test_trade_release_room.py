"""A trade never fails for a full PC while a safe spare duplicate can be released to make room.

Regression: a hand-picked trade between Red and Gold failed with "An adventure needs a free PC slot
to prepare its Pokémon for this trade". Gold held six in the party and 280 in the PC: 54 eggs, which
the cartridge refuses to release, one copy of nearly every species and five Snorlax holding Leftovers.
Releasing never let a held item go, so nothing was spare and Gen II preparation gave up.
"""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import trading
from pokesim.gen2.menus import ChangeBox, Release
from pokesim.gen2.preparation import FULL, Preparation
from pokesim.gen2.release import spares
from pokesim.runtime.participant import keeps
from pokesim.trade.preferences import identity

SNORLAX, SNEASEL = 143, 215


def mon(species, *, box=0, position=0, dvs=(8, 8, 8, 8, 8), trainer_id=4321, **extra):
    fields = dict(species=species, egg=False, box=box, position=position, trainer_id=trainer_id, dvs=dvs, level=50,
                  held_item=0, experience=8000, stat_exp=(0,) * 5, nick='SNORLAX', moves=(33, 0, 0, 0))
    fields.update(extra)
    return SimpleNamespace(**fields)


def full(stored, party=None, active_box=0):
    party = party if party is not None else tuple(mon(9, box=None, position=None, trainer_id=slot, nick='TOTODILE')
                                                   for slot in range(6))
    return SimpleNamespace(party=tuple(party), stored=tuple(stored), active_box=active_box, box_counts=(20,) * 14,
                           frame=100)


def gold_like():
    """The live Gold PC in miniature: eggs, single copies and boxed Snorlax holding Leftovers."""
    lead = mon(SNORLAX, box=None, position=None, held_item=146, dvs=(12, 12, 12, 12, 12))
    boxed = [mon(SNORLAX, box=box, position=position, held_item=146, dvs=dvs)
             for box, position, dvs in ((4, 3, (9, 9, 9, 9, 9)), (11, 1, (5, 6, 7, 8, 6)), (13, 5, (14, 13, 13, 13, 13)))]
    eggs = [mon(SNEASEL, box=0, position=position, egg=True, level=5) for position in range(3)]
    single = mon(1, box=2, position=0)
    return full([*eggs, single, *boxed], party=[lead, *(mon(9, box=None, position=None, trainer_id=slot) for slot in range(5))])


def test_a_trade_may_release_a_spare_holding_an_item_but_never_an_egg_or_a_last_copy():
    snapshot = gold_like()
    assert spares(snapshot) == []
    order = spares(snapshot, lenient=True)
    # The weakest boxed Snorlax goes first. The lead and best copies, the eggs and the single Bulbasaur stay.
    assert [(m.box, m.position) for m in order] == [(11, 1), (4, 3), (13, 5)]
    plain = mon(SNORLAX, box=6, position=0, dvs=(13, 13, 13, 13, 13))
    trained = mon(SNORLAX, box=6, position=1, dvs=(2, 2, 2, 2, 2), stat_exp=(30000,) * 5)
    roomy = full([*snapshot.stored, plain, trained], party=snapshot.party)
    # A copy without an item or training still goes before one with either.
    assert spares(roomy, lenient=True)[0] is plain
    assert spares(roomy)[0] is plain


def test_a_lenient_release_still_keeps_shiny_perfect_and_rare_copies():
    best = mon(SNORLAX, box=1, position=0, dvs=(13, 13, 13, 13, 13))
    shiny = mon(SNORLAX, box=1, position=1, dvs=(1, 10, 10, 10, 10), held_item=146)
    perfect = mon(SNORLAX, box=1, position=2, dvs=(15, 15, 15, 15, 15), held_item=146)
    egg = mon(SNORLAX, box=1, position=3, egg=True, level=5)
    # With a shiny and a perfect copy kept, the plain copy is the only spare, even with items allowed.
    assert spares(full([best, shiny, perfect, egg]), lenient=True) == [best]
    assert spares(full([shiny, perfect, egg]), lenient=True) == []


@pytest.fixture(scope='module')
def gold():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'gold')


def test_trade_spare_protects_keep_hand_picked_and_wished_pokemon(gold):
    from pokesim.gen2.policy import Policy
    policy = Policy(gold, seed=1, starter='chikorita')
    snapshot = gold_like()
    weakest, middle, best = sorted(snapshot.stored[4:], key=lambda m: sum(m.dvs))
    assert policy.release_target(snapshot) is None
    assert policy.trade_spare(snapshot) is weakest
    key = lambda m: identity({'trainer_id': m.trainer_id, 'dvs': m.dvs, 'dex': m.species})  # noqa: E731
    # A Pokémon set to Keep, one hand-picked for a trade (even by an older trainer-and-DV key) and a wished species stay.
    policy.trade_preferences = lambda: {key(weakest): {'state': 'locked'}}
    assert policy.trade_spare(snapshot) is middle
    assert policy.trade_spare(snapshot, protect=[key(middle).split('-')[0]]) is best
    assert policy.trade_spare(snapshot, protect=[key(middle), key(best)]) is None
    assert policy.trade_spare(snapshot, wished=[SNORLAX]) is None


def preparation(spare=None, boxes=(20,) * 14):
    events, saved = [], {}
    policy = SimpleNamespace(trade_spare=lambda snapshot, protect, wished: spare)
    emu = SimpleNamespace(policy=policy, data=SimpleNamespace(species={SNORLAX: {'name': 'Snorlax'}}),
                          store=SimpleNamespace(set=saved.__setitem__),
                          _event=lambda event, snapshot: events.append(event))
    state = {'id': 't', 'trade_key': 'k', 'protect': ['k'], 'wished': []}
    return Preparation(emu, state), events, saved


def test_preparation_releases_one_safe_spare_when_every_box_is_full():
    spare = mon(SNORLAX, box=11, position=1, dvs=(5, 6, 7, 8, 6), level=50, nick='ZZZ')
    snapshot = full([spare], active_box=3)
    prep, events, saved = preparation(spare)
    # The spare's box opens first, then the PC releases it.
    assert prep.make_room(snapshot) == ChangeBox(11)
    snapshot.active_box = 11
    menu = prep.make_room(snapshot)
    assert menu == Release(11, 1, [SNORLAX, 4321, [5, 6, 7, 8, 6]])
    # Nothing is logged while the spare is still in its box.
    prep.announce(snapshot)
    assert events == [] and prep.released is None
    prep.released = spare
    snapshot.stored = ()
    prep.announce(snapshot)
    assert [event.title for event in events] == ['Released ZZZ (Snorlax Lv 50) to make room for a trade']
    assert saved['interaction_preparation']['released'][0]['species'] == SNORLAX


def test_preparation_with_nothing_safe_to_release_fails_with_a_clear_error():
    prep, _, _ = preparation(None)
    with pytest.raises(ValueError, match='Every PC box is full and no spare duplicate can be safely released'):
        prep.make_room(full([]))
    assert 'Every PC box is full' in FULL
    prep, _, _ = preparation(None)
    roomy = full([])
    roomy.box_counts = (20, 20, 7) + (20,) * 11
    assert prep.make_room(roomy) == ChangeBox(2)


def test_a_full_pc_with_a_safe_spare_still_offers_and_lists_its_boxed_pokemon():
    snapshot = full([mon(SNORLAX)])
    assert trading.sealed(snapshot)
    assert trading.sealed(snapshot, SimpleNamespace(trade_spare=lambda snapshot: None))
    assert not trading.sealed(snapshot, SimpleNamespace(trade_spare=lambda snapshot: mon(SNORLAX)))
    snapshot.party = snapshot.party[:5]
    assert not trading.sealed(snapshot, SimpleNamespace(trade_spare=lambda snapshot: None))


def test_prepare_requests_carry_only_well_formed_keeps():
    assert keeps({}) == {'protect': [], 'wished': []}
    assert keeps({'protect': ['abc', 7, ''], 'wished': [143, 0, 252, '1', True]}) == {'protect': ['abc'], 'wished': [143]}
