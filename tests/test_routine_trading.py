"""Trusted trading must create benefits without spending protected partners."""
from dataclasses import replace
from pokesim.broker import routine
from test_broker import inv, MAGIKARP, ZUBAT, SANDSHREW, KADABRA, DEX_TO_SPECIES


def test_exclusives_do_not_require_a_level_90_payment():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {SANDSHREW}, stored=[(SANDSHREW, 6), (SANDSHREW, 8)])
    deal, = routine.proposals([red, blue])
    assert deal['spends'] == {'give': 'spare', 'take': 'spare'}
    assert deal['give']['level'] == 5 and deal['take']['level'] == 6


def test_trade_evolution_is_a_benefit_even_when_both_own_the_pre_evolution():
    red = inv('red', {KADABRA}, stored=[(KADABRA, 20), (KADABRA, 25)])
    blue = replace(red, instance='blue', spares=tuple(replace(p, instance='blue') for p in red.spares))
    deal, = routine.proposals([red, blue])
    assert 'Alakazam' in deal['reason']


def test_last_copies_and_best_copies_are_never_spent():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5)])
    blue = inv('blue', {ZUBAT}, stored=[(ZUBAT, 8), (ZUBAT, 9)])
    assert routine.proposals([red, blue]) == []
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 15)])
    deal, = routine.proposals([red, blue])
    assert deal['give']['level'] == 5 and deal['take']['level'] == 8


def test_hunting_partners_and_party_members_are_protected():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 15)], hunting=DEX_TO_SPECIES[MAGIKARP])
    blue = inv('blue', {ZUBAT}, party=[(ZUBAT, 8), (ZUBAT, 9)])
    assert routine.proposals([red, blue]) == []


def test_no_pointless_swaps_or_small_level_churn():
    red = inv('red', {MAGIKARP, ZUBAT}, stored=[(MAGIKARP, 5), (MAGIKARP, 9), (ZUBAT, 9)])
    blue = inv('blue', {MAGIKARP, ZUBAT}, stored=[(ZUBAT, 6), (ZUBAT, 8), (MAGIKARP, 9)])
    assert routine.proposals([red, blue]) == []


def test_quality_upgrades_remain_useful_after_dex_registration():
    red = inv('red', {MAGIKARP, ZUBAT}, stored=[(MAGIKARP, 5), (MAGIKARP, 9), (ZUBAT, 9)])
    blue = inv('blue', {MAGIKARP, ZUBAT}, stored=[(ZUBAT, 20), (ZUBAT, 25), (MAGIKARP, 9)])
    deal, = routine.proposals([red, blue])
    assert 'five levels stronger' in deal['reason']


def test_dv_upgrade_requires_known_totals_and_a_comparable_level():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 20)])
    red = replace(red, stored=tuple(replace(p, dvs=(5, 5, 5, 5, 5)) for p in red.stored))
    incoming = replace(red.stored[0], dvs=(6, 6, 6, 6, 6))
    assert routine.benefit(red, incoming)[0] == 5
    assert routine.benefit(red, replace(incoming, level=10))[0] == 0
    assert routine.benefit(replace(red, stored=tuple(replace(p, dvs=()) for p in red.stored)), incoming)[0] == 0


def test_last_copy_can_unlock_a_new_entry_when_enabled():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5)])
    blue = inv('blue', {ZUBAT}, stored=[(ZUBAT, 8)])
    deal, = routine.proposals([red, blue], allow_last_copies=True)
    assert deal['spends'] == {'give': 'last one', 'take': 'last one'}
    assert 'registers' in deal['reason']
    red_after = inv('red', {MAGIKARP, ZUBAT}, stored=[(ZUBAT, 8)])
    blue_after = inv('blue', {MAGIKARP, ZUBAT}, stored=[(MAGIKARP, 5)])
    assert routine.proposals([red_after, blue_after], allow_last_copies=True) == []


def test_last_copy_mode_keeps_party_projects_and_best_of_multiple_copies():
    blue = inv('blue', {ZUBAT}, stored=[(ZUBAT, 8)])
    red = inv('red', {MAGIKARP}, party=[(MAGIKARP, 5)])
    assert routine.proposals([red, blue], allow_last_copies=True) == []
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5)], hunting=DEX_TO_SPECIES[MAGIKARP])
    assert routine.proposals([red, blue], allow_last_copies=True) == []
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 15)])
    deal, = routine.proposals([red, blue], allow_last_copies=True)
    assert deal['give']['level'] == 5
    assert deal['spends']['give'] == 'spare'


def test_last_copy_cannot_be_spent_for_a_quality_upgrade_alone():
    red = inv('red', {MAGIKARP, ZUBAT}, stored=[(MAGIKARP, 40), (ZUBAT, 5)])
    blue = inv('blue', {MAGIKARP, ZUBAT}, stored=[(ZUBAT, 40), (MAGIKARP, 5)])
    assert routine.proposals([red, blue], allow_last_copies=True) == []


def test_board_explains_last_copy_sharing_and_event_gifts():
    from pokesim.broker.app import render_board
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5)])
    blue = inv('blue', {ZUBAT}, stored=[(ZUBAT, 8)])
    deals = routine.proposals([red, blue], allow_last_copies=True)
    page = render_board([red, blue], deals, 90, {
        'enabled': True, 'allow_last_copies': True,
        'events': [{'gifts': [{'instance': 'red'}]}],
    })
    assert 'LAST ONE' in page
    assert 'A last boxed copy may travel' in page
    assert 'Red received Mew (Lv. 5)' in page
