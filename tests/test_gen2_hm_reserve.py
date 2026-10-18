from types import SimpleNamespace

from pokesim.app.coordinator import Coordinator
from pokesim.gen2 import trading
from pokesim.gen2.preparation import reserves

CUT, FLY, SURF, STRENGTH, FLASH, WHIRLPOOL, WATERFALL = 15, 19, 57, 70, 148, 250, 127


def member(*moves):
    return SimpleNamespace(species=143, egg=False, moves=moves, held_item=0, level=50)


def hm_party(last):
    # The live Crystal party that failed four trades in a row: every reserve knows a field move.
    return (member(22, 51, 35, 230), member(84, 65, FLY, 156), member(51, 61, 35, CUT),
            member(173, SURF, 34, STRENGTH), member(56, WHIRLPOOL, WATERFALL, 156), last)


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
