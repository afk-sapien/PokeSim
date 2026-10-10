"""A clerk that keeps offering a purchase the wallet cannot cover must not trap the player."""
from types import SimpleNamespace

from pokesim.gen2.menus import Buy
from pokesim.gen2.policy import Policy

GREAT_BALL = 4


def screen(money=50, items=()):
    data = SimpleNamespace(game='gold', item_attributes={GREAT_BALL: {'price': 600}}, item_names={GREAT_BALL: 'Great Ball'})
    return SimpleNamespace(money=money, items=list(items), data=data)


def test_buy_never_picks_an_item_the_money_cannot_cover():
    # 50 money buys nothing, so no Core purchase starts and the task backs out of the shop.
    assert Buy(GREAT_BALL, 20, 39).build(screen(50, [(GREAT_BALL, 39)])) is None


def test_quantity_is_clamped_to_what_the_wallet_and_pack_cover():
    assert Buy(GREAT_BALL, 20, 0).build(screen(1500)).amount == 2
    assert Buy(GREAT_BALL, 20, 97).build(screen(12000, [(GREAT_BALL, 97)])).amount == 2


def test_buy_is_finished_once_the_pack_count_rises():
    assert not Buy(GREAT_BALL, 20, 19).finished(screen(12000, [(GREAT_BALL, 19)]))
    assert Buy(GREAT_BALL, 20, 19).finished(screen(12000, [(GREAT_BALL, 39)]))


def conversation_stub():
    return SimpleNamespace(talk_key=None, talk_frames=0, shopping=(GREAT_BALL, 20), shop_location=(1030, 'Clerk', GREAT_BALL),
                           interaction='buy_balls', TALK_STALL_FRAMES=Policy.TALK_STALL_FRAMES,
                           TALK_FAIL_FRAMES=Policy.TALK_FAIL_FRAMES, fail=lambda reason: setattr(stub_failures, 'last', reason))


stub_failures = SimpleNamespace(last=None)


def talking(money=50, x=3):
    return SimpleNamespace(map=1030, map_name='Ecruteak Mart', x=x, y=3, money=money, items=[(GREAT_BALL, 39)])


def test_a_conversation_that_changes_nothing_drops_the_errand_backs_out_and_then_fails():
    policy, snapshot = conversation_stub(), talking()
    stub_failures.last = None
    results = [Policy.talk_progress(policy, snapshot) for _ in range(Policy.TALK_FAIL_FRAMES + 1)]
    assert not any(results[:Policy.TALK_STALL_FRAMES])
    assert all(results[Policy.TALK_STALL_FRAMES:Policy.TALK_FAIL_FRAMES - 1])
    assert policy.shopping is None and policy.shop_location is None and policy.interaction is None
    assert 'Ecruteak Mart' in stub_failures.last


def test_a_conversation_that_keeps_changing_things_is_never_a_stall():
    policy = conversation_stub()
    for step in range(300):
        assert not Policy.talk_progress(policy, talking(money=50 + step))
    assert policy.shopping is not None
