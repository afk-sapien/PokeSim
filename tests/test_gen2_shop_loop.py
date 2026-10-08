"""A clerk that keeps offering a purchase the wallet cannot cover must not trap the player."""
from types import SimpleNamespace

from pokesim.gen2.menus import Buy
from pokesim.gen2.policy import Policy

GREAT_BALL = 4
BLANK = [' ' * 20] * 18
SHOP = [' ' * 20] * 12 + ['┌' + '─' * 18 + '┐'] + [' ' * 20] * 5


def screen(rows=BLANK, text='', money=50, items=(), script=0):
    data = SimpleNamespace(item_attributes={GREAT_BALL: {'price': 600}}, item_names={GREAT_BALL: 'Great Ball'})
    snapshot = SimpleNamespace(tiles=rows, text=text, money=money, items=list(items), data=data)
    return snapshot, SimpleNamespace(byte=lambda name: script)


def test_buy_stays_in_the_shop_until_the_screen_has_been_clear_for_several_frames():
    buy = Buy(GREAT_BALL, 20, 19)
    frames = [screen(SHOP, 'BUY', 12000, [(GREAT_BALL, 39)]),
              screen(BLANK, '', 12000, [(GREAT_BALL, 39)]),  # the blank frame after "Here you go!"
              screen(SHOP, 'BUY', 12000, [(GREAT_BALL, 39)])]
    assert [buy.step(*frame) for frame in frames] == ['b', 'b', 'b']
    clear = screen(BLANK, '', 12000, [(GREAT_BALL, 39)])
    assert [buy.step(*clear) for _ in range(3)] == ['b', 'b', None]


def test_buy_waits_for_a_running_script_before_leaving():
    buy = Buy(GREAT_BALL, 20, 19)
    assert buy.step(*screen(BLANK, '', 12000, [(GREAT_BALL, 39)], script=1)) == 'b'
    assert buy.step(*screen(BLANK, '', 12000, [(GREAT_BALL, 39)], script=1)) == 'b'
    assert buy.step(*screen(BLANK, '', 12000, [(GREAT_BALL, 39)], script=1)) == 'b'


def test_buy_gives_up_on_a_screen_that_never_clears():
    buy = Buy(GREAT_BALL, 20, 19)
    presses = [buy.step(*screen(SHOP, 'BUY', 12000, [(GREAT_BALL, 39)])) for _ in range(60)]
    assert presses[:40] == ['b'] * 40 and presses[40] is None


def test_buy_never_picks_an_item_the_money_cannot_cover():
    buy = Buy(GREAT_BALL, 20, 39)
    # 50 money buys nothing: back out with B instead of choosing the item again.
    assert buy.step(*screen(SHOP, 'BUY', 50, [(GREAT_BALL, 39)])) == 'b'
    assert buy.phase == 'exit'


def test_quantity_is_clamped_to_what_the_wallet_covers():
    buy = Buy(GREAT_BALL, 20, 0, phase='quantity')
    snapshot, _ = screen(SHOP, '× 1', 1500)
    mem = SimpleNamespace(byte=lambda name: 5 if name == 'wItemQuantityChange' else 0)
    assert buy.step(snapshot, mem) == 'down'  # 1500 pays for 2, not 20, and 5 is too many
    mem = SimpleNamespace(byte=lambda name: 2 if name == 'wItemQuantityChange' else 0)
    assert buy.step(snapshot, mem) == 'a' and buy.phase == 'confirm'


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
