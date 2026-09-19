from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.policies.base import Action, PolicyContext
from pokesim.runtime import preparation
from pokesim.store import Store
from pokesim.trade.preferences import identity
from test_duplicates import snapshot, stored
from test_strategy import mon


@pytest.fixture
def participant(tmp_path, monkeypatch):
    candidate = stored(0, trainer_id=101)
    snap = replace(snapshot([candidate], party=(mon(trainer_id=202, dvs=(3,) * 5),)),
                   map=89, x=13, y=4)
    store = Store(tmp_path)
    memory = bytearray(65536)
    emu = SimpleNamespace(store=store, paused=False, manual_mode=False, frame=snap.frame,
                          input_epoch=0, preparation=None, policy=Mock(), pb=SimpleNamespace(memory=memory))
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: snap)
    yield emu, snap, candidate
    store.close()


def test_preparation_reservation_is_durable_and_idempotent(participant):
    emu, _, candidate = participant
    key = identity(asdict(candidate))
    result = preparation.begin(emu, key, 'transaction-1')
    assert result['phase'] == 'travelling'
    assert result['selected_key'] == key
    assert preparation.begin(emu, key, 'transaction-1') == result
    with pytest.raises(ValueError, match='reserved'):
        preparation.begin(emu, key, 'transaction-2')
    assert emu.store.get(preparation.KEY)['id'] == 'transaction-1'


def test_restart_pauses_preparation_until_coordinator_recovery(participant):
    emu, _, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    preparation.restore(emu)
    assert emu.paused
    assert emu.preparation is None
    assert preparation.cancel(emu, 'transaction-1')['phase'] == 'cancelled'
    assert not emu.paused
    emu.policy.on_restore.assert_called_once()


def test_protection_change_cancels_before_pc_input(participant):
    emu, snap, candidate = participant
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    emu.store.set_trade_preference(key, {'state': 'locked'})
    actions = emu.preparation.step(PolicyContext(snap, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert emu.preparation is None


def test_active_party_and_ambiguous_individuals_are_not_reserved(participant, monkeypatch):
    emu, snap, candidate = participant
    party_key = identity(asdict(snap.party[0]))
    with pytest.raises(ValueError, match='Active party'):
        preparation.begin(emu, party_key, 'party')
    repeated = replace(snap, stored_details=(candidate, replace(candidate, position=1)))
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: repeated)
    with pytest.raises(ValueError, match='uniquely'):
        preparation.begin(emu, identity(asdict(candidate)), 'ambiguous')
    assert emu.store.get(preparation.KEY) is None


def test_arrival_holds_exact_withdrawn_partner_before_export(participant):
    emu, snap, candidate = participant
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    arrived = replace(snapshot([], party=(snap.party[0], partner)), map=89, x=11, y=3)
    calls = []

    def hold(action, transaction):
        calls.append((action, transaction))
        emu.paused = True

    emu._trade = hold
    assert emu.preparation.step(PolicyContext(arrived, 0, 0, emu.pb.memory)) == []
    assert calls == [('prepare', 'transaction-1')]
    assert emu.store.get(preparation.KEY)['party_slot'] == 1
    assert emu.store.get(preparation.KEY)['phase'] == 'ready'
    assert emu.paused


@pytest.mark.parametrize('busy', [{'in_battle': True}, {'textbox': True}, {'start_menu': True}])
def test_preparation_waits_for_natural_safe_point(participant, monkeypatch, busy):
    emu, snap, candidate = participant
    active = replace(snap, **busy)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    ordinary_actions = [Action('a', 4, 8)]
    emu.policy.step.return_value = ordinary_actions
    memory = bytes(emu.pb.memory)
    result = preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    assert result['phase'] == 'travelling'
    assert result['waiting_for'] == 'overworld'
    assert emu.input_epoch == 0
    assert not emu.paused
    controller = emu.preparation
    assert controller.step(PolicyContext(active, 0, 0, emu.pb.memory)) == ordinary_actions
    later = replace(active, frame=active.frame + 4000)
    emu.frame = later.frame
    assert controller.step(PolicyContext(later, 0, 0, emu.pb.memory)) == ordinary_actions
    assert emu.store.get(preparation.KEY)['waiting_for'] == 'overworld'
    safe = replace(snap, frame=later.frame + 1)
    emu.frame = safe.frame
    actions = controller.step(PolicyContext(safe, 0, 0, emu.pb.memory))
    assert actions == [Action('up', 4, 8)]
    assert emu.policy.step.call_count == 2
    assert 'waiting_for' not in emu.store.get(preparation.KEY)
    assert emu.store.get(preparation.KEY)['phase'] == 'storage'
    assert emu.store.get('trade_hold') is None
    assert bytes(emu.pb.memory) == memory


def test_safe_point_wait_has_a_frame_deadline(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1', max_frames=60)
    expired = replace(active, frame=active.frame + 61)
    actions = emu.preparation.step(PolicyContext(expired, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'deadline' in emu.store.get(preparation.KEY)['error']
    emu.policy.step.assert_not_called()
    assert emu.preparation is None


def test_safe_point_wait_rechecks_protection_before_policy_input(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    emu.store.set_trade_preference(key, {'state': 'locked'})
    actions = emu.preparation.step(PolicyContext(active, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    emu.policy.step.assert_not_called()


def test_waiting_restart_and_cancellation_remain_recoverable(participant, monkeypatch):
    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, in_battle=True))
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    preparation.restore(emu)
    assert emu.paused
    assert emu.preparation is None
    assert preparation.cancel(emu, 'transaction-1')['phase'] == 'cancelled'
    assert not emu.paused
    emu.policy.on_restore.assert_called_once()


def test_participant_reports_preparing_while_battle_finishes(participant, monkeypatch):
    from pokesim.app.registry import identifier
    from pokesim.runtime.participant import Participant

    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, in_battle=True))
    key = identity(asdict(candidate))
    owner = Participant(SimpleNamespace(store=emu.store, emulator=emu), SimpleNamespace())
    monkeypatch.setattr(owner, 'inventory', lambda: {'offers': [{'trade_key': key}]})
    request = {'id': identifier(), 'plan_digest': 'unchanged-plan', 'selected_key': key}
    response = owner.prepare(request)
    assert response['phase'] == 'preparing'
    assert response['preparation']['waiting_for'] == 'overworld'
    assert owner.prepare(request) == response
    assert emu.store.get('trade_hold') is None


def test_waiting_does_not_adopt_an_unplanned_party_member(participant, monkeypatch):
    emu, snap, candidate = participant
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: replace(snap, start_menu=True))
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    moved = replace(snapshot([], party=(snap.party[0], partner)), map=89, x=11, y=3)
    actions = emu.preparation.step(PolicyContext(moved, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'moved before' in emu.store.get(preparation.KEY)['error']
    assert emu.store.get('trade_hold') is None
    emu.policy.step.assert_not_called()


def test_safe_point_wait_has_a_wall_clock_deadline(participant, monkeypatch):
    emu, snap, candidate = participant
    active = replace(snap, in_battle=True)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    state = preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    monkeypatch.setattr(preparation.time, 'time', lambda: state['deadline'] + 1)
    actions = emu.preparation.step(PolicyContext(active, 0, 0, emu.pb.memory))
    assert all(action.button is None for action in actions)
    assert emu.store.get(preparation.KEY)['phase'] == 'failed'
    assert 'deadline' in emu.store.get(preparation.KEY)['error']
    emu.policy.step.assert_not_called()


def storage_party():
    return tuple(mon(trainer_id=200 + i, level=50 if i == 0 else 10 + i,
                     dvs=(3,) * 5, moves=(33,)) for i in range(6))


def storage_menu(index=0):
    from test_strategy import menu
    return menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                (1, 1 + 2 * index), index=index, top=(1, 1))


def storage_step(controller, snap, memory):
    return controller.step(PolicyContext(snap, 0, 0, memory))[0].button


def test_full_active_box_deposits_elsewhere_before_switching_to_offer(participant):
    from pokesim.screen import W_TILEMAP
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    party = storage_party()
    full = replace(snap, party=party, boxed_pokemon=((153, 20),) * 20,
                   box_counts=(20, 20, 19) + (20,) * 9, textbox=True)
    assert storage_step(controller, full, storage_menu(3)) == 'a'
    assert controller.operation == 'change_box'
    assert controller.target_box == 2

    memory = menu({1: '             BOX 1', 2: '             BOX 2', 12: '             BOX12'},
                  (12, 3), index=2, top=(12, 1))
    memory[W_TILEMAP + 20 + 17] = 0xF7
    memory[W_TILEMAP + 12 * 20 + 16] = 0xF7
    memory[W_TILEMAP + 12 * 20 + 17] = 0xF8
    assert preparation.Screen(memory).kind(full) == 'change_box'
    assert storage_step(controller, full, memory) == 'a'

    available = replace(full, active_box=2, boxed_pokemon=((153, 20),) * 19)
    assert storage_step(controller, available, storage_menu(1)) == 'a'
    assert controller.operation == 'deposit'
    assert controller.deposit_key == identity(asdict(party[1]))
    memory = menu({1: '  PARTNER', 3: '  PARTNER', 7: '  CANCEL'}, (0, 3), index=1)
    assert preparation.Screen(memory).kind(available) == 'party'
    assert storage_step(controller, available, memory) == 'a'

    deposited = replace(available, party=party[:1] + party[2:],
                        boxed_pokemon=((153, 20),) * 20, box_counts=(20,) * 12)
    assert storage_step(controller, deposited, storage_menu(3)) == 'a'
    assert controller.operation == 'change_box'
    assert controller.target_box == candidate.box
    opened = replace(deposited, active_box=candidate.box)
    assert storage_step(controller, opened, storage_menu()) == 'a'
    assert controller.operation == 'withdraw'
    memory = menu({4: '     PARTNER', 6: '     CANCEL'}, (5, 4), top=(5, 4))
    assert preparation.Screen(memory).kind(opened) == 'list'
    assert storage_step(controller, opened, memory) == 'a'
    assert emu.store.get(preparation.KEY)['phase'] == 'storage'


def test_full_storage_fails_without_releasing_anything(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    full = replace(snap, party=storage_party(), boxed_pokemon=((153, 20),) * 20,
                   box_counts=(20,) * 12, textbox=True)
    assert storage_step(emu.preparation, full, storage_menu(2)) is None
    assert 'Every PC box is full' in emu.store.get(preparation.KEY)['error']


@pytest.mark.parametrize('state', ['locked', 'offered', 'withdrawn'])
def test_protected_preferred_reserve_uses_another_safe_partner(participant, state):
    emu, snap, candidate = participant
    party = storage_party()
    emu.store.set_trade_preference(identity(asdict(party[1])), {'state': state})
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    full = replace(snap, party=party, textbox=True)
    assert storage_step(controller, full, storage_menu(1)) == 'a'
    assert controller.deposit_key == identity(asdict(party[2]))


def test_storage_reserve_never_drops_strongest_or_unique_field_move(participant):
    emu, snap, candidate = participant
    party = tuple(replace(p, moves=(move,)) for p, move in
                  zip(storage_party(), (33, 15, 19, 57, 70, 148)))
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    assert storage_step(emu.preparation, replace(snap, party=party), storage_menu(1)) is None
    assert 'No safe unprotected reserve' in emu.store.get(preparation.KEY)['error']


def test_storage_reserve_rechecks_identity_and_protection_in_party_menu(participant):
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    full = replace(snap, party=storage_party(), textbox=True)
    assert storage_step(controller, full, storage_menu(1)) == 'a'
    emu.store.set_trade_preference(controller.deposit_key, {'state': 'locked'})
    memory = menu({1: '  PARTNER', 3: '  PARTNER', 7: '  CANCEL'}, (0, 3), index=1)
    assert storage_step(controller, full, memory) is None
    assert 'became protected' in emu.store.get(preparation.KEY)['error']


def test_withdraw_uses_refreshed_identity_position_and_rejects_wrong_box(participant):
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    assert storage_step(controller, snap, storage_menu()) == 'a'
    candidate = replace(candidate, position=5)
    moved = replace(snapshot([candidate], party=snap.party), map=89, x=13, y=4, textbox=True)
    memory = menu({4: '     PARTNER', 6: '     CANCEL'}, (5, 4), index=0, top=(5, 4))
    memory[0xCC36] = 5
    assert storage_step(controller, moved, memory) == 'a'
    assert storage_step(controller, replace(moved, active_box=1), memory) == 'b'


def test_stale_deposit_list_closes_after_party_slot_is_free(participant):
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    full = replace(snap, party=storage_party(), textbox=True)
    assert storage_step(controller, full, storage_menu(1)) == 'a'
    memory = menu({1: '  PARTNER', 3: '  PARTNER', 7: '  CANCEL'}, (0, 3), index=1)
    assert storage_step(controller, replace(full, party=full.party[:5]), memory) == 'b'


def test_unexpected_pc_confirmation_is_not_accepted(participant):
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    memory = menu({1: '    YES', 3: '    NO'}, (3, 1), top=(3, 1))
    assert preparation.Screen(memory).kind(snap) == 'yes_no'
    assert storage_step(controller, snap, memory) == 'b'
    controller.operation = 'change_box'
    assert storage_step(controller, snap, memory) == 'a'


def test_selected_reserve_follows_identity_when_party_order_changes(participant):
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    full = replace(snap, party=storage_party(), textbox=True)
    assert storage_step(controller, full, storage_menu(1)) == 'a'
    reordered = replace(full, party=full.party[:1] + full.party[2:] + full.party[1:2])
    memory = menu({1: '  PARTNER', 3: '  PARTNER', 7: '  CANCEL'}, (0, 3), index=1)
    assert storage_step(controller, reordered, memory) == 'down'
    assert controller.deposit_key == identity(asdict(full.party[1]))


def test_ambiguous_reserves_do_not_get_deposited(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    party = storage_party()
    ambiguous = replace(snap, party=party[:1] + (party[1],) * 5, textbox=True)
    assert storage_step(emu.preparation, ambiguous, storage_menu(1)) is None
    assert 'No safe unprotected reserve' in emu.store.get(preparation.KEY)['error']


def test_withdraw_waits_for_cartridge_to_remove_temporary_box_copy(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.operation = 'withdraw'
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    transferring = replace(snap, party=(*snap.party, partner), textbox=True)
    memory = storage_menu()
    assert storage_step(controller, transferring, memory) is None
    assert emu.preparation is controller
    settled = replace(transferring, stored_details=(), stored_pokemon=(), frame=snap.frame + 12)
    assert storage_step(controller, settled, memory) == 'b'
    assert controller.state['phase'] == 'rendezvous'
    assert controller.selection_wait_since is None


def test_pc_identity_wait_is_bounded_and_sends_no_inputs(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.operation = 'change_box'
    missing = replace(snap, stored_details=(), stored_pokemon=(), textbox=True)
    assert storage_step(controller, missing, storage_menu()) is None
    assert storage_step(controller, replace(missing, frame=snap.frame + 180), storage_menu()) is None
    assert emu.preparation is None
    assert 'uniquely' in controller.state['error']


def test_encounter_during_travel_uses_the_same_traveller(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    actions = [Action('a', 6, 12)]
    controller.traveller = Mock()
    controller.traveller.step.return_value = actions
    encounter = replace(snap, map=12, in_battle=True)
    ctx = PolicyContext(encounter, 0, 0, emu.pb.memory)
    assert controller.step(ctx) == actions
    controller.traveller.step.assert_called_once_with(ctx)
    emu.policy.step.assert_not_called()
    assert controller.state['phase'] == 'travelling'
    assert emu.store.get('trade_hold') is None


def test_field_move_menu_sequence_stays_with_traveller(participant):
    from pokesim.policies.battle import Decision
    from test_strategy import menu

    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    travelling = replace(snap, map=12, x=10, y=10, frame=snap.frame + 100,
                         party=(replace(snap.party[0], moves=(57,)),), start_menu=True)
    traveller = controller.traveller
    traveller.observed_map = travelling.map
    traveller.intent = Decision('field', 0, reason='Use Surf to cross the water')
    traveller.intent_since = travelling.frame
    traveller.field_move = 'SURF'
    stages = [
        ('pause', menu({1: '  MON', 3: '  ITEM', 5: '  EXIT'}, (1, 1))),
        ('party', menu({1: '  PARTNER', 7: '  CANCEL'}, (0, 1), top=(0, 1))),
        ('party_action', menu({1: '  SURF', 3: '  STATS', 5: '  SWITCH'}, (1, 1))),
    ]
    for kind, memory in stages:
        assert preparation.Screen(memory).kind(travelling) == kind
        assert storage_step(controller, travelling, memory) == 'a'
        assert controller.traveller is traveller
        assert traveller.intent.kind == 'field'
        travelling = replace(travelling, frame=travelling.frame + 60)
    emu.policy.step.assert_not_called()
    assert controller.state['phase'] == 'travelling'
    assert emu.store.get('trade_hold') is None


@pytest.mark.parametrize(('operation', 'map_id', 'menu_open'), [
    (None, preparation.CENTER, True),
    ('withdraw', 12, True),
    ('withdraw', preparation.CENTER, False),
])
def test_identity_wait_does_not_hide_a_missing_selection_outside_pc_transfer(
        participant, operation, map_id, menu_open):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.operation = operation
    missing = replace(snap, map=map_id, stored_details=(), stored_pokemon=(), textbox=menu_open)
    memory = storage_menu() if menu_open else emu.pb.memory
    assert storage_step(controller, missing, memory) is None
    assert controller.state['phase'] == 'failed'
    assert 'uniquely' in controller.state['error']
    assert emu.preparation is None


def test_identity_wait_rechecks_protection_when_transfer_settles(participant):
    emu, snap, candidate = participant
    key = identity(asdict(candidate))
    preparation.begin(emu, key, 'transaction-1')
    controller = emu.preparation
    controller.operation = 'withdraw'
    partner = mon(trainer_id=candidate.trainer_id, dvs=candidate.dvs)
    transferring = replace(snap, party=(*snap.party, partner), textbox=True)
    assert storage_step(controller, transferring, storage_menu()) is None
    emu.store.set_trade_preference(key, {'state': 'locked'})
    settled = replace(transferring, stored_details=(), stored_pokemon=(), frame=snap.frame + 12)
    assert storage_step(controller, settled, storage_menu()) is None
    assert controller.state['phase'] == 'failed'
    assert 'protected' in controller.state['error']
    assert emu.store.get('trade_hold') is None


@pytest.mark.parametrize('progress', ['hp', 'pp'])
def test_long_travel_battle_with_health_or_move_progress_does_not_time_out(participant, progress):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    actions = [Action('a', 6, 12)]
    controller.traveller = Mock()
    controller.traveller.step.return_value = actions
    for turn in range(4):
        partner = replace(snap.party[0], **({'hp': snap.party[0].hp - turn} if progress == 'hp'
                          else {'pp': (snap.party[0].pp[0] - turn, *snap.party[0].pp[1:])}))
        battle = replace(snap, map=12, in_battle=True, frame=snap.frame + turn * 2000,
                         party=(partner,))
        emu.frame = battle.frame
        assert controller.step(PolicyContext(battle, 0, 0, emu.pb.memory)) == actions
        assert emu.preparation is controller
        assert controller.state['phase'] == 'travelling'
    assert controller.traveller.step.call_count == 4
    stalled = replace(battle, frame=battle.frame + 3601)
    emu.frame = stalled.frame
    assert all(action.button is None for action in controller.step(
        PolicyContext(stalled, 0, 0, emu.pb.memory)))
    assert emu.preparation is None
    assert 'stopped making progress' in controller.state['error']


@pytest.mark.parametrize('kind,text', [
    ('change_box', 'Choose a PKMN BOX.'),
    ('dialogue', 'WITHDRAW PKMN DEPOSIT PKMN CHANGE BOX What?'),
])
def test_pc_box_transition_waits_without_reopening_current_menu(participant, monkeypatch, kind, text):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.operation = 'change_box'
    screen = SimpleNamespace(kind=lambda _: kind, text=text, menu_index=0, scroll=0, cursor=None)
    monkeypatch.setattr(preparation, 'Screen', lambda _: screen)
    assert storage_step(controller, snap, emu.pb.memory) is None
    assert emu.preparation is controller


def test_center_walking_waits_for_map_transition_before_failing(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.nav.route = Mock(side_effect=[None, 'right'])
    ctx = PolicyContext(snap, 0, 0, emu.pb.memory)
    assert controller._walk(ctx, ((89, 11, 3),))[0].button is None
    assert controller._walk(ctx, ((89, 11, 3),))[0].button == 'right'
    assert controller.walk_wait_since is None


def test_center_walking_cannot_wait_forever_on_an_impossible_route(participant):
    emu, snap, candidate = participant
    preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
    controller = emu.preparation
    controller.nav.route = Mock(return_value=None)
    controller._walk(PolicyContext(snap, 0, 0, emu.pb.memory), ((89, 11, 3),))
    later = replace(snap, frame=snap.frame + 600)
    with pytest.raises(ValueError, match='No supported walking route'):
        controller._walk(PolicyContext(later, 0, 0, emu.pb.memory), ((89, 11, 3),))


@pytest.mark.parametrize('league_map', sorted(preparation.LEAGUE))
def test_trade_preparation_finishes_league_before_taking_over(participant, monkeypatch, league_map):
    emu, snap, candidate = participant
    active = replace(snap, map=league_map)
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: active)
    ordinary_actions = [Action('up', 8, 12)]
    emu.policy.step.return_value = ordinary_actions
    result = preparation.begin(emu, identity(asdict(candidate)), 'league-trade')
    assert result['waiting_for'] == 'overworld'
    assert 'League run' in result['waiting_reason']
    controller = emu.preparation
    assert controller.step(PolicyContext(active, 0, 0, emu.pb.memory)) == ordinary_actions
    assert emu.input_epoch == 0
    safe = replace(snap, map=174, x=15, y=8, frame=active.frame + 100)
    emu.frame = safe.frame
    controller.step(PolicyContext(safe, 0, 0, emu.pb.memory))
    assert 'waiting_for' not in controller.state
    assert controller.state['phase'] == 'storage'


def test_league_inventory_has_no_offers_until_returning_to_a_center(participant):
    from pokesim.runtime.participant import Participant
    emu, snap, candidate = participant
    copies = [candidate, replace(candidate, position=1, level=19, trainer_id=303)]
    inventory = replace(snapshot(copies, party=snap.party), map=113)
    emu.status = lambda: {'game': inventory.to_dict()}
    owner = Participant(SimpleNamespace(store=emu.store, emulator=emu),
                        SimpleNamespace(adventure_id='blue', generation=1))
    assert owner.inventory()['offers'] == []
    inventory = replace(inventory, map=174)
    assert owner.inventory()['offers']
