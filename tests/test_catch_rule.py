"""Every path that throws a ball at an owned species asks the PC's one catch rule (pcvalue.verdict)."""
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pokesim import pcvalue
from pokesim.policies.battle import W_ENEMY_MON, choose_battle, useful_capture
from pokesim.policies.collection import Collection
from pokesim.policies.strategic import StrategicPolicy
from pokesim.runtime.participant import Participant
from pokesim.screen import Screen
from test_capture_diversity import collection, sid
from test_level100_priority import individual, postgame
from test_strategy import menu, mon


@pytest.fixture
def refuse(monkeypatch):
    """Make the PC refuse every new copy, so a path that still catches has skipped verdict."""
    def use():
        monkeypatch.setattr(pcvalue, 'verdict', lambda *args, **kwargs: pcvalue.Worth(False, 'Spare'))
    return use


def wild(dvs=b'\xff\xff'):
    mem = bytearray(0x10000)
    mem[W_ENEMY_MON + 12:W_ENEMY_MON + 14] = dvs
    return mem


def test_gen1_incidental_catch_asks_verdict(refuse):
    policy, state, mem = StrategicPolicy(7), collection(stored_pokemon=()), wild()
    enemy = mon(species=sid(67), types=(1, 1), level=41, hp=1, moves=(), pp=())
    keeps = policy._keeps(state, sid(67), mem)
    assert useful_capture(state, sid(67), 41, keeps=keeps)
    assert choose_battle(state, state.party[0], enemy, 0, keeps=keeps).kind == 'item'
    refuse()
    assert not useful_capture(state, sid(67), 41, keeps=keeps)
    assert choose_battle(state, state.party[0], enemy, 0, keeps=keeps).kind != 'item'


@pytest.mark.parametrize('kind', ['dv_hunt', 'repeat', 'returned'])
def test_gen1_hunts_and_returned_legendaries_ask_verdict(refuse, kind):
    c = Collection()
    species = sid(150) if kind == 'returned' else sid(10)
    c.project = {'species': species, 'method': 'grass', 'repeat': True, 'dv_hunt': kind == 'dv_hunt', 'map': 51}
    c.returned_legendaries = {150} if kind == 'returned' else set()
    s = postgame(party=(individual(100, 1), replace(individual(5, 2), species=species)), in_battle=1)
    assert c.repeat_target(species, 51, s, (15,) * 5) == species
    refuse()
    assert c.repeat_target(species, 51, s, (15,) * 5) is None


def test_gen1_safari_catch_asks_verdict(refuse):
    policy = StrategicPolicy(7)
    state = collection(stored_pokemon=(), enemy_species=sid(67), enemy_level=41)
    memory = menu({12: 'BALL', 14: 'ROCK'}, (1, 12), top=(1, 12))
    assert policy._dispatch(state, Screen(memory), 'safari', memory)[0].button == 'a'
    refuse()
    assert policy._dispatch(state, Screen(memory), 'safari', memory)[0].button == 'right'


def test_an_incoming_trade_asks_verdict(refuse):
    policy = SimpleNamespace(pc_rated=lambda snapshot, extra=(): pcvalue.rate(list(extra)))
    game = SimpleNamespace(emu=SimpleNamespace(policy=policy, snapshot=SimpleNamespace(owned={16})))
    assert Participant.would_keep(game, {'dex': 16, 'level': 5, 'dvs': [15] * 5})['keep']
    refuse()
    assert not Participant.would_keep(game, {'dex': 16, 'level': 5, 'dvs': [15] * 5})['keep']


@pytest.fixture(scope='module')
def real_data():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    return GameData.load(directory, 'crystal')


@pytest.mark.parametrize('reason', ['requested', 'returned'])
def test_gen2_battle_catch_of_an_owned_species_asks_verdict(refuse, real_data, reason):
    from pokesim.gen2.policy import Policy
    from pokesim.gen2.release import keeps_another
    policy = Policy(real_data)
    policy.battle_task = lambda task, snapshot, mem: SimpleNamespace(button=task.key())
    policy.needed_move = lambda snapshot: 0
    policy.capture_move = lambda *args: None
    policy.remedy = lambda *args, **kwargs: False
    if reason == 'requested':
        policy.collection['prerequisites'] = [157]
    else:
        policy.returned = {157}
    snapshot = SimpleNamespace(party=(), stored=(), text='FIGHT', tiles=(), map=real_data.map_ids['ROUTE_36'],
        in_battle=1, enemy_species=157, owned={157}, can_catch=True, badges=65535, money=10000,
        pockets={'balls': [(real_data.items['POKE_BALL'], 20)]})
    mem = SimpleNamespace(byte=lambda name: 0, read=lambda name, size: b'\xff' * size)
    throw = ('Throw', real_data.items['POKE_BALL'])
    assert keeps_another(policy, snapshot, 157, dvs=(15,) * 5)
    assert policy.battle(snapshot, mem).button == throw
    refuse()
    assert not keeps_another(policy, snapshot, 157, dvs=(15,) * 5)
    assert policy.battle(snapshot, mem).button != throw
