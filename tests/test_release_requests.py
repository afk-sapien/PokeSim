"""An owner's release request is stored by trade identity, starts the next PC visit, goes first and is
dropped once its Pokémon has gone. A Keep, party, egg or unconfirmed last copy request never starts one."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.gen2 import ledger
from pokesim.gen2.release import BOX_CAPACITY, pending
from pokesim.pcvalue import DEADLOCK, LAST_COPY
from pokesim.planning.ledger import BOX_REFILL
from pokesim.policies.team import held_identities, requested_slots
from pokesim.store import Store
from pokesim.trade.preferences import identity
from test_gen2_storage_ledger import BEST, PARTY, Policy, mon, no_breeding_stock, snapshot  # noqa: F401  (fixture)
from test_release_origins import best_and, stored
from test_release_origins import snapshot as gen1_snapshot
from test_trade_preferences import game  # noqa: F401  (fixture)


def key(row):
    return identity({'trainer_id': row.trainer_id, 'dvs': row.dvs, 'dex': row.species})


def gen1_key(mon):
    return identity({'trainer_id': mon.trainer_id, 'dvs': mon.dvs, 'species': mon.species})


def test_the_store_keeps_drops_and_prunes_requests(tmp_path):
    store = Store(tmp_path)
    assert store.release_requests() == {}
    store.set_release_request('a', 'release')
    store.set_release_request('b', LAST_COPY)
    assert store.release_requests() == {'a': 'release', 'b': LAST_COPY}
    store.set_release_request('a', '')
    assert store.release_requests() == {'b': LAST_COPY}
    assert store.prune_release_requests({'c'}) == {}
    assert store.release_requests() == {}


def test_attach_gives_a_policy_every_release_input(tmp_path):
    store = Store(tmp_path)
    policy = SimpleNamespace()
    store.attach(policy, 2)
    store.set('pc_favor', 'shiny')
    store.set_release_request('a', 'release')
    assert policy.release_requests() == {'a': 'release'}
    assert policy.pc_favor() == 'shiny'
    assert policy.league_marks() == frozenset()
    store.set('pc_favor', 'anything else')
    assert policy.pc_favor() is None


def test_a_gen1_request_waits_for_a_visit_unless_it_is_kept():
    weak = stored(1, dvs=(2,) * 5)
    s = gen1_snapshot(best_and(weak))
    assert requested_slots(s, {gen1_key(weak): 'release'}) == [(0, 1)]
    assert requested_slots(s, {gen1_key(weak): 'release'}, {gen1_key(weak): {'state': 'locked'}}) == []
    assert requested_slots(s, {gen1_key(weak): 'release'}, reserved={(0, 1)}) == []
    lone = stored(2, 19)
    assert requested_slots(gen1_snapshot(best_and(weak, lone)), {gen1_key(lone): 'release'}) == []
    assert requested_slots(gen1_snapshot(best_and(weak, lone)), {gen1_key(lone): LAST_COPY}) == [(0, 2)]
    assert gen1_key(weak) in held_identities(s)



def test_compact_fallback_rows_never_drop_a_request():
    weak = stored(1, dvs=(2,) * 5)
    full = gen1_snapshot(best_and(weak))
    compact = replace(full, stored_details=())
    assert held_identities(compact) is None
    from pokesim.policies.strategic import StrategicPolicy
    policy = StrategicPolicy(7)
    asked = {gen1_key(weak): 'release', 'gone': 'release'}
    policy.release_requests = lambda: dict(asked)
    policy.prune_release_requests = lambda held: pytest.fail('pruned from compact rows')
    policy.release_pending(compact)
    policy.prune_release_requests = lambda held: {key: value for key, value in asked.items() if key in held}
    assert policy.release_pending(full)


def test_the_gen1_menu_takes_the_planners_choice():
    from pokesim.policies.strategic import StrategicPolicy
    cheap, asked = stored(1, dvs=(1,) * 5), stored(2, dvs=(9,) * 5)
    s = gen1_snapshot(best_and(cheap, asked), box_counts=(20,) * 12)
    policy = StrategicPolicy(7)
    policy.release_requests = lambda: {gen1_key(asked): 'release'}
    assert policy._release_target(s) == (0, 2)
    # The PC menu ranks with the same call, so release_changed never cancels the menu's pick.
    assert policy.pc.box_target(s, 'party_release', None, {}) == 0
    assert policy.pc.target(s, 'party_release', None, {}) == 2
    policy.pc_favor = lambda: 'dvs'
    assert policy.pc.target(s, 'party_release', None, {}) == policy._release_target(s)[1]


def test_the_gen1_full_notice_needs_a_full_pc():
    from pokesim.policies.strategic import StrategicPolicy
    lone = [stored(0, level=60), stored(1, 19)]
    policy = StrategicPolicy(7)
    policy._release_target(gen1_snapshot(lone, box_counts=(2,) + (0,) * 11))
    assert not policy.pc_deadlock
    policy._release_target(gen1_snapshot(lone, box_counts=(20,) * 12))
    assert policy.pc_deadlock


class Requests(Policy):
    def __init__(self, requests):
        super().__init__()
        self.requests = dict(requests)

    def release_requests(self):
        return dict(self.requests)

    def prune_release_requests(self, held):
        self.requests = {k: v for k, v in self.requests.items() if k in held}
        return dict(self.requests)


def test_a_gen2_request_starts_a_visit_and_is_dropped_once_gone():
    weak = mon(1)
    roomy = snapshot([BEST, weak], PARTY)
    roomy.box_counts = (BOX_CAPACITY - BOX_REFILL,) + (BOX_CAPACITY,) * 13
    policy = Requests({key(weak): 'release'})
    policy.storage_target = lambda view: ledger.storage_unit(policy, view)
    assert pending(policy, roomy)
    # With the refill mark reached the request still goes.
    assert ledger.release_step(policy, roomy) == 'a' and policy.menu.position == 1
    gone = snapshot([BEST], PARTY)
    assert not pending(policy, gone) and policy.requests == {}


def test_a_gen2_request_for_a_last_copy_waits_until_the_confirm_names_it():
    lone = mon(1, species=19)
    view = snapshot([BEST, lone], PARTY)
    assert not pending(Requests({key(lone): 'release'}), view)
    assert pending(Requests({key(lone): LAST_COPY}), view)


def test_the_pc_api_saves_requests_and_favor_and_shows_each_value(game, monkeypatch):
    client, store, emu = game
    mon = client.get('/api/pokedex/status').json()['storage']['pokemon'][0]
    slot = (mon['box'] - 1, mon['position'] - 1)
    emu.pc_values.return_value = ({slot: {'score': 40, 'text': 'Score 40', 'status': 'spare', 'reason': '',
                                          'next': 1, 'requested': None}}, True)
    emu.request_release.side_effect = lambda box, position, key, confirm: (
        store.set_release_request(key, 'release') and 'release')
    body = {'key': mon['trade_key'], 'box': mon['box'], 'position': mon['position']}
    assert client.post('/api/pc/release', json=body).json() == {'ok': True, 'request': 'release'}
    emu.request_release.assert_called_once_with(*slot, mon['trade_key'], '')
    assert client.post('/api/pc/favor', json={'favor': 'dvs'}).status_code == 200
    page = client.get('/api/pokedex/status?view=pc').json()
    shown = page['storage']['pokemon'][0]
    assert shown['pc_value']['next'] == 1 and shown['release_requested']
    assert page['pc_favor'] == 'dvs' and page['pc_deadlock'] == DEADLOCK
    assert client.post('/api/pc/release', json={**body, 'cancel': True}).status_code == 200
    assert store.release_requests() == {}
    assert client.post('/api/pc/favor', json={'favor': 'level'}).status_code == 422


def test_the_pc_api_refuses_a_kept_pokemon_and_watchers(game, monkeypatch):
    client, store, emu = game
    emu.request_release.side_effect = ValueError('Pikachu is set to Keep. Change its trade setting first.')
    body = {'key': 'k', 'box': 1, 'position': 1}
    refused = client.post('/api/pc/release', json=body)
    assert refused.status_code == 409 and 'set to Keep' in refused.json()['detail']
    monkeypatch.setattr(config, 'VIEWER_ONLY', True)
    assert client.post('/api/pc/release', json=body).status_code == 403
    assert client.post('/api/pc/favor', json={'favor': 'shiny'}).status_code == 403
    assert store.release_requests() == {} and store.pc_favor() is None


def test_gen2_pc_values_are_rated_once_until_an_input_changes():
    import os
    from pokesim.gen2.data import GameData
    from pokesim.gen2.policy import Policy as Gen2Policy
    if not os.environ.get('GEN2_DATA_DIR'):
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    policy = Gen2Policy(GameData.load(os.environ['GEN2_DATA_DIR'], 'crystal'), seed=1, starter='cyndaquil')
    weak = mon(1)
    view = snapshot([BEST, weak], PARTY)
    asked = {}
    policy.release_requests = lambda: dict(asked)
    first = policy.pc_rated(view)
    assert policy.pc_rated(view) is first and pending(policy, view) is False
    asked[key(weak)] = 'release'
    assert policy.pc_rated(view) is not first and pending(policy, view)
    # Linked adventures missing the species add trade demand to its spare.
    policy.demand = {16: 1}
    assert 'Wanted in trade' in policy.pc_rated(view)[-1].describe()


def test_the_gen1_release_keeps_the_note_of_the_pokemon_it_took():
    from pokesim.policies.strategic import StrategicPolicy
    cheap, other = stored(1, dvs=(1,) * 5), stored(2, dvs=(3,) * 5)
    s = gen1_snapshot(best_and(cheap, other), box_counts=(20,) * 12)
    policy = StrategicPolicy(7)
    assert policy._release_target(s) == (0, 1)
    taken = policy.release_note
    policy._request(s, ('release', 1), 'Let a spare go')
    # The next target's note replaces release_note, but the journal quotes the one taken.
    policy._release_target(gen1_snapshot(best_and(other), box_counts=(20,) * 12))
    assert policy.released_note == taken and policy.release_note != taken
