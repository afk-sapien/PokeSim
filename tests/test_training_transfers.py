import json
from dataclasses import replace

from pokesim.policies.base import PolicyContext
from pokesim.policies.collection import Collection
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import MAPS
from test_collection import sid, state
from test_strategy import menu, mon


def project():
    return {'method': 'train', 'parent': sid(75), 'family': [sid(75)], 'box': 4,
            'initial_level': 43, 'target_level': 50, 'key': 'train:39:50'}


def test_pc_withdrawal_cannot_complete_training_using_the_previous_slot_level():
    policy = StrategicPolicy(7)
    policy.collection.project = project()
    policy.collection.remaining = 72000
    transient = state(frame=100, map=MAPS['INDIGO_PLATEAU_LOBBY'], x=15, y=8,
                      party=(mon(species=sid(75), nick='TRUFFLE', level=100, experience=71833),))
    memory = menu({0: ' WITHDRAW', 2: ' DEPOSIT', 4: ' RELEASE', 6: ' CHANGE BOX'}, (0, 0))
    policy.step(PolicyContext(transient, 0, 0, memory))
    assert policy.collection.project is not None
    assert 'gains' not in policy.collection.project
    assert not policy.collection.director.completed


def test_transfer_wait_survives_restore_and_then_counts_real_training():
    c = Collection()
    c.project = project()
    c.remaining = 72000
    transient = state(party=(mon(species=sid(75), nick='TRUFFLE', level=100, experience=71833),))
    c.observe(transient, training_ready=False)
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    actual = replace(transient, frame=100, party=(replace(transient.party[0], level=43),))
    restored.observe(actual)
    assert restored.project['gains'] == {'experience': 0, 'levels': 0}
    restored.observe(replace(actual, frame=220, in_battle=1,
                             party=(replace(actual.party[0], level=44, experience=80000),)))
    assert restored.project['gains'] == {'experience': 8167, 'levels': 1}
    restored.observe(replace(actual, frame=340, in_battle=1,
                             party=(replace(actual.party[0], level=50, experience=117360),)))
    assert restored.project is None
    assert restored.director.completed == {'training': 1}
    assert restored.director.outcomes[-1]['gains']['levels'] == 7


def test_party_disappearance_during_transfer_does_not_count_as_training_progress():
    c = Collection()
    c.project = project()
    c.remaining = 72000
    s = state(party=(mon(species=sid(75), level=43, experience=71833),))
    c.observe(s)
    c.observe(replace(s, frame=120, party=()), training_ready=False)
    assert c.idle_frames == 120
    assert c.project['gains'] == {'experience': 0, 'levels': 0}


def test_withdrawing_a_reserve_starts_a_fresh_idle_window_only_once():
    c = Collection()
    c.project = project()
    c.remaining = 72000
    absent = state(map=MAPS['INDIGO_PLATEAU_LOBBY'])
    for frame in range(0, 6601, 120):
        c.observe(replace(absent, frame=frame))
    actual = replace(absent, frame=6720,
                     party=(mon(species=sid(75), level=43, experience=71833),))
    c.observe(actual, training_ready=False)
    assert c.idle_frames == 6720
    assert 'initial_experience' not in c.project
    c.observe(replace(actual, frame=6840))
    assert c.idle_frames == 120
    assert c.remaining == 72000 - 120
    restored = Collection()
    restored.load(json.loads(json.dumps(c.state_dict())))
    restored.observe(replace(actual, frame=6840))
    for frame in range(6960, 22081, 120):
        snapshot = replace(actual, frame=frame, party=() if frame % 240 else actual.party)
        restored.observe(snapshot, training_ready=bool(snapshot.party))
    assert restored.project is None
    assert restored.director.outcomes[-1]['status'] == 'deferred'
    assert restored.director.outcomes[-1]['gains'] == {'experience': 0, 'levels': 0}
