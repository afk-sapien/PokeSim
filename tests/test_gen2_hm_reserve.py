import os
from types import SimpleNamespace

import pytest

from pokesim.app.coordinator import Coordinator
from pokesim.gen2 import champion_shop, menus, trading, training
from pokesim.gen2.preparation import reserves
from pokesim.planning.ledger import FIELD_MOVES, LEARN_KEPT

CUT, FLY, SURF, STRENGTH, FLASH, WHIRLPOOL, WATERFALL = 15, 19, 57, 70, 148, 250, 127


def member(*moves):
    return SimpleNamespace(species=143, egg=False, moves=moves, held_item=0, level=50)


def hm_party(last):
    # The live Crystal party that failed four trades in a row: every reserve knows a field move.
    return (member(22, 51, 35, 230), member(84, 65, FLY, 156), member(51, 61, 35, CUT),
            member(173, SURF, 34, STRENGTH), member(56, WHIRLPOOL, WATERFALL, 156), last)


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_the_protected_field_moves_are_the_seven_hms_in_every_version(version):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, version)
    hms = {'CUT', 'FLY', 'SURF', 'STRENGTH', 'FLASH', 'WHIRLPOOL', 'WATERFALL'}
    assert all('HM_' + name in data.items for name in hms)
    moves = {CUT, FLY, SURF, STRENGTH, FLASH, WHIRLPOOL, WATERFALL}
    assert {data.moves[move]['constant'] for move in moves} == hms
    assert FIELD_MOVES == moves and LEARN_KEPT == moves | {29, 249}
    # Machines, the Champion shop, level-up moves and training all read the ledger's one set.
    assert champion_shop.FIELD_MOVES is menus.FIELD_MOVES is training.FIELD_MOVES is FIELD_MOVES


def test_a_reserve_whose_field_moves_another_member_knows_can_be_deposited():
    assert reserves(hm_party(member(173, SURF, 34, 205))) == [5]


def test_a_party_of_only_field_move_users_offers_no_boxed_pokemon(tmp_path, monkeypatch):
    from pokesim.store import Store
    snapshot = SimpleNamespace(party=hm_party(member(173, FLASH, 34, 205)), stored=(), items=(), box_counts=(5,) * 14)
    assert reserves(snapshot.party) == []
    assert trading.crowded(snapshot)
    monkeypatch.setattr(trading, 'live_status', lambda *args: {'party': [], 'storage': {'pokemon': [
        {'species': 1, 'dex': 1, 'box': 1, 'position': 1, 'trainer_id': 9, 'dvs': (9,) * 5}]}})
    monkeypatch.setattr(trading, 'unlocked', lambda *args: False)
    monkeypatch.setattr(trading, 'Memory', lambda *args: None)
    store = Store(tmp_path)
    try:
        emu = SimpleNamespace(snapshot=snapshot, policy=SimpleNamespace(collection={}, in_league=lambda snap: False),
                              data=SimpleNamespace(item_names={}), paused=False, manual_mode=False,
                              pb=SimpleNamespace(memory=b''), status=lambda: {'game': {}})
        owner = trading.Participant(SimpleNamespace(store=store, emulator=emu),
                                    SimpleNamespace(adventure_id='crystal', generation=2))
        inventory = owner.inventory()
        assert inventory['offers'] == []
        assert inventory['trade_blocked'] == trading.CROWDED
    finally:
        store.close()


def test_the_gen2_reserve_failure_reads_as_a_full_party():
    row = {'plan': {'kind': 'cable_trade'},
           'error': 'The party has no safe reserve to deposit for this exchange (adventure ' + 'a' * 32 + ')'}
    assert Coordinator._generic_failure_reason(row) == (
        'An adventure could not safely make room in its party for the selected Pokémon.')
