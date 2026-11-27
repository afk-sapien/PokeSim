"""A wild Ditto that used Transform shows the copied species and DVs, and a throw still catches a Ditto
with its own DVs, so every catch rule judges the Ditto."""
import os
from types import SimpleNamespace

import pytest

from battle_fakes import reading
from pokesim.gen2.data import GameData

RAIKOU, ENTEI, DITTO = 243, 244, 132


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def policy_for(data):
    from pokesim.gen2.policy import Policy
    policy = Policy(data)
    policy.battle_task = lambda task, snapshot, mem: SimpleNamespace(button=task.key())
    policy.needed_move = lambda snapshot: 0
    policy.remedy = lambda *args, **kwargs: False
    return policy


def meeting(data, owned, balls, hp=60):
    # The lead is a Raikou, so the Ditto's Transform writes 243 where the snapshot reads the wild species.
    lead = SimpleNamespace(species=RAIKOU, level=50, moves=(84, 0, 0, 0), pp=(30, 0, 0, 0), held_item=0,
                           stats=(160, 100, 90, 130, 110, 100), hp=160, max_hp=160, status=0, egg=False)
    return SimpleNamespace(party=(lead,), stored=(), text='FIGHT', tiles=(), map=data.map_ids['ROUTE_34'], in_battle=1,
                           enemy_species=RAIKOU, enemy_level=20, enemy_hp=hp, enemy_max_hp=60, owned=set(owned),
                           can_catch=True, badges=65535, money=10000, pockets={'balls': balls},
                           box_counts=(0,) * 14, active_box=0,
                           roamers=({'species': ENTEI, 'map': next(iter(data.maps))},),
                           enemy_shiny=False, bug_contest=False, event=lambda name: False)


def transformed_memory():
    flags = {'wEnemySubStatus5': 0x08}  # SUBSTATUS_TRANSFORMED
    return SimpleNamespace(byte=lambda name: flags.get(name, 0), read=lambda name, size: bytes(size))


def test_a_transformed_ditto_is_not_thrown_the_master_ball(real_data):
    policy = policy_for(real_data)
    master, ultra = real_data.items['MASTER_BALL'], real_data.items['ULTRA_BALL']
    snapshot = meeting(real_data, owned={RAIKOU}, balls=[(master, 1), (ultra, 20)], hp=3)
    mem = transformed_memory()
    reading(policy, mem)
    assert policy.reads.enemy.transformed
    assert policy.ball_labels(snapshot)[0] != 'MASTER BALL'
    assert policy.battle(snapshot, mem).button != ('Throw', master)


def test_the_keep_rule_judges_the_ditto_by_its_own_dvs(real_data, monkeypatch):
    from pokesim.gen2 import postgame, release
    policy = policy_for(real_data)
    policy.capture_move = lambda *args, **kwargs: None
    seen = []
    monkeypatch.setattr(release, 'keeps_another',
                        lambda policy, snapshot, dex, level=5, dvs=None: seen.append((dex, dvs)) and False)
    monkeypatch.setattr(postgame, 'quality_species', lambda policy: DITTO)
    snapshot = meeting(real_data, owned={RAIKOU, DITTO}, balls=[(real_data.items['ULTRA_BALL'], 20)])
    mem = transformed_memory()
    reading(policy, mem)
    # The shown bytes are the copied lead's, and wEnemyBackupDVs holds what a caught Ditto keeps.
    policy.reads.enemy.dvs = (0, 0, 0, 0, 0)
    policy.reads.enemy.shown_dvs = b'\xff\xff'
    policy.battle(snapshot, mem)
    assert seen and seen[0] == (DITTO, (0, 0, 0, 0, 0))
