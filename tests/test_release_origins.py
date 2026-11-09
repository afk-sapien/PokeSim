"""Where a Pokémon came from adds to its PC value: a stranger's trade, a gift and a legendary go after
the player's own copies and copies from linked adventures, but none of them is kept by origin alone.

Linked adventures are learned two ways: the original trainer of each Pokémon that arrives in a completed
exchange, and the trainer ids the coordinator passes with its collection requests.
"""
from dataclasses import replace

import pytest

from pokesim.pcvalue import queue
from pokesim.policies.collection import gift_species
from pokesim.policies.team import SPECIES, release_rated, release_target
from pokesim.ram import StoredMon
from pokesim.runtime.participant import Participant, _promote, merge_partners
from pokesim.store import Store
from pokesim.trade import partners
from test_events import snap
from test_preparation import participant  # noqa: F401  (fixture)

PLAYER, SILVER, STRANGER = 47325, 13132, 20897
BY_DEX = {row['dex']: sid for sid, row in SPECIES.items()}


def stored(position, species=16, **changes):
    return replace(StoredMon(0, position, BY_DEX[species], 20, '', (33, 45, 0, 0), 8000, (8,) * 5, (0,) * 5,
                             trainer_id=PLAYER), **changes)


def snapshot(copies, player=PLAYER, active=0, **changes):
    return snap(stored_details=tuple(copies), stored_pokemon=tuple((p.box, p.species, p.level, p.nick) for p in copies),
                player_id=player, active_box=active, **changes)


# Nine free slots, so a refill to BOX_REFILL frees one.
ONE_NEEDED = {'box_counts': (20,) * 11 + (11,)}


def best_and(*others, species=16):
    return [stored(0, species, level=60, dvs=(14,) * 5), *others]


def order(s, **inputs):
    """Stored slots in release order."""
    return [row.entry.slot for row in queue(release_rated(s, **inputs))]


def test_the_player_and_partner_copies_go_before_a_strangers():
    # DVs with HP 0, rarer as the other four rise.
    own = stored(1, dvs=(0, 6, 6, 6, 6))
    partner = stored(2, dvs=(0, 4, 4, 4, 4), trainer_id=SILVER)
    stranger = stored(3, dvs=(0, 2, 2, 2, 2), trainer_id=STRANGER)
    s = snapshot(best_and(own, partner, stranger))
    assert order(s, partners=frozenset({SILVER})) == [(0, 2), (0, 1), (0, 3)]
    assert order(s) == [(0, 1), (0, 3), (0, 2)]
    assert release_target(snapshot(best_and(own, partner, stranger), **ONE_NEEDED), partners=frozenset({SILVER})) == (0, 2)
    # A stranger's copy is only worth more. It still goes when it is the only spare.
    assert release_target(snapshot(best_and(stranger))) == (0, 3)


def test_an_unknown_player_leaves_the_trainer_out_of_the_rules():
    stranger = stored(1, dvs=(1,) * 5, trainer_id=STRANGER)
    assert release_target(snapshot(best_and(stranger), player=None)) == (0, 1)


@pytest.mark.parametrize('dex', [144, 145, 146, 150, 151])
def test_a_legendary_copy_goes_after_every_plain_spare(dex):
    copies = [stored(position, dex, dvs=(0,) + (2 * position + 2,) * 4) for position in range(3)]
    pidgey = [stored(3, dvs=(0, 4, 4, 4, 4)), stored(4, dvs=(15,) * 5)]
    s = snapshot(copies + pidgey)
    assert order(s) == [(0, 3), (0, 0), (0, 1)]
    assert ('Legendary', 200) in next(row for row in release_rated(s) if row.entry.slot == (0, 0)).parts


def test_the_players_own_gift_copy_goes_after_a_partners():
    eevee = BY_DEX[133]
    own = stored(1, 133, dvs=(3,) * 5)
    partner = stored(2, 133, dvs=(2,) * 5, trainer_id=SILVER)
    s = snapshot(best_and(own, partner, species=133))
    assert order(s, partners=frozenset({SILVER}), gifts=frozenset({eevee})) == [(0, 2), (0, 1)]
    assert order(s, partners=frozenset({SILVER})) == [(0, 2), (0, 1)]
    rows = {row.entry.slot: row for row in release_rated(s, partners=frozenset({SILVER}), gifts=frozenset({eevee}))}
    assert ('Gift', 80) in rows[0, 1].parts and ('Gift', 80) not in rows[0, 2].parts


def test_gift_and_fossil_species_count_with_their_evolutions():
    gifts = gift_species('red')
    # Eevee and its evolutions, Lapras, the Hitmons and the fossils, but no legendary or wild species.
    for dex in (133, 134, 135, 136, 131, 106, 107, 138, 139, 140, 141, 142):
        assert BY_DEX[dex] in gifts, dex
    for dex in (16, 144, 150, 143):
        assert BY_DEX[dex] not in gifts, dex


def test_the_open_box_goes_first():
    best = stored(0, dvs=(14,) * 5)
    weak = stored(1, dvs=(1,) * 5)
    here = stored(0, dvs=(5,) * 5, box=3)
    assert release_target(snapshot([best, weak, here], active=3)) == (3, 0)
    assert release_target(snapshot([best, weak, here], active=0)) == (0, 1)


def test_shiny_and_rare_dv_copies_go_after_a_plain_spare():
    shiny = stored(1, dvs=(0, 2, 10, 10, 10))
    rare = stored(2, dvs=(13, 15, 15, 14, 15))
    perfect = stored(0, level=60, dvs=(15,) * 5)
    # The shiny is the best copy by value and the perfect one the rarest, so both stay.
    assert order(snapshot([perfect, shiny, rare])) == [(0, 2)]
    assert order(snapshot([perfect, shiny, rare, stored(3)])) == [(0, 3), (0, 2)]


def test_the_received_trainer_id_comes_from_the_struct_in_both_generations():
    gen1 = bytearray(33)
    gen1[12:14] = SILVER.to_bytes(2, 'big')
    gen2 = bytearray(32)
    gen2[6:8] = SILVER.to_bytes(2, 'big')
    assert partners.received(bytes(gen1).hex()) == SILVER
    assert partners.received(bytes(gen2), 2) == SILVER
    assert partners.received('zz') is None and partners.received(b'\x00') is None
    assert partners.owners(PLAYER, frozenset({SILVER})) == {PLAYER, SILVER}
    assert partners.owners(None, frozenset({SILVER})) is None


def committed(store, trainers):
    from test_managed_participant import committed as base
    record = base(store)
    record['incoming_trainers'] = trainers
    return record


def test_an_id_recorded_at_trade_time_is_kept_and_read_back(tmp_path):
    store = Store(tmp_path)
    try:
        assert store.trade_partners() == frozenset()
        _promote(store, committed(store, [SILVER, None]))
        assert store.trade_partners() == {SILVER}
    finally:
        store.close()
    store = Store(tmp_path)
    try:
        assert store.trade_partners() == {SILVER}
    finally:
        store.close()


def test_the_coordinators_partner_ids_are_merged_and_kept(tmp_path):
    store = Store(tmp_path)
    try:
        merge_partners(store, {'partners': [SILVER]})
        merge_partners(store, {'partners': [7726]})
        merge_partners(store, {})
        assert store.trade_partners() == {SILVER, 7726}
        for bad in ([-1], [0x10000], [True], ['13132'], 'x', list(range(partners.LIMIT + 1))):
            with pytest.raises(ValueError):
                merge_partners(store, {'partners': bad})
        assert store.trade_partners() == {SILVER, 7726}
    finally:
        store.close()


def test_gen1_collection_requests_merge_the_partner_ids(tmp_path):
    from types import SimpleNamespace
    from pokesim.policies.collection import Collection
    store = Store(tmp_path)
    try:
        participant = object.__new__(Participant)
        participant.emu = SimpleNamespace(policy=SimpleNamespace(collection=Collection()))
        participant.store = store
        participant.collection_demand({'requests': {}, 'partners': [SILVER]})
        assert store.trade_partners() == {SILVER}
    finally:
        store.close()


def test_gen2_collection_requests_merge_the_partner_ids(tmp_path):
    from types import SimpleNamespace
    from pokesim.gen2.trading import Participant as Gen2Participant
    store = Store(tmp_path)
    try:
        participant = Gen2Participant.__new__(Gen2Participant)
        participant.emu = SimpleNamespace(policy=SimpleNamespace())
        participant.store = store
        participant.collection_demand({'requests': {}, 'partners': [PLAYER]})
        assert store.trade_partners() == {PLAYER}
    finally:
        store.close()


def test_the_inventory_publishes_the_players_trainer_id(participant):  # noqa: F811
    from test_managed_trade_evolutions import runtime_inventory
    emu, snap, _ = participant
    emu.snapshot = snap = replace(snap, player_id=PLAYER)
    assert runtime_inventory(emu, snap)['player_id'] == PLAYER


def test_the_strategic_policy_passes_the_stored_partners_to_the_release():
    from pokesim.policies.strategic import StrategicPolicy
    policy = StrategicPolicy(7)
    partner = stored(1, dvs=(2,) * 5, trainer_id=SILVER)
    s = snapshot(best_and(partner, stored(2, dvs=(4,) * 5)), **ONE_NEEDED)
    assert policy._release_target(s) == (0, 2)
    policy.trade_partners = lambda: frozenset({SILVER})
    assert policy._release_target(s) == (0, 1)
