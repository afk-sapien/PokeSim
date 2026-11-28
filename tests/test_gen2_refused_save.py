"""A Gen II gift waits when the live game refuses to save, as Red's does.

The autosave refuses while the bot backs out of a screen no plan owns, while the screen has been
still too long, or while the last read was not valid. The gift then has no checkpoint to stand on.
"""
from pokesim import config
from pokesim.runtime.reward_delivery import PENDING
from test_restart_gifts import gen2_emu, gen2_snapshot, sent, store  # noqa: F401


def refusing(store, data=None):
    emu = gen2_emu(store, data)
    emu._autosave = lambda: None
    return emu


def test_the_gs_ball_waits_for_a_save_it_can_stand_on(store, monkeypatch):  # noqa: F811
    from types import SimpleNamespace
    from pokesim.gen2 import celebi, rewards
    monkeypatch.setattr(config, 'CELEBI_EVENT', True, raising=False)
    monkeypatch.setattr(celebi, 'read_snapshot', lambda *_: gen2_snapshot(set()))
    monkeypatch.setattr(celebi, 'Memory', lambda *_: SimpleNamespace(byte=lambda _: 0))
    monkeypatch.setattr(rewards, 'clone_emulator', lambda _: sent())
    assert celebi.activate(refusing(store, SimpleNamespace(game='crystal'))) is None
    assert store.get(celebi.CLAIM) is None and store.get(PENDING) is None


def test_a_gen2_reward_has_no_source_without_a_save(store):  # noqa: F811
    # The shared delivery then refuses with 'Custom rewards require a verified source checkpoint'.
    from pokesim.gen2 import rewards
    assert rewards.GEN2.metadata(refusing(store), None, 0) is None
