"""The adventure seed and its streams make every bot choice the same in a replay."""
import json
import os
from types import SimpleNamespace

import pytest

from pokesim import config, seeds
from pokesim.gen2.naming import Naming
from pokesim.policies.strategic import StrategicPolicy
from pokesim.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    yield store
    store.close()


def test_the_adventure_seed_is_created_once_and_kept(store, monkeypatch):
    monkeypatch.setattr(config, 'SEED', None)
    first = seeds.adventure_seed(store)
    assert isinstance(first, int) and store.get(seeds.KEY) == first
    assert seeds.adventure_seed(store) == first
    # A restart clears the key, and the new game draws its own.
    store.set(seeds.KEY, None)
    assert seeds.adventure_seed(store) != first


def test_seed_in_the_config_overrides_the_kept_one(store, monkeypatch):
    monkeypatch.setattr(config, 'SEED', 7)
    assert seeds.adventure_seed(store) == 7
    assert store.get(seeds.KEY) is None


def test_a_stream_draws_the_same_numbers_for_the_same_labels():
    draws = [seeds.stream(7, 'reload', 120).random() for _ in range(2)]
    assert draws[0] == draws[1]
    assert seeds.stream(7, 'reload', 121).random() != draws[0]
    assert seeds.stream(8, 'reload', 120).random() != draws[0]
    assert seeds.stream(None, 'name', 1, 0).random() == seeds.stream(None, 'name', 1, 0).random()


def test_reload_idles_are_one_to_180_frames_and_differ_with_the_clock():
    idles = [seeds.reload_idle(7, frames) for frames in range(0, 60_000, 60)]
    assert all(1 <= idle <= seeds.RELOAD_IDLE for idle in idles)
    assert len(set(idles)) > 100
    assert idles == [seeds.reload_idle(7, frames) for frames in range(0, 60_000, 60)]


def test_a_gift_seed_is_one_per_kind_and_championship_count():
    seed = seeds.gift_seed(7, 'mew_event', 1)
    assert len(seed) == 32 and int(seed, 16) >= 0
    assert seeds.gift_seed(7, 'mew_event', 1) == seed
    assert len({seed, seeds.gift_seed(7, 'mew_return', 1), seeds.gift_seed(7, 'mew_event', 2),
                seeds.gift_seed(8, 'mew_event', 1)}) == 4


def test_the_gen1_mew_event_seed_comes_from_the_adventure_seed(monkeypatch):
    from pokesim.policies import collection
    from pokesim.runtime.reward_delivery import select_reward
    monkeypatch.setattr(collection, 'champion', lambda _: True)
    snapshot = SimpleNamespace(owned=frozenset())
    ledger = {'earned': 1, 'delivered': 1, 'observed': 1}
    first = select_reward(snapshot, ledger, False, mew_event=True, seed=7)
    assert first == ('mew_event', None, first[2], seeds.gift_seed(7, 'mew_event', 1))
    assert select_reward(snapshot, ledger, False, mew_event=True, seed=7) == first
    assert select_reward(snapshot, ledger, False, mew_event=True, seed=8)[3] != first[3]


def test_adventure_choices_without_a_seed_are_the_same_every_time():
    first, second = StrategicPolicy(), StrategicPolicy()
    assert (first.fossil, first.collection.eevee_choice, first.collection.dojo_choice) == (
        second.fossil, second.collection.eevee_choice, second.collection.dojo_choice)


def naming_screen(subject):
    snapshot = SimpleNamespace(text='DEL END', player_name='', rival_name='', party=())
    values = {'wNamingScreenType': subject, 'wNamingScreenCurNameLength': 0}
    # A cursor pointer outside work RAM stops the step once the name is chosen.
    mem = SimpleNamespace(byte=values.get, read=lambda *_: bytes(2), raw=lambda *_: bytes(16))
    return snapshot, mem


def test_a_gen2_name_is_the_same_after_a_restart(monkeypatch):
    monkeypatch.setattr(config, 'TRAINER_NAME', '', raising=False)
    monkeypatch.setattr(config, 'RIVAL_NAME', '', raising=False)
    before = Naming(7)
    saved = json.loads(json.dumps(before.state_dict()))
    before.step(*naming_screen(1))
    first = before.target
    restarted = Naming(7)
    restarted.load_state_dict(saved)
    restarted.step(*naming_screen(1))
    assert restarted.target == first
    # The next name draws again, with the first one taken.
    before.step(*naming_screen(2))
    assert before.target != first


def test_the_gen2_policy_generator_is_saved_and_restored():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    from pokesim.gen2.policy import Policy
    data = GameData.load(directory, 'crystal')
    policy = Policy(data, seed=1, starter='cyndaquil')
    policy.rng.random()
    state = json.loads(json.dumps(policy.state_dict()))
    restored = Policy(data, seed=2, starter='cyndaquil')
    restored.load_state_dict(state)
    assert restored.rng.random() == policy.rng.random()
