"""A restart resets the Mew, mythical gift and GS Ball markers. None of them can send a second gift.

The first gift survives a restart in two places: an old game's save that the reward barrier still
lets load, and a Pokémon traded back into the new game. Either way the Pokédex owns it, and each
gift checks the Pokédex before its marker.
"""
from types import SimpleNamespace

import pytest

from pokesim import config, rewards
from pokesim.runtime.reward_delivery import BARRIER, PENDING, deliver
from pokesim.store import Store
from pokesim.trade.event import EVENT_KEY
from test_events import snap


class Sent(Exception):
    """Raised where a gift would start, so a test sees that it was about to send one."""


def sent():
    raise Sent


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    yield store
    store.close()


def restart_after_a_gift(store, generation, marker, value):
    store.set(marker, value)
    store.set(BARRIER, 'first-gift')
    store.set('trade_barrier', 'first-trade')
    store.restart(generation, {})
    assert store.get(marker) is None
    # The barriers stay, so a save from before the first gift still cannot load.
    assert store.get(BARRIER) == 'first-gift' and store.get('trade_barrier') == 'first-trade'


@pytest.mark.parametrize(('owned', 'gift'), [({1, 151}, False), ({1}, True)])
def test_a_gen1_restart_sends_mew_only_to_a_game_that_has_none(store, monkeypatch, owned, gift):
    from pokesim import ram
    restart_after_a_gift(store, 1, EVENT_KEY, 'first-mew')
    state = snap(hall_of_fame_count=1, owned=frozenset(owned), box_counts=(0,) * 12)
    monkeypatch.setattr(ram, 'read_snapshot', lambda *_: state)
    emu = SimpleNamespace(store=store, paused=False, manual_mode=False, pb=SimpleNamespace(memory=None),
                          frame=100, _state_bytes=sent)
    if gift:
        with pytest.raises(Sent):
            deliver(emu, mew_event=True)
        return
    assert deliver(emu, mew_event=True) is None
    assert store.get(EVENT_KEY) == {'source': 'observed_ownership'} and store.get(PENDING) is None


def gen2_emu(store, data=None):
    policy = SimpleNamespace(menu=None, collection={})
    return SimpleNamespace(store=store, paused=False, manual_mode=False, preparation=None, policy=policy,
                           pb=SimpleNamespace(memory='live'), data=data, frame=100, _autosave=sent)


def gen2_snapshot(owned, *events):
    return SimpleNamespace(valid=True, started=True, in_battle=False, tiles=[''] * 18, hall_of_fame_count=1,
                           owned=frozenset(owned), box_counts=(0,) * 14, event=lambda name: name in events)


@pytest.mark.parametrize(('owned', 'gift'), [({151}, False), (set(), True)])
def test_a_gen2_restart_sends_the_mythical_gift_only_to_a_game_without_mew(store, monkeypatch, owned, gift):
    from pokesim.gen2 import rewards as gen2_rewards
    restart_after_a_gift(store, 2, gen2_rewards.MYTHICAL, 'first-mew')
    monkeypatch.setattr(config, 'MEW_EVENT', True, raising=False)
    monkeypatch.setattr(config, 'LEAGUE_REWARDS', False, raising=False)
    monkeypatch.setattr(gen2_rewards, 'read_snapshot', lambda *_: gen2_snapshot(owned))
    monkeypatch.setattr(gen2_rewards, 'Memory', lambda *_: SimpleNamespace(byte=lambda _: 0))
    monkeypatch.setattr(gen2_rewards, 'clone_emulator', lambda _: sent())
    emu = gen2_emu(store)
    if gift:
        with pytest.raises(Sent):
            gen2_rewards.deliver(emu)
        return
    assert gen2_rewards.deliver(emu) is None
    assert store.get(gen2_rewards.MYTHICAL) is None and store.get(PENDING) is None
    assert rewards.ledger(store.db)['delivered'] == 0


@pytest.mark.parametrize(('owned', 'events', 'gift'), [
    ({251}, (), False),
    (set(), ('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER',), False),
    (set(), (), True),
])
def test_a_gen2_restart_sends_the_gs_ball_only_to_a_game_without_it_or_celebi(store, monkeypatch, owned, events, gift):
    from pokesim.gen2 import celebi
    restart_after_a_gift(store, 2, celebi.CLAIM, 'first-ball')
    monkeypatch.setattr(config, 'CELEBI_EVENT', True, raising=False)
    monkeypatch.setattr(celebi, 'read_snapshot', lambda *_: gen2_snapshot(owned, *events))
    monkeypatch.setattr(celebi, 'Memory', lambda *_: SimpleNamespace(byte=lambda _: 0))
    emu = gen2_emu(store, SimpleNamespace(game='crystal'))
    if gift:
        with pytest.raises(Sent):
            celebi.activate(emu)
        return
    assert celebi.activate(emu) is None
    assert store.get(celebi.CLAIM) == 'already_available' and store.get(PENDING) is None
