from pokesim.app.coordinator import Coordinator
from pokesim.app.registry import identifier
from test_managed_coordinator import Peer, setup


def offer(key, dex, level=20):
    return {'trade_key': key, 'dex': dex, 'arrived_dex': dex, 'level': level}


def inventory(*offers):
    return {'owned': [16, 19, 25],
            'party': [{'dex': dex, 'level': 10} for dex in [16, 19, 25]],
            'offers': list(offers)}


def completed(setup, left_key='previous-left', right_key='previous-right', phase='completed', at=0):
    left, right = setup.data['left_id'], setup.data['right_id']
    tid = identifier()
    plan = {'participants': [left, right], 'left_id': left, 'right_id': right,
            'left_key': left_key, 'right_key': right_key,
            'campaign_ids': {aid: setup.registry.adventure(aid)['campaign_id'] for aid in [left, right]},
            'display_offers': {left: {'dex': 25}, right: {'dex': 19}}}
    setup.registry.create_transaction(tid, plan)
    setup.registry.update_transaction(tid, phase=phase, decision='COMMIT' if phase == 'completed' else 'ABORT')
    with setup.registry.lock, setup.registry.db:
        setup.registry.db.execute('UPDATE interactions SET updated_at=? WHERE id=?', (at, tid))
    return plan


def selection(setup, monkeypatch, inventories, coordinator=None):
    c = coordinator or setup.coordinator
    selected = []
    monkeypatch.setattr(c, 'inventory', inventories.__getitem__)
    def propose(data, **chosen):
        selected.append(data)
        return {'id': 'selected'}
    monkeypatch.setattr(c, 'propose', propose)
    monkeypatch.setattr(c, 'execute', lambda _: selected[-1])
    return c.schedule_once()


def test_same_individual_cannot_return_for_another_quality_upgrade(setup, monkeypatch):
    completed(setup, left_key='returning')
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('new-left', 25)), right: inventory(offer('returning', 19))}
    assert selection(setup, monkeypatch, inventories) is None


def test_return_is_allowed_when_it_registers_a_new_species(setup, monkeypatch):
    completed(setup, left_key='returning')
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('new-left', 25)), right: inventory(offer('returning', 19))}
    inventories[left]['owned'] = [25]
    assert selection(setup, monkeypatch, inventories) is not None


def test_equal_benefit_prefers_species_outside_recent_exchanges(setup, monkeypatch):
    completed(setup)
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('zzz-repeated-species', 25), offer('aaa-diverse-species', 16)),
                   right: inventory(offer('new-right', 19))}
    selected = selection(setup, monkeypatch, inventories)
    assert 'aaa-diverse-species' in [selected['left_key'], selected['right_key']]


def test_new_pokedex_entries_outrank_species_variety(setup, monkeypatch):
    completed(setup)
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('repeated-species', 25), offer('diverse-species', 16)),
                   right: inventory(offer('new-right', 19))}
    inventories[right]['owned'] = [16, 19]
    selected = selection(setup, monkeypatch, inventories)
    assert 'repeated-species' in [selected['left_key'], selected['right_key']]


def test_scheduler_considers_best_exchange_across_all_games(setup, monkeypatch):
    third = setup.registry.create('Third', 'rom', {}, identifier())
    setup.registry.transition(third['id'], 'running', 'test setup', desired_state='running')
    setup.peers[third['id']] = Peer(third['id'], 'third')
    ids = sorted(game['id'] for game in setup.registry.adventures())
    inventories = {aid: inventory(offer(aid, 25)) for aid in ids}
    inventories[ids[-1]]['owned'] = []
    selected = selection(setup, monkeypatch, inventories)
    assert ids[-1] in [selected['left_id'], selected['right_id']]


def test_visited_individuals_survive_coordinator_restart_and_history_window(setup, monkeypatch):
    completed(setup, left_key='returning')
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('new-left', 25)), right: inventory(offer('returning', 19))}
    c = Coordinator(setup.manager)
    monkeypatch.setattr(setup.registry, 'transactions', lambda **_: [])
    assert selection(setup, monkeypatch, inventories, c) is None
    c.close()


def test_aborted_exchanges_do_not_claim_visits(setup, monkeypatch):
    completed(setup, left_key='returning', phase='aborted')
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('new-left', 25)), right: inventory(offer('returning', 19))}
    assert selection(setup, monkeypatch, inventories) is not None


def test_new_campaign_does_not_inherit_previous_campaign_visits(setup, monkeypatch):
    completed(setup, left_key='returning')
    left, right = setup.data['left_id'], setup.data['right_id']
    setup.registry.update(left, campaign_id=identifier())
    inventories = {left: inventory(offer('new-left', 25)), right: inventory(offer('returning', 19))}
    assert selection(setup, monkeypatch, inventories) is not None


def test_the_same_species_pair_waits_after_a_trade(setup, monkeypatch):
    # Live, two games swapped the same two species back and forth for small gains.
    import time
    completed(setup, at=time.time() - 3600)
    left, right = setup.data['left_id'], setup.data['right_id']
    inventories = {left: inventory(offer('again', 25), offer('other', 16)), right: inventory(offer('new-right', 19))}
    selected = selection(setup, monkeypatch, inventories)
    assert 'other' in selected.values()
    # A new Pokédex entry still justifies the same pair.
    inventories[right]['owned'] = [19]
    assert 'again' in selection(setup, monkeypatch, {left: inventory(offer('again', 25)), right: inventories[right]}).values()


def test_a_trade_the_receiver_would_release_is_skipped_and_its_pair_waits(setup, monkeypatch):
    from pokesim.app.coordinator import pair_key
    left, right = setup.data['left_id'], setup.data['right_id']
    c = setup.coordinator
    asked = []
    def would_keep(aid, mon):
        asked.append((aid, mon['dex']))
        return mon['dex'] != 25
    monkeypatch.setattr(c, '_would_keep', would_keep)
    # Both gain a level, and the lower level 25 ranks first.
    inventories = {left: inventory(offer('spare', 25), offer('kept', 16, 30)), right: inventory(offer('new-right', 19))}
    selected = selection(setup, monkeypatch, inventories)
    assert 'kept' in selected.values() and (right, 25) in asked
    assert pair_key(left, right, {'dex': 25}, {'dex': 19}) in c.refused_pairs
    # The refused pair is not asked about again while it waits.
    asked.clear()
    selection(setup, monkeypatch, inventories)
    assert (right, 25) not in asked


def test_a_worker_that_cannot_answer_does_not_block_its_trade(setup, monkeypatch):
    left, right = setup.data['left_id'], setup.data['right_id']
    c = setup.coordinator
    def refuse(aid, operation, data=None, recovery=False):
        if operation == 'would_keep':
            raise RuntimeError('Adventure worker did not answer')
        return original(aid, operation, data, recovery)
    original = c._request
    monkeypatch.setattr(c, '_request', refuse)
    inventories = {left: inventory(offer('only', 25, 30)), right: inventory(offer('new-right', 19))}
    assert selection(setup, monkeypatch, inventories) is not None
