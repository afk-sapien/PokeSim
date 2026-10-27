"""An automatic pick whose offer vanishes before its exchange is left out, not retried every pass."""
import pytest

from pokesim.app import coordinator as module

from test_managed_coordinator import setup  # noqa: F401  (fixture)


class Vanishing:
    """Offers its Pokémon while candidates are scored, then not when the exchange reads it again."""
    def __init__(self, peer):
        self.peer, self.reads = peer, 0
        self.request = peer.request

    def __call__(self, method, path, data=None, timeout=None):
        result = self.request(method, path, data, timeout)
        if path.endswith('/inventory'):
            self.reads += 1
            if self.reads == 2:
                result = {**result, 'offers': []}
        return result


def test_a_vanished_offer_is_skipped_quietly_and_then_left_out(setup, monkeypatch, caplog):  # noqa: F811
    c, left = setup.coordinator, setup.data['left_id']
    peer = setup.peers[left]
    monkeypatch.setattr(peer, 'request', Vanishing(peer))
    with caplog.at_level('INFO', logger=module.log.name):
        assert c.schedule_once() is None
    assert setup.registry.transactions() == []
    assert (left, peer.key) in c.ineligible
    assert left in caplog.text and peer.key in caplog.text
    # The next pass no longer picks it, so nothing else is proposed and nothing fails.
    def propose(data):
        raise Picked(data)
    monkeypatch.setattr(c, 'propose', propose)
    assert c.schedule_once() is None
    # Once the wait is over the Pokémon can be picked again.
    c.ineligible = {side: 0 for side in c.ineligible}
    with pytest.raises(Picked) as picked:
        c.schedule_once()
    data = picked.value.args[0]
    assert peer.key == data['left_key' if data['left_id'] == left else 'right_key']


class Picked(Exception):
    pass


def test_a_hand_picked_trade_still_reports_the_missing_offer(setup):  # noqa: F811
    with pytest.raises(module.Ineligible, match='no longer eligible') as error:
        setup.coordinator.propose({**setup.data, 'left_key': 'locked-or-protected'})
    assert (error.value.aid, error.value.key) == (setup.data['left_id'], 'locked-or-protected')
