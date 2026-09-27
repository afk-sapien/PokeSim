"""Rarity-aware investment and protection across collection, release, and trading."""
import json
import random
from dataclasses import asdict, replace

from pokesim.broker.inventory import normalise
from pokesim.investment import assessment, training_investment
from pokesim.policies.collection import Collection
from pokesim.policies.director import AdventureDirector
from pokesim.policies.team import release_target
from pokesim.web.pokedex import live_status
from test_duplicates import stored, snapshot
from test_level100_priority import individual, postgame, candidates

RARE = (15, 15, 13, 13, 9)
POOR = (0, 8, 8, 8, 8)


def partner(level=5, dvs=RARE, **changes):
    return {'species': 0x99, 'level': level, 'dvs': dvs, 'stat_exp': (0,) * 5,
            'moves': (33,), **changes}


def test_probabilities_and_potential_do_not_change_with_training():
    small = assessment(partner())
    trained = assessment(partner(100, stat_exp=(65535,) * 5))
    assert small == trained
    assert small['dv_top_percent'] == 273 / 65536 * 100
    assert small['dv_better_percent'] == 177 / 65536 * 100
    perfect = assessment(partner(dvs=(15,) * 5))
    assert perfect['dv_top_percent'] > 0
    assert perfect['dv_better_percent'] == 0


def test_invalid_dvs_do_not_claim_rarity():
    for dvs in (None, (), (8,) * 5, (0, 15, 15, 15, 15), (True,) * 5):
        assert assessment(partner(dvs=dvs))['dv_top_percent'] is None


def test_current_and_future_strength_survive_until_replacement_catches_up():
    newcomer = stored(0, level=5, dvs=RARE)
    veteran = stored(1, level=100, dvs=POOR, stat_exp=(65535,) * 5)
    assert release_target(snapshot([newcomer, veteran])) is None
    assert release_target(snapshot([replace(newcomer, level=100, stat_exp=(65535,) * 5), veteran])) == (0, 1)


def test_rare_find_is_not_released_even_with_a_better_copy():
    assert release_target(snapshot([stored(0, dvs=RARE), stored(1, dvs=(15,) * 5)])) is None


def test_automatic_trade_protects_rare_candidate_and_trained_veteran():
    from pokesim.broker.routine import listings
    s = snapshot([stored(0, level=5, dvs=RARE), stored(1, level=100, dvs=POOR)])
    payload = json.loads(json.dumps(live_status(s.to_dict(), None)))
    inv = normalise('red', 'http://red', payload)
    assert inv.tradeable == inv.spares == ()
    assert all(row['can_offer'] and not row['listed'] for row in listings(inv))
    payload['storage']['pokemon'][0]['trade_preference'] = 'offered'
    inv = normalise('red', 'http://red', payload)
    assert len(inv.tradeable) == 1 and inv.tradeable[0].position == 1
    payload['storage']['pokemon'][0]['trade_preference'] = 'locked'
    locked = normalise('red', 'http://red', payload)
    assert not locked.tradeable
    assert not listings(locked)[0]['can_offer']
    assert not listings(normalise('red', 'http://red', payload, protected=(0x99,)))[1]['can_offer']


def test_hunting_budget_then_training_and_no_delay_for_unavailable_species():
    poor = partner(dvs=POOR)
    for count in range(3):
        assert not training_investment(poor, [poor], hunt_available=True, searches=count)['eligible']
    assert training_investment(poor, [poor], hunt_available=True, searches=3)['eligible']
    assert training_investment(poor, [poor], hunt_available=False)['eligible']
    assert training_investment(partner(95, POOR), [], hunt_available=True)['eligible']


def test_equal_duplicate_does_not_restart_training_but_substantial_upgrade_does():
    veteran = partner(100, POOR)
    assert not training_investment(partner(5, POOR), [veteran])['eligible']
    result = training_investment(partner(), [veteran])
    assert result['eligible'] and result['priority'] == 3
    # Rarity alone does not make a nearly equivalent fully trained replacement worthwhile.
    near_perfect = partner(100, (15, 15, 15, 15, 13))
    assert not training_investment(partner(5, (15, 15, 15, 13, 15)), [near_perfect])['eligible']
    assert training_investment(partner(dvs=(15,) * 5), [near_perfect])['eligible']


def test_rare_low_level_training_beats_ordinary_high_level_mastery():
    d = AdventureDirector()
    rows = [(1, {'method': 'train', 'key': 'rare', 'initial_level': 5, 'investment_priority': 3}),
            (1000, {'method': 'train', 'key': 'old', 'initial_level': 99,
                    'investment_priority': 1, 'mastery_needed': True})]
    assert d.select(rows, random.Random(1))['key'] == 'rare'


def test_collection_search_budget_survives_restart_and_counts_failures():
    c = Collection()
    for i in range(3):
        c.project = {'method': 'grass', 'species': 0x99, 'dv_hunt': True, 'repeat': True, 'key': 'hunt'}
        assert c.abandon('No reachable encounter')
        restored = Collection()
        restored.load(json.loads(json.dumps(c.state_dict())))
        c = restored
        assert c.quality_searches['153'] == i + 1
    c.abandon('No project')
    assert c.quality_searches['153'] == 3
    old = Collection()
    old.load({})
    assert old.quality_searches == {}


def test_collection_defers_poor_farmable_partner_then_allows_it_after_budget():
    mon = replace(individual(5, 1, 10), dvs=POOR)
    s = postgame(party=(mon,))
    assert not any(p['method'] == 'train' for _, p in candidates(s))
    rows = candidates(s, searches=3)
    assert any(p['method'] == 'train' for _, p in rows)


def test_api_uses_same_assessment_for_party_and_boxed_individuals():
    mon = replace(individual(5, 1, 1), dvs=RARE)
    boxed = stored(0, level=5, dvs=RARE, trainer_id=2)
    result = live_status(snapshot([boxed], party=(mon,)).to_dict(), None)
    for key in ('dv_top_percent', 'dv_better_percent', 'potential_power'):
        assert result['party'][0][key] == result['storage']['pokemon'][0][key]
    assert asdict(mon)['dvs'] == RARE


def test_npc_trade_skips_rare_partner_but_can_use_an_ordinary_spare():
    rare = replace(individual(5, 1, 1), dvs=RARE)
    ordinary = replace(individual(5, 2, 1), dvs=POOR)
    s = postgame(party=(individual(100, 3, 113), rare, ordinary))
    choice = Collection().trade_candidate(s, {'give': rare.species})
    assert choice['party_index'] == 2


def test_older_veteran_can_trade_after_replacement_catches_up():
    newcomer = stored(0, level=100, dvs=RARE, stat_exp=(65535,) * 5)
    old = stored(1, level=100, dvs=POOR, stat_exp=(65535,) * 5)
    payload = live_status(snapshot([newcomer, old]).to_dict(), None)
    inv = normalise('red', 'http://red', payload)
    assert [(copy.position, copy.level) for copy in inv.tradeable] == [(2, 100)]


def test_registered_evolution_does_not_bypass_small_upgrade_threshold():
    from pokesim.investment import potential_power
    from test_collection import sid
    newer = replace(individual(5, 1, 25), dvs=(15, 15, 15, 15, 13))
    older = replace(individual(100, 2, 26), dvs=(15, 15, 15, 15, 11))
    future = {**asdict(newer), 'species': sid(26)}
    gain = potential_power(future) / potential_power(asdict(older)) - 1
    assert 0 < gain < 0.02
    rows = candidates(postgame(party=(newer, older)))
    assert not any(p['method'] == 'evolve' and p['parent'] == newer.species for _, p in rows)
