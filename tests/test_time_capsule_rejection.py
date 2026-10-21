"""Gold, Silver and Crystal reject a Red, Blue or Yellow Pokémon whose stored types do not match
its species ("appears to be abnormal"), then cancel the trade. PokeSim refuses such a Pokémon
before the Cable Club, stops a session as soon as the game shows the message, and stops picking
a Pokémon whose automatic trades keep failing the same way.
"""
import time
from types import SimpleNamespace

import pytest

from pokesim.app.coordinator import (FAILURE_BACKOFF_SECONDS, NO_PARTY_ROOM, PC_FULL, SET_ASIDE, WHOLE_GAME,
                                     Coordinator, failure_backoff)
from pokesim.app.registry import identifier
from pokesim.interactions.cable_metadata import ABNORMAL
from pokesim.ram import _decode_box
from pokesim.runtime.participant import capsule_types_reason, manual_rows

from test_managed_coordinator import setup  # noqa: F401  (fixture)
from test_trade_builder import built, make_crystal  # noqa: F401  (fixture)

NIDOQUEEN = 0x10  # Gen I internal index; Poison/Ground is (3, 4)


def box_record(types):
    struct = bytes([NIDOQUEEN, 0, 100, 40, 0, *types, 120, 33, 10, 0, 0, 0x12, 0x34, 0, 0x30, 0])
    struct += bytes(10) + bytes([0xAB, 0xCD]) + bytes([35, 35, 0, 0])
    return struct, bytes([0x8D, 0x88, 0x83, 0x8E, 0x50]) + bytes(6)


def test_box_records_keep_their_stored_types():
    mon, = _decode_box(0, *box_record((4, 7)))
    assert mon.types == (4, 7)
    assert mon.species == NIDOQUEEN and mon.level == 40


def test_mismatched_stored_types_are_named_as_the_reason():
    # The live RUSTAUDIT: a Nidoqueen whose record says Ground/Bug.
    reason = capsule_types_reason({'species': NIDOQUEEN, 'types': (4, 7)})
    assert 'Nidoqueen' in reason and 'abnormal' in reason
    assert capsule_types_reason({'species': NIDOQUEEN, 'types': (3, 4)}) == ''
    # Nothing to compare is not a reason to refuse.
    assert capsule_types_reason({'species': NIDOQUEEN}) == ''
    assert capsule_types_reason({'species': 0, 'types': (1, 1)}) == ''


def test_manual_rows_mark_a_classic_pokemon_the_time_capsule_rejects():
    payload = {'party': [], 'storage': {'pokemon': [
        {'trade_key': 'a-1', 'species': NIDOQUEEN, 'types': (4, 7), 'box': 1, 'position': 1},
        {'trade_key': 'b-1', 'species': NIDOQUEEN, 'types': (3, 4), 'box': 1, 'position': 2}]}}
    bad, good = manual_rows(payload, 1)
    # A Red, Blue or Yellow partner does not check types, so the row is not blocked outright.
    assert bad['blocked'] == '' and bad['time_capsule_compatible'] is False
    assert 'abnormal' in bad['time_capsule_reason']
    assert good['time_capsule_compatible'] is True and good['time_capsule_reason'] == ''
    assert 'time_capsule_compatible' not in manual_rows(payload, 2)[0]


def test_planner_refuses_a_rejected_classic_pokemon_up_front():
    old = {'cartridge_generation': 1}
    modern = {'cartridge_generation': 2, 'time_capsule_ready': True}
    take = {'time_capsule_compatible': True, 'cartridge_generation': 2}
    give = {'nick': 'RUSTAUDIT', 'time_capsule_compatible': False,
            'time_capsule_reason': capsule_types_reason({'species': NIDOQUEEN, 'types': (4, 7)})}
    assert not Coordinator._compatible_pair(old, modern, give, take)
    assert not Coordinator._compatible_pair(modern, old, take, give)
    assert Coordinator._compatible_pair(old, modern, {**give, 'time_capsule_compatible': True}, take)
    # Older workers send no flag for classic offers. They still trade.
    assert Coordinator._compatible_pair(old, modern, {}, take)
    # Between two classic games the types are never checked.
    assert Coordinator._compatible_pair(old, old, give, give)
    reason = Coordinator._capsule_reason(old, modern, give, take)
    assert reason.startswith('RUSTAUDIT cannot go to a Gold, Silver or Crystal game.') and 'Nidoqueen' in reason


def test_trade_builder_greys_out_crystal_for_a_rejected_classic_pokemon(built):  # noqa: F811
    service, left, right = built.manager.builder, built.data['left_id'], built.data['right_id']
    make_crystal(built.peers[right])
    assert service.targets(left, '0')['adventures'][0]['available'] is True
    built.peers[left].pokemon[0].update(time_capsule_compatible=False, time_capsule_reason='It looks abnormal')
    row = service.targets(left, '0')['adventures'][0]
    assert row['available'] is False
    assert 'cannot go to a Gold, Silver or Crystal game' in row['reason'] and 'It looks abnormal' in row['reason']


def test_abnormal_failure_has_a_plain_reason():
    row = {'plan': {'kind': 'trade'}, 'error': f'Cable Club session failed: Cable session failed: {ABNORMAL}'}
    reason = Coordinator._generic_failure_reason(row)
    assert 'abnormal' in reason and 'kept their Pokémon' in reason


def row(when, error='Cable session failed: Time Capsule exhausted its controller step budget',
        left='y' * 32, left_key='467ee8db-29', right='s' * 32, right_key=None, phase='aborted', decision='ABORT'):
    return {'updated_at': when, 'phase': phase, 'decision': decision, 'error': error,
            'plan': {'left_id': left, 'right_id': right, 'left_key': left_key,
                     'right_key': right_key or identifier() + '-1'}}


def test_backoff_starts_after_the_second_identical_failure_and_doubles():
    now = 10_000
    key = ('y' * 32, '467ee8db')
    assert failure_backoff([row(now - 10)], now) == {}
    # The partner changes every time, as it did live. Only the repeated Pokémon waits.
    backed = failure_backoff([row(now - 400), row(now - 10)], now)
    assert backed == {key: now - 10 + FAILURE_BACKOFF_SECONDS}
    assert failure_backoff([row(now - 800), row(now - 400), row(now - 10)], now)[key] == now - 10 + 2 * FAILURE_BACKOFF_SECONDS
    # Sixteen failures wait a day at most, and the wait ends.
    many = [row(now - 360 * index) for index in range(16)]
    assert failure_backoff(many, now)[key] == now + 86400
    assert failure_backoff(many, now + 86401) == {}


def test_backoff_counts_only_the_latest_run_of_one_error():
    now = 10_000
    key = ('y' * 32, '467ee8db')
    assert failure_backoff([row(now - 30), row(now - 20, error='Something else'), row(now - 10)], now) == {}
    assert failure_backoff([row(now - 30), row(now - 20, phase='completed', decision='COMMIT'), row(now - 10)], now) == {}
    benign = [row(now - 30), row(now - 20, error='Cancelled by the owner'), row(now - 15, error=SET_ASIDE), row(now - 10)]
    assert key in failure_backoff(benign, now)
    # Transaction ids inside the message do not make two failures differ.
    ids = [row(now - 20, error=f'Failed ({identifier()})'), row(now - 10, error=f'Failed ({identifier()})')]
    assert key in failure_backoff(ids, now)


def test_scheduler_leaves_out_a_pokemon_whose_trades_keep_failing(setup, monkeypatch):  # noqa: F811
    c = setup.coordinator
    error = 'Cable Club session failed: Cable session failed: Time Capsule exhausted its controller step budget'
    for _ in range(2):
        tx = c.propose({**setup.data, 'request_id': identifier()})
        setup.registry.update_transaction(tx['id'], phase='aborted', decision='ABORT', error=error)
    real = time.time
    # Past the five minute cooldown that used to be the only limit.
    monkeypatch.setattr(time, 'time', lambda: real() + 400)
    assert c.schedule_once() is None
    assert setup.cable_calls == []
    attention = c.status()['attention']
    assert 'automatic trading leaves this Pokémon out until' in attention['message']
    assert 'will try again' not in attention['message']
    # Once the wait is over the Pokémon is offered again.
    monkeypatch.setattr(time, 'time', lambda: real() + 400 + FAILURE_BACKOFF_SECONDS)
    assert c.schedule_once()['phase'] == 'completed'


def test_a_full_pc_backs_off_the_whole_game_across_different_pokemon():
    # Live, Blue offered Caterpie, Marowak and Goldeen in turn and each trade found its PC full.
    now = 10_000
    blue = 'b' * 32
    error = f'{PC_FULL} and no unprotected spare duplicate can make room for this trade (adventure {blue})'
    rows = [row(now - 300 * index, error=error, left=blue, left_key=identifier() + '-1') for index in range(3)]
    backed = failure_backoff(rows, now)
    assert backed[(blue, WHOLE_GAME)] == now + 2 * FAILURE_BACKOFF_SECONDS
    assert all(side[1] == WHOLE_GAME for side in backed)
    offers = {'offers': [{'trade_key': identifier() + '-1'}]}
    assert Coordinator._auto_offers(blue, offers, set(backed))[1]['offers'] == []
    assert Coordinator._auto_offers('s' * 32, offers, set(backed))[1]['offers'] == offers['offers']
    # A completed trade by that game ends the wait.
    done = row(now - 5, left=blue, phase='completed', decision='COMMIT')
    assert (blue, WHOLE_GAME) not in failure_backoff([*rows, done], now)


@pytest.mark.parametrize('refusal', NO_PARTY_ROOM)
def test_a_party_that_cannot_make_room_backs_off_the_whole_game(refusal):
    # Live, Yellow's party was the starter, four lone HM holders and one Pokémon kept for training,
    # and each trade into it failed with a different boxed Pokémon.
    now = 10_000
    yellow = '7' * 32
    error = f'{refusal} for this trade (adventure {yellow})'
    rows = [row(now - 300 * index, error=error, left=yellow, left_key=identifier() + '-1') for index in range(3)]
    backed = failure_backoff(rows, now)
    assert backed[(yellow, WHOLE_GAME)] == now + 2 * FAILURE_BACKOFF_SECONDS
    assert Coordinator._auto_offers(yellow, {'offers': [{'trade_key': identifier() + '-1'}]}, set(backed))[1]['offers'] == []
