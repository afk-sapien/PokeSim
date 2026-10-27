"""Every pair of supported games through compatibility, preparation, timeouts and the recorded result.

The coordinator is driven with synthetic participants, so no ROM is needed. Each pair names the
left game first. Mixed pairs go through the Time Capsule.
"""
from dataclasses import asdict, replace
import hashlib
from itertools import product
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pokesim.app.coordinator import Coordinator
from pokesim.app.registry import Registry, identifier
from pokesim.cartridges import by_version
from pokesim.policies.base import PolicyContext
from pokesim.runtime import preparation
from pokesim.store import Store
from pokesim.trade.preferences import identity
from pokecore import timecapsule as core
from shortcut_fakes import PRESS, Recorder
from test_duplicates import snapshot, stored
from test_managed_coordinator import Peer
from test_strategy import mon

VERSIONS = ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal')
GEN1 = ('red', 'blue', 'yellow')
GEN2 = ('gold', 'silver', 'crystal')
PAIRS = list(product(VERSIONS, repeat=2))
MIXED = [pair for pair in PAIRS if by_version(pair[0]).generation != by_version(pair[1]).generation]


def generation(version):
    return by_version(version).generation


def mixed(pair):
    return generation(pair[0]) != generation(pair[1])


def label(pair):
    return '-'.join(pair)


def worker_adapter(pair):
    """The adapter ID the cable worker would publish, routed the way link_worker.run_session routes."""
    if mixed(pair):
        from pokesim.gen2.timecapsule_worker import ADAPTER_ID
    elif generation(pair[0]) == 2:
        from pokesim.gen2.link_worker import ADAPTER_ID
    else:
        from pokesim.interactions.link_worker import ADAPTER_ID
    return ADAPTER_ID


class GamePeer(Peer):
    """A participant that answers like its cartridge generation does."""

    def __init__(self, aid, key, version):
        super().__init__(aid, key)
        self.version = version
        self.generation = generation(version)
        self.capsule_ready = self.generation == 2
        self.offer = {'cartridge_generation': self.generation, 'time_capsule_compatible': True}
        self.stall = False
        self.prepare_error = None

    def request(self, method, path, data=None, timeout=None):
        operation = path.rsplit('/', 1)[-1]
        if operation == 'inventory' and not self.trade_blocked:
            self.calls.append(operation)
            return {'offers': [{'trade_key': self.key, 'dex': self.dex, 'arrived_dex': self.dex, **self.offer}],
                    'owned': self.owned, 'cartridge_generation': self.generation,
                    'time_capsule_ready': self.capsule_ready}
        if operation == 'prepare' and (self.stall or self.prepare_error):
            self.calls.append(operation)
            self.prepared.append(dict(data))
            if self.prepare_error:
                raise RuntimeError(self.prepare_error)
            return {'id': data['id'], 'phase': 'preparing', 'preparation': {'phase': 'travelling'}}
        return super().request(method, path, data, timeout)


class Supervisor:
    def __init__(self, registry, peers):
        self.registry, self.peers = registry, peers
        self.stops = []

    def child(self, aid):
        return self.peers[aid]

    def start(self, aid, recovery=False):
        assert recovery

    def stop(self, aid):
        self.stops.append(aid)
        self.registry.update(aid, state='stopped')


@pytest.fixture
def matrix(tmp_path):
    registry = Registry(tmp_path)
    for version in VERSIONS:
        registry.add_rom(version + '-rom', 'sha-' + version, version)
    peers = {}
    manager = SimpleNamespace(root=tmp_path, registry=registry, supervisor=Supervisor(registry, peers), suspended=False,
                              assets=SimpleNamespace(game_data_dir=tmp_path), maintenance=threading.RLock())
    announced = []
    manager.notifications = SimpleNamespace(trade_completed=lambda row, display: announced.append(row['id']))
    coordinator = Coordinator(manager)
    coordinator.prepare_poll = 0
    cable_calls = []

    def cable(row, plan):
        cable_calls.append(row['id'])
        versions = tuple(registry.adventure(aid)['version'] for aid in row['plan']['participants'])
        return {'status': 'verified', 'schema_version': 1, 'interaction_id': row['id'],
                'attempt_id': row['plan']['attempt_id'], 'adapter_id': worker_adapter(versions),
                'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'participants': {aid: {'adventure_id': aid, 'checkpoint_sha256': 'new-' + aid}
                                 for aid in row['plan']['participants']}}
    coordinator._run_cable = cable

    def pair(left, right):
        games = []
        for index, version in enumerate((left, right)):
            game = registry.create(f'{version.title()} {index}', version + '-rom', {}, identifier())
            registry.update(game['id'], state='running', desired_state='running')
            peers[game['id']] = GamePeer(game['id'], f'{version}-{index}', version)
            games.append(game['id'])
        request = {'left_id': games[0], 'right_id': games[1], 'left_key': f'{left}-0', 'right_key': f'{right}-1',
                   'request_id': identifier()}
        return request, peers[games[0]], peers[games[1]]

    yield SimpleNamespace(coordinator=coordinator, registry=registry, peers=peers, pair=pair,
                          cable_calls=cable_calls, announced=announced)
    coordinator.close()
    registry.close()


# Admission and compatibility.

@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_every_pair_of_supported_games_can_propose_a_trade(matrix, pair):
    request, left, right = matrix.pair(*pair)
    row = matrix.coordinator.propose(request)
    assert row['plan']['participants'] == [left.aid, right.aid]
    assert row['phase'] not in {'aborted', 'completed'}


@pytest.mark.parametrize('pair', MIXED, ids=label)
def test_a_mixed_pair_needs_an_unlocked_time_capsule(matrix, pair):
    request, left, right = matrix.pair(*pair)
    modern = left if left.generation == 2 else right
    modern.capsule_ready = False
    with pytest.raises(ValueError, match='Time Capsule needs an unlocked'):
        matrix.coordinator.propose(request)
    assert matrix.registry.transactions() == []


@pytest.mark.parametrize('pair', MIXED, ids=label)
def test_a_gen2_offer_the_time_capsule_rejects_cannot_go_to_a_gen1_game(matrix, pair):
    request, left, right = matrix.pair(*pair)
    modern = left if left.generation == 2 else right
    modern.offer['time_capsule_compatible'] = False
    with pytest.raises(ValueError, match='Time Capsule needs an unlocked'):
        matrix.coordinator.propose(request)


@pytest.mark.parametrize('pair', MIXED, ids=label)
def test_an_abnormal_gen1_offer_cannot_go_to_a_gen2_game(matrix, pair):
    request, left, right = matrix.pair(*pair)
    classic = left if left.generation == 1 else right
    classic.offer['time_capsule_compatible'] = False
    with pytest.raises(ValueError, match='Time Capsule needs an unlocked'):
        matrix.coordinator.propose(request)


@pytest.mark.parametrize('pair', [pair for pair in PAIRS if not mixed(pair)], ids=label)
def test_a_same_generation_pair_ignores_the_time_capsule(matrix, pair):
    request, left, right = matrix.pair(*pair)
    for peer in (left, right):
        peer.capsule_ready = False
        peer.offer['time_capsule_compatible'] = False
    assert matrix.coordinator.propose(request)['plan']['participants'] == [left.aid, right.aid]


@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_gen2_kadabra_arrives_evolved_only_in_a_gen1_game(pair):
    giver = {'cartridge_generation': generation(pair[0]), 'dex': 64, 'arrived_dex': 64}
    recipient = {'cartridge_generation': generation(pair[1])}
    arrived = Coordinator._offer_for(giver, recipient)['arrived_dex']
    assert arrived == (65 if pair[0] in GEN2 and pair[1] in GEN1 else 64)


@pytest.mark.parametrize('pair', MIXED, ids=label)
def test_a_manual_mixed_trade_names_which_side_the_time_capsule_blocks(pair):
    left = {'cartridge_generation': generation(pair[0]), 'time_capsule_ready': True}
    right = {'cartridge_generation': generation(pair[1]), 'time_capsule_ready': True}
    modern_left = generation(pair[0]) == 2
    johto = {'name': 'Chikorita', 'time_capsule_compatible': False,
             'time_capsule_reason': 'Red, Blue and Yellow only know the first 151 species'}
    kanto = {'name': 'Mew', 'time_capsule_compatible': True}
    give, take = (johto, kanto) if modern_left else (kanto, johto)
    assert not Coordinator._compatible_pair(left, right, give, take)
    assert Coordinator._capsule_reason(left, right, give, take) == (
        'Chikorita cannot go to a Red, Blue or Yellow game. Red, Blue and Yellow only know the first 151 species')
    glitched = {'name': 'Missingno', 'time_capsule_compatible': False, 'time_capsule_reason': 'Its types are abnormal'}
    give, take = (kanto, glitched) if modern_left else (glitched, kanto)
    assert not Coordinator._compatible_pair(left, right, give, take)
    assert Coordinator._capsule_reason(left, right, give, take) == (
        'Missingno cannot go to a Gold, Silver or Crystal game. Its types are abnormal')
    (left if modern_left else right)['time_capsule_ready'] = False
    assert 'cannot use the Time Capsule yet' in Coordinator._capsule_reason(left, right, kanto, kanto)


# What crosses the Time Capsule.

def capsule_mon(species=25, moves=(84, 0, 0, 0), held_item=0, egg=False):
    return SimpleNamespace(species=species, moves=moves, held_item=held_item, egg=egg)


@pytest.mark.parametrize(('member', 'crosses'), [
    (capsule_mon(), True),
    (capsule_mon(species=151), True),
    (capsule_mon(species=152), False),
    (capsule_mon(species=251), False),
    (capsule_mon(moves=(84, 165, 0, 0)), True),
    (capsule_mon(moves=(84, 166, 0, 0)), False),
    (capsule_mon(held_item=core.LEFTOVERS), True),
    (capsule_mon(held_item=core.KINGS_ROCK), True),
    (capsule_mon(held_item=core.FLOWER_MAIL), False),
    (capsule_mon(egg=True), False),
], ids=['pikachu', 'mew', 'chikorita', 'celebi', 'struggle', 'gen2-move', 'leftovers', 'kings-rock', 'mail', 'egg'])
def test_only_kanto_species_with_gen1_moves_and_no_mail_cross_the_time_capsule(member, crosses):
    from pokesim.gen2.timecapsule import compatible
    assert compatible(member, None) is crosses


@pytest.mark.parametrize('item', sorted(core.MAIL_ITEMS))
def test_every_mail_item_stays_behind(item):
    from pokesim.gen2.timecapsule import compatible
    assert not compatible(capsule_mon(held_item=item), None)


@pytest.mark.parametrize(('member', 'reason'), [
    (capsule_mon(egg=True), 'Eggs cannot'),
    (capsule_mon(species=152), 'first 151 species'),
    (capsule_mon(moves=(84, 200, 0, 0)), 'move that does not exist'),
    (capsule_mon(held_item=core.FLOWER_MAIL), 'holds Mail'),
])
def test_a_blocked_gen2_pokemon_explains_why(member, reason):
    from pokesim.gen2.trading import capsule_reason
    data = SimpleNamespace(item_names={core.FLOWER_MAIL: 'FLOWER MAIL', core.LEFTOVERS: 'LEFTOVERS'})
    assert reason in capsule_reason(member, data)


@pytest.fixture(scope='module', params=GEN2)
def gen2_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, request.param)


def test_the_mail_explanation_names_the_same_items_the_time_capsule_refuses(gen2_data):
    from pokesim.gen2.trading import capsule_reason
    for item in range(1, 256):
        member = capsule_mon(held_item=item)
        explained = 'holds Mail' in capsule_reason(member, gen2_data)
        assert explained is core.is_mail(item), (item, gen2_data.item_names.get(item))


def gen1_struct(species, catch_rate, level=30):
    raw = bytearray(44)
    raw[0], raw[3], raw[7], raw[33] = species, level, catch_rate, level
    raw[8:12] = bytes((84, 85, 0, 0))
    raw[27:29] = (0xA5, 0x5A)
    return bytes(raw)


def test_a_gen1_catch_rate_becomes_the_held_item_the_cartridge_gives(gen2_data):
    from pokesim.gen2.timecapsule_conversion import to_gen2
    from pokesim.strategy_data import SPECIES
    pikachu = next(sid for sid, entry in SPECIES.items() if entry['dex'] == 25)
    for rate in range(256):
        row = {'struct': gen1_struct(pikachu, rate), 'nickname': b'', 'trainer': b''}
        arrived = to_gen2(row, gen2_data)['struct']
        assert arrived[0] == 25
        assert arrived[1] == core.held_item_from_catch_rate(rate), rate


def test_pokesim_and_core_convert_a_pokemon_the_same_way_both_directions(gen2_data):
    from pokesim.gen2.timecapsule_conversion import to_gen1, to_gen2
    from pokesim.strategy_data import SPECIES
    gen1_species = {sid: {'dex': entry['dex'], 'stats': entry['stats']} for sid, entry in SPECIES.items()}
    gen2_species = {dex: {'types': entry['types'], 'stats': entry['stats']}
                    for dex, entry in gen2_data.species.items() if 1 <= dex <= 151}
    for sid in sorted(SPECIES):
        if not 1 <= SPECIES[sid]['dex'] <= 151:
            continue
        row = {'struct': gen1_struct(sid, core.BERRY if sid % 2 else 0x19)}
        modern = to_gen2(row, gen2_data)
        assert modern == core.to_gen2(row, gen1_species, gen2_species), SPECIES[sid]['dex']
        assert to_gen1(modern, gen2_data) == core.to_gen1(modern, gen1_species, gen2_species), SPECIES[sid]['dex']


def test_a_gen2_held_item_crosses_to_gen1_as_its_catch_rate(gen2_data):
    from pokesim.gen2.timecapsule_conversion import to_gen1, to_gen2
    from pokesim.strategy_data import SPECIES
    pikachu = next(sid for sid, entry in SPECIES.items() if entry['dex'] == 25)
    modern = to_gen2({'struct': gen1_struct(pikachu, 0)}, gen2_data)
    for item in (core.LEFTOVERS, core.KINGS_ROCK, core.EVERSTONE, core.METAL_COAT):
        held = {'struct': modern['struct'][:1] + bytes([item]) + modern['struct'][2:]}
        classic = to_gen1(held, gen2_data)['struct']
        assert classic[7] == item
        # Back home, the catch rate becomes the item again unless the cartridge maps it to another.
        assert to_gen2({'struct': classic}, gen2_data)['struct'][1] == core.held_item_from_catch_rate(item)


# Preparation requests.

@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_both_sides_are_told_whether_the_trade_uses_the_time_capsule(matrix, pair):
    request, left, right = matrix.pair(*pair)
    matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    for peer, key in ((left, request['left_key']), (right, request['right_key'])):
        assert [sent['time_capsule'] for sent in peer.prepared] == [mixed(pair)]
        assert peer.prepared[0]['selected_key'] == key


# The recorded result.

@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_completed_trade_is_recorded_on_both_sides(matrix, pair):
    request, left, right = matrix.pair(*pair)
    left.outgoing = {'struct': 'aa', 'nickname': 'a1', 'trainer': 'a2'}
    right.outgoing = {'struct': 'bb', 'nickname': 'b1', 'trainer': 'b2'}
    staged = {}
    for peer in (left, right):
        original = peer.request

        def request_with_record(method, path, data=None, timeout=None, original=original, peer=peer):
            if path.endswith('/stage'):
                staged[peer.aid] = data
            return original(method, path, data, timeout)
        peer.request = request_with_record
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert (row['phase'], row['decision']) == ('completed', 'COMMIT')
    assert row['result']['adapter_id'] == worker_adapter(pair)
    for peer, other in ((left, right), (right, left)):
        record = peer.records[row['id']]
        assert (record['phase'], record['decision']) == ('released', 'COMMIT')
        assert record['staged']['checkpoint_sha256'] == 'new-' + peer.aid
        assert staged[peer.aid]['incoming'] == other.outgoing
        assert [call for call in peer.calls if call in {'stage', 'apply', 'release', 'abort'}] == ['stage', 'apply', 'release']
        assert not matrix.coordinator.reserved(peer.aid)
    assert matrix.cable_calls == [row['id']]
    assert matrix.announced == [row['id']]
    assert set(row['result']['display']) == {left.aid, right.aid}


@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_manifest_from_another_kind_of_cable_session_cannot_commit(matrix, pair):
    adapters = {worker_adapter(other) for other in PAIRS} - {worker_adapter(pair)}
    assert len(adapters) == 2
    original = matrix.coordinator._run_cable
    for adapter in sorted(adapters):
        request, left, right = matrix.pair(*pair)
        matrix.coordinator._run_cable = lambda row, plan: {**original(row, plan), 'adapter_id': adapter}
        row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
        assert (row['phase'], row['decision']) == ('aborted', 'ABORT')
        assert 'does not match this exact paired attempt' in row['error']
        for peer in (left, right):
            assert 'stage' not in peer.calls and 'apply' not in peer.calls
            assert peer.records[row['id']]['phase'] == 'aborted'


# Stalls, pauses and timeouts. Both sides always hear the abort and nothing is applied.

def assert_both_aborted(matrix, row, left, right):
    assert (row['phase'], row['decision']) == ('aborted', 'ABORT')
    for peer in (left, right):
        assert 'abort' in peer.calls
        assert 'apply' not in peer.calls and 'stage' not in peer.calls
        assert not matrix.coordinator.reserved(peer.aid)
        assert matrix.registry.adventure(peer.aid)['state'] == 'running'


@pytest.mark.parametrize('stalled', ['left', 'right'])
@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_side_that_never_finishes_preparing_aborts_both(matrix, pair, stalled):
    """Regression: a Crystal and Red trade timed out with Red paused, and the banner could not say which
    game never got ready or that it took too long."""
    request, left, right = matrix.pair(*pair)
    late = left if stalled == 'left' else right
    late.stall = True
    matrix.coordinator.prepare_timeout = 0
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert row['error'] == f'The adventures did not reach a safe Cable Club rendezvous in time (adventure {late.aid})'
    assert matrix.cable_calls == []
    name = matrix.registry.adventure(late.aid)['name']
    assert matrix.coordinator._failure_reason(row) == (
        f'{name} ({late.version.title()}) took too long to reach the Cable Club and prepare its Pokémon.')


def test_both_sides_missing_the_rendezvous_name_neither(matrix):
    request, left, right = matrix.pair('crystal', 'red')
    left.stall = right.stall = True
    matrix.coordinator.prepare_timeout = 0
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert row['error'] == 'The adventures did not reach a safe Cable Club rendezvous in time'
    assert matrix.coordinator._failure_reason(row) == (
        'An adventure took too long to reach the Cable Club and prepare its Pokémon.')


@pytest.mark.parametrize('version', GEN2)
def test_the_gen2_preparation_deadline_reads_as_taking_too_long(matrix, version):
    """Regression: Gen II's own deadline fell through to the reason for an unknown failure."""
    request, left, right = matrix.pair(version, 'red')
    left.prepare_error = 'The trainer did not reach the Cable Club before the preparation deadline'
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert matrix.coordinator._failure_reason(row) == (
        f'{version.title()} 0 ({version.title()}) took too long to reach the Cable Club and prepare its Pokémon.')


@pytest.mark.parametrize('paused', ['left', 'right'])
@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_paused_side_aborts_both_and_is_named(matrix, pair, paused):
    request, left, right = matrix.pair(*pair)
    held = left if paused == 'left' else right
    held.prepare_error = 'Resume autonomous play before preparing a trade'
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert row['error'] == f'Resume autonomous play before preparing a trade (adventure {held.aid})'
    assert matrix.cable_calls == []
    name = matrix.registry.adventure(held.aid)['name']
    assert matrix.coordinator._failure_reason(row) == (
        f'{name} ({held.version.title()}) was paused or under manual control, so it could not prepare its Pokémon.')


@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_cable_session_past_its_deadline_aborts_both(matrix, pair):
    request, left, right = matrix.pair(*pair)

    def late(row, plan):
        matrix.cable_calls.append(row['id'])
        raise TimeoutError('Cable Club session exceeded its deadline')
    matrix.coordinator._run_cable = late
    row = matrix.coordinator.execute(matrix.coordinator.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert row['error'] == 'Cable Club session exceeded its deadline'
    assert [call for call in left.calls if call == 'prepare'] == ['prepare']


class Silent:
    """A cable worker that starts and then never prints or exits."""

    def __init__(self, command, **kwargs):
        self.env = kwargs['env']
        self.stdin = Mock()
        self.stdout = SimpleNamespace(readline=lambda size: '')
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


@pytest.mark.parametrize('pair', PAIRS, ids=label)
def test_a_silent_cable_worker_is_stopped_at_the_session_deadline(matrix, pair, monkeypatch):
    from pokesim.app import coordinator as module
    from pokesim.game_data import VARIANT_ENV
    request, left, right = matrix.pair(*pair)
    started = []

    def popen(command, **kwargs):
        started.append(Silent(command, **kwargs))
        return started[-1]
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    c = matrix.coordinator
    c.session_timeout = 0
    c._run_cable = Coordinator._run_cable.__get__(c)
    row = c.execute(c.propose(request)['id'])
    assert_both_aborted(matrix, row, left, right)
    assert row['error'] == 'Cable Club session exceeded its deadline'
    assert len(started) == 1 and started[0].terminated
    yellow = all(version == 'yellow' for version in pair if version in GEN1) and any(v in GEN1 for v in pair)
    assert started[0].env[VARIANT_ENV] == ('yellow' if yellow else 'red')


# Gen I preparation: PC boxes, making room and the HM reserve.

@pytest.fixture
def gen1(tmp_path, monkeypatch):
    state = {}
    store = Store(tmp_path)
    emu = SimpleNamespace(store=store, paused=False, manual_mode=False, frame=0, input_epoch=0,
                          preparation=None, policy=Mock(), pb=SimpleNamespace(memory=bytearray(65536)))
    monkeypatch.setattr(preparation, 'read_snapshot', lambda *args: state['snap'])

    def start(candidate, party=(mon(trainer_id=202, dvs=(3,) * 5),), **changes):
        # Preparation begins in the overworld and then reaches the PC.
        state['snap'] = replace(snapshot([candidate], party=party), map=89, x=13, y=4, **changes)
        preparation.begin(emu, identity(asdict(candidate)), 'transaction-1')
        return emu.preparation, Recorder(emu.preparation.shortcut), replace(state['snap'], textbox=True)
    yield SimpleNamespace(emu=emu, start=start)
    store.close()


def storage_menu(index=0):
    from test_strategy import menu
    return menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'},
                (1, 1 + 2 * index), index=index, top=(1, 1))


def step(controller, snap, memory):
    return controller.step(PolicyContext(snap, 0, 0, memory))[0]


def hm_party(*moves):
    """A full party whose lead is strongest. Each reserve knows the given move."""
    return (mon(trainer_id=200, level=60, dvs=(3,) * 5, moves=(33,)),) + tuple(
        mon(trainer_id=201 + i, level=20 + i, dvs=(3,) * 5, moves=(33, move)) for i, move in enumerate(moves))


@pytest.mark.parametrize('box', range(12), ids=lambda box: f'box{box + 1}')
def test_gen1_withdraws_its_offer_from_every_pc_box(gen1, box):
    candidate = stored(0, trainer_id=101, box=box)
    active = (box + 1) % 12
    controller, recorder, snap = gen1.start(candidate, active_box=active,
                                            box_counts=tuple(1 if i == box else 0 for i in range(12)))
    assert step(controller, snap, storage_menu()) == PRESS
    assert controller.operation == 'change_box'
    assert recorder.last.kind == 'change_box' and recorder.last.box == box
    recorder.finish()
    opened = replace(snap, active_box=box)
    assert step(controller, opened, storage_menu()) == PRESS
    assert controller.operation == 'withdraw'
    assert recorder.last.kind == 'withdraw_pokemon' and recorder.last.position == candidate.position


@pytest.mark.parametrize('box', [10, 11], ids=['box11', 'box12'])
def test_gen1_menu_fallback_reaches_the_last_pc_boxes(gen1, box):
    from pokesim.screen import W_TILEMAP
    from test_strategy import menu
    candidate = stored(0, trainer_id=101, box=box)
    controller, recorder, snap = gen1.start(candidate, active_box=0)
    recorder.refuse.add('change_box')
    assert step(controller, snap, storage_menu()).button == 'down'
    assert controller.target_box == box
    for index, button in ((0, 'down'), (box - 1, 'down'), (box, 'a')):
        memory = menu({1: '             BOX 1', 2: '             BOX 2', 12: '             BOX12'},
                      (12, 1 + index), index=index, top=(12, 1))
        memory[W_TILEMAP + 20 + 17] = 0xF7
        memory[W_TILEMAP + 12 * 20 + 16] = 0xF7
        memory[W_TILEMAP + 12 * 20 + 17] = 0xF8
        assert preparation.Screen(memory).kind(snap) == 'change_box'
        assert step(controller, snap, memory).button == button


@pytest.mark.parametrize('free', [1, 10, 11], ids=['box2', 'box11', 'box12'])
def test_gen1_deposits_into_the_next_free_box_to_make_room(gen1, free):
    candidate = stored(0, trainer_id=101, box=3)
    counts = tuple(5 if i == free else 20 for i in range(12))
    party = hm_party(33, 33, 33, 33, 33)
    controller, recorder, snap = gen1.start(candidate, party=party, active_box=0,
                                            box_counts=counts, boxed_pokemon=((153, 20),) * 20)
    assert step(controller, snap, storage_menu(3)) == PRESS
    assert recorder.last.kind == 'change_box' and recorder.last.box == free
    recorder.finish()
    opened = replace(snap, active_box=free, boxed_pokemon=((153, 20),) * 5)
    assert step(controller, opened, storage_menu()) == PRESS
    assert controller.operation == 'deposit'
    assert recorder.last.kind == 'deposit_pokemon' and recorder.last.slot == 1


def test_gen1_full_pc_with_nothing_to_release_fails_and_says_why(gen1):
    candidate = stored(0, trainer_id=101, box=11)
    controller, _, snap = gen1.start(candidate, party=hm_party(33, 33, 33, 33, 33),
                                     box_counts=(20,) * 12, boxed_pokemon=((153, 20),) * 20)
    assert controller.step(PolicyContext(snap, 0, 0, storage_menu()))[0].button is None
    assert 'Every PC box is full' in gen1.emu.store.get(preparation.KEY)['error']


@pytest.mark.parametrize(('moves', 'slot'), [
    ((15, 15, 19, 57, 70), 1),      # Two know Cut, so one may go.
    ((15, 19, 57, 70, 70), 4),      # Two know Strength.
    ((148, 15, 19, 57, 148), 1),    # Two know Flash.
    ((15, 19, 57, 70, 33), 5),      # The one without a field move.
])
def test_gen1_hm_reserve_keeps_one_user_of_every_field_move(gen1, moves, slot):
    candidate = stored(0, trainer_id=101)
    controller, recorder, snap = gen1.start(candidate, party=hm_party(*moves))
    assert step(controller, snap, storage_menu(1)) == PRESS
    assert recorder.last.kind == 'deposit_pokemon' and recorder.last.slot == slot
    party = snap.party[:slot] + snap.party[slot + 1:]
    for move in {15, 19, 57, 70, 148} & {m for member in snap.party for m in member.moves}:
        assert any(move in member.moves for member in party)


def test_gen1_party_of_unique_field_move_users_cannot_make_room(gen1):
    candidate = stored(0, trainer_id=101)
    controller, _, snap = gen1.start(candidate, party=hm_party(15, 19, 57, 70, 148))
    assert controller.step(PolicyContext(snap, 0, 0, storage_menu(1)))[0].button is None
    assert 'No safe unprotected reserve' in gen1.emu.store.get(preparation.KEY)['error']


# Gen II preparation: PC boxes, making room and the HM reserve.

def gen2_member(*moves, box=None, position=0, species=143, level=30):
    return SimpleNamespace(species=species, level=level, egg=False, moves=moves, held_item=0, box=box,
                           position=position, hp=10, status=0, trainer_id=7, dvs=(1, 2, 3, 4), nick='')


@pytest.mark.parametrize('box', [0, 10, 12, 13], ids=lambda box: f'box{box + 1}')
def test_gen2_make_room_opens_the_first_box_with_space(box):
    from pokesim.gen2.menus import ChangeBox
    from pokesim.gen2.preparation import Preparation
    counts = tuple(5 if i == box else 20 for i in range(14))
    prep = Preparation(SimpleNamespace(policy=None), {})
    assert prep.make_room(SimpleNamespace(box_counts=counts, active_box=0)) == ChangeBox(box)


@pytest.mark.parametrize('box', [11, 13], ids=['box12', 'box14'])
def test_gen2_make_room_releases_a_spare_from_a_high_box(box):
    from pokesim.gen2.menus import ChangeBox, Release
    from pokesim.gen2.preparation import Preparation
    spare = gen2_member(33, box=box, position=19)
    policy = SimpleNamespace(trade_spare=lambda snap, protect, wished: spare)
    prep = Preparation(SimpleNamespace(policy=policy), {'protect': ['kept'], 'wished': [25]})
    full = SimpleNamespace(box_counts=(20,) * 14, active_box=0)
    assert prep.make_room(full) == ChangeBox(box)
    assert prep.make_room(SimpleNamespace(box_counts=(20,) * 14, active_box=box)) == Release(
        box, 19, [143, 7, [1, 2, 3, 4]])


def test_gen2_full_pc_with_nothing_to_release_says_why():
    from pokesim.gen2.preparation import FULL, Preparation
    prep = Preparation(SimpleNamespace(policy=SimpleNamespace(trade_spare=lambda *args: None)), {})
    with pytest.raises(ValueError, match=FULL):
        prep.make_room(SimpleNamespace(box_counts=(20,) * 14, active_box=0))


@pytest.mark.parametrize('version', VERSIONS)
def test_every_game_can_change_to_its_last_pc_box(version):
    from pokecore.shortcuts import ChangeBox as CoreChangeBox
    last = 11 if generation(version) == 1 else 13
    assert CoreChangeBox(last, version=version).box == last
    with pytest.raises(ValueError):
        CoreChangeBox(last + 1, version=version)


@pytest.mark.parametrize(('moves', 'expected'), [
    ((15, 15, 19, 57, 70), [1, 2]),
    ((250, 127, 250, 127, 33), [1, 2, 3, 4, 5]),
    ((15, 19, 57, 70, 148), []),
    ((127, 19, 57, 70, 148), []),
])
def test_gen2_hm_reserve_keeps_one_user_of_every_field_move(moves, expected):
    from pokesim.gen2.preparation import reserves
    party = (gen2_member(33),) + tuple(gen2_member(33, move) for move in moves)
    assert reserves(party) == expected


# A participant that was paused for the trade plays on after the abort.

def gen1_participant(store, emu):
    from pokesim.runtime.participant import Participant
    return Participant(SimpleNamespace(store=store, emulator=emu), SimpleNamespace(adventure_id='a' * 32))


def gen2_participant(store, emu):
    from pokesim.gen2.trading import Participant
    return Participant(SimpleNamespace(store=store, emulator=emu), SimpleNamespace(adventure_id='b' * 32))


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('phase', ['travelling', 'ready'])
def test_an_abort_hands_a_paused_game_back_to_autonomous_play(tmp_path, version, phase):
    from pokesim.runtime.participant import PREFIX
    store = Store(tmp_path)
    try:
        loads = []
        emu = SimpleNamespace(store=store, paused=True, manual_mode=False, preparation=object(), input_epoch=0,
                              policy=SimpleNamespace(on_restore=Mock(), collection={}),
                              _load_state_file=loads.append, _autosave=Mock())
        if generation(version) == 2:
            emu.generation = 2
        tid = identifier()
        store.set(PREFIX + tid, {'id': tid, 'phase': 'preparing' if phase == 'travelling' else 'prepared',
                                 'decision': None, 'plan_digest': 'plan', 'selected_key': 'key',
                                 'was_paused': False, 'was_manual': False,
                                 **({'source_name': 'source.state'} if phase == 'ready' else {})})
        store.set(preparation.KEY, {'id': tid, 'phase': phase, 'trade_key': 'key'})
        if phase == 'ready':
            store.set('trade_hold', {'id': tid, 'source': 'source.state', 'phase': 'prepared'})
        owner = (gen2_participant if generation(version) == 2 else gen1_participant)(store, emu)
        record = owner.abort({'id': tid})
        assert (record['phase'], record['decision']) == ('aborted', 'ABORT')
        assert not emu.paused and not emu.manual_mode and emu.preparation is None
        assert store.get('trade_hold') is None and store.get(preparation.KEY) is None
        assert len(loads) == (phase == 'ready')
        assert emu.policy.on_restore.called
        assert owner.abort({'id': tid})['phase'] == 'aborted'
    finally:
        store.close()
