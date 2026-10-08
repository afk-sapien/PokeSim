"""Game Corner tasks must always leave the machine and must fail when they stop making progress."""
from dataclasses import asdict
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.gen2 import gamecorner
from pokesim.gen2.gamecorner import Coins, Prize, Slots

REELS = {
    # Three reel layouts are drawn in the top twelve rows. They are kana glyphs, never box text.
    'golem': ['ガザジ ヂ ヂザジ ガ ガザジ'] * 12,
    'chansey': ['ビブヅデヅデビブ  ビブヅデ'] * 12,
    'plain': [''] * 12,
}
RUNNING = SimpleNamespace(byte=lambda name: 255)
IDLE = SimpleNamespace(byte=lambda name: 0)


def screen(box=(), reels='golem', coins=9899, money=0, owned=()):
    rows = list(REELS[reels]) + [''] * 6
    if box:
        rows[12] = '┌' + '─' * 18 + '┐'
        for index, line in enumerate(box[:4]):
            rows[13 + index] = '│' + line.ljust(18)[:18] + '│'
        rows[17] = '└' + '─' * 18 + '┘'
    return SimpleNamespace(coins=coins, money=money, owned=set(owned), tiles=rows, text='\n'.join(rows))


def question(cursor, coins=9899, reels='golem'):
    rows = list(REELS[reels]) + [''] * 6
    rows[12] = '┌' + '─' * 13 + '┬────┐'
    rows[13] = '│' + ' ' * 13 + '│' + ('▶' if cursor == 'YES' else ' ') + 'YES │'
    rows[14] = '│Play again?   │    │'
    rows[15] = '│' + ' ' * 13 + '│' + ('▶' if cursor == 'NO' else ' ') + 'NO  │'
    rows[16] = '└' + '─' * 13 + '┴────┘'
    return SimpleNamespace(coins=coins, money=0, owned=set(), tiles=rows, text='\n'.join(rows))


class Machine:
    """The Game Corner slot machine as observed on the cartridge: only some phases listen to B."""

    def __init__(self, coins, phase, wins=0, reels='golem'):
        self.coins, self.phase, self.wins, self.reels, self.cursor, self.rounds = coins, phase, wins, reels, 'YES', 0

    @property
    def open(self):
        return self.phase != 'closed'

    def snapshot(self):
        if self.phase == 'closed':
            return screen(coins=self.coins)
        if self.phase == 'bet':
            return screen(['Bet how many', 'coins?', '▶ 3', '  2', '  1'], self.reels, self.coins)
        if self.phase in {'reel1', 'reel2', 'reel3', 'flash'}:
            return screen(['Start!'], self.reels, self.coins)
        if self.phase == 'result':
            return screen(['lined up!', 'Won 10 coins!', '▼'] if self.win() else ['Darn!'], self.reels, self.coins)
        return question(self.cursor, self.coins, self.reels)

    def win(self):
        return self.wins and self.rounds % self.wins == 0

    def press(self, button):
        order = ['reel1', 'reel2', 'reel3', 'flash']
        if self.phase == 'bet':
            if button == 'a':
                self.coins, self.phase = max(0, self.coins - 3), 'reel1'
                self.rounds += 1
            elif button == 'b':
                self.phase = 'closed'
        elif self.phase in order:
            if button == 'a' and self.phase != 'flash':
                self.phase = order[order.index(self.phase) + 1]
            elif self.phase == 'flash':
                self.phase = 'result'
                self.coins = min(9999, self.coins + (10 if self.win() else 0))
        elif self.phase == 'result':
            if button in {'a', 'b'}:
                self.phase, self.cursor = 'again', 'YES'
        elif self.phase == 'again':
            if button in {'up', 'down'}:
                self.cursor = 'NO' if button == 'down' else 'YES'
            elif button == 'b' or button == 'a' and self.cursor == 'NO':
                self.phase = 'closed'
            elif button == 'a':
                self.phase = 'bet'


def play(machine, menu, limit=400):
    for count in range(limit):
        button = menu.step(machine.snapshot(), RUNNING if machine.open else IDLE)
        if button is None:
            return count
        machine.press(button)
        if machine.phase == 'flash':
            machine.press('a')
    raise AssertionError(f'still in {machine.phase} after {limit} steps')


@pytest.mark.parametrize('reels', REELS)
@pytest.mark.parametrize('phase', ['bet', 'reel1', 'reel2', 'reel3', 'flash', 'result', 'again'])
def test_slots_leave_from_every_phase_when_credits_fall_below_the_floor(phase, reels):
    machine = Machine(9899, phase, reels=reels)
    play(machine, Slots(9999))
    assert machine.phase == 'closed'


@pytest.mark.parametrize('phase', ['bet', 'reel1', 'reel2', 'reel3', 'flash', 'result', 'again'])
def test_slots_leave_from_every_phase_once_the_prize_budget_is_reached(phase):
    machine = Machine(9999, phase)
    play(machine, Slots(9999))
    assert machine.phase == 'closed'


def test_slots_stop_the_reels_instead_of_pressing_b_on_the_start_box():
    """The recorded stall: 9899 credits, reels spinning on Start!, and only B was sent."""
    menu = Slots(9999, exiting=True)
    for phase in ('reel1', 'reel2', 'reel3'):
        assert menu.step(Machine(9899, phase).snapshot(), RUNNING) == 'a'


@pytest.mark.parametrize('coins,exiting', [(9899, True), (9900, False), (9998, False), (9999, True), (0, True)])
def test_slots_exit_condition_respects_the_coin_case_cap_and_floor(coins, exiting):
    menu = Slots(9999)
    menu.step(Machine(coins, 'reel1').snapshot(), RUNNING)
    assert menu.exiting is exiting


def test_slots_never_wait_for_more_than_the_coin_case_holds():
    menu = Slots(10500)
    menu.step(Machine(9999, 'reel1').snapshot(), RUNNING)
    assert menu.exiting


def test_slots_keep_playing_until_the_floor_is_crossed():
    machine = Machine(9930, 'bet')
    steps = play(machine, Slots(9999), limit=1000)
    assert machine.phase == 'closed' and machine.coins < 9900 and steps > 40


def test_slots_reach_the_budget_through_wins():
    machine = Machine(9970, 'bet', wins=1)
    play(machine, Slots(9999), limit=1000)
    assert machine.phase == 'closed' and machine.coins >= 9999


def test_slots_answer_the_play_again_question_by_intent():
    keep = Slots(9999)
    assert keep.step(question('YES', 9950), RUNNING) == 'a'
    assert keep.step(question('NO', 9950), RUNNING) == 'up'
    leave = Slots(9999, exiting=True)
    assert leave.step(question('YES', 9899), RUNNING) == 'down'
    assert leave.step(question('NO', 9899), RUNNING) == 'a'


def test_slots_back_out_of_the_bet_menu_and_wait_for_the_script_to_end():
    menu = Slots(9999, exiting=True)
    assert menu.step(Machine(9899, 'bet').snapshot(), RUNNING) == 'b'
    assert menu.step(screen(['Darn! Ran out', 'of coins!'], coins=0), RUNNING) == 'b'
    assert menu.step(screen(coins=0), RUNNING) == 'b'
    assert menu.step(screen(coins=0), IDLE) is None


def test_slots_fail_when_nothing_changes_so_the_stuck_path_takes_over():
    menu = Slots(9999)
    still = Machine(9950, 'reel1').snapshot()
    for _ in range(gamecorner.SLOT_IDLE_STEPS + 1):
        assert menu.step(still, RUNNING) == 'a'
    assert menu.step(still, RUNNING) is None
    assert 'Slots' in menu.failure and menu.step(still, RUNNING) is None


def test_slots_total_step_limit_fails_even_when_the_screen_keeps_changing():
    menu = Slots(9999)
    for index in range(gamecorner.SLOT_STEPS):
        assert menu.step(screen(['Start!'], coins=9950 + index % 40), RUNNING) == 'a'
    assert menu.step(screen(['Start!'], coins=9950), RUNNING) is None
    assert menu.failure


def test_game_corner_tasks_survive_a_policy_reload_with_their_counters():
    menu = Slots(9999)
    menu.step(Machine(9950, 'reel1').snapshot(), RUNNING)
    assert Slots(**asdict(menu)) == menu
    assert Coins(**asdict(Coins(500))) == Coins(500)
    assert Prize(**asdict(Prize(137))) == Prize(137)
    # A checkpoint written before the counters existed still loads.
    assert Slots(**{'target': 9999, 'exiting': True}).failure == ''


def test_coin_vendor_fails_when_the_screen_never_changes():
    rows = [''] * 18
    rows[12], rows[13] = '┌', '│Hello'
    snapshot = SimpleNamespace(coins=0, money=20000, text='\n'.join(rows), tiles=rows)
    menu = Coins(5555)
    for _ in range(gamecorner.IDLE_STEPS + 1):
        menu.step(snapshot, None)
    assert menu.step(snapshot, None) is None and menu.failure


def test_prize_counter_fails_when_the_screen_never_changes():
    rows = [''] * 18
    snapshot = SimpleNamespace(owned=set(), text='Not enough coins', tiles=rows)
    menu = Prize(137)
    for _ in range(gamecorner.IDLE_STEPS + 1):
        menu.step(snapshot, None)
    assert menu.step(snapshot, None) is None and menu.failure


def test_naming_screen_closes_after_too_many_presses():
    from pokesim.gen2.naming import MAX_STEPS, Naming
    naming = Naming(1)
    screen_ = SimpleNamespace(text='DEL END', player_name='', rival_name='', party=())
    naming.steps = MAX_STEPS
    buttons = {naming.step(screen_, None) for _ in range(4)}
    assert buttons == {'a', 'start'}


def test_policy_hands_a_failed_slot_task_to_the_stuck_path(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    policy.menu = Slots(9999)
    still = Machine(9950, 'reel1').snapshot()
    results = [policy.menu_step(still, RUNNING) for _ in range(gamecorner.SLOT_IDLE_STEPS + 2)]
    assert results[-2] == 'a' and results[-1] is None
    assert policy.menu is None and policy.take_failure()
    assert list(policy.rescue)[:3] == ['b', 'b', 'b']


def test_policy_does_not_cut_a_long_healthy_slot_session_short(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, starter='cyndaquil')
    policy.menu = Slots(9999)
    for index in range(policy.MENU_STEP_LIMIT + 200):
        assert policy.menu_step(screen(['Start!'], coins=9950 + index % 40), RUNNING) == 'a'
    assert policy.take_failure() is None


@pytest.fixture(scope='module')
def real_data():
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'silver')


def test_real_cartridge_slot_machine_leaves_a_spinning_machine(real_data):
    """Replay a local savestate of the stall: 9899 credits, reels spinning, exiting already true.

    Savestates of the cartridge are never committed. Set GEN2_CARTRIDGE_DIR and GEN2_SLOTS_STATE (a
    Silver savestate taken at a slot machine) to run it.
    """
    cartridges, state = os.environ.get('GEN2_CARTRIDGE_DIR'), os.environ.get('GEN2_SLOTS_STATE')
    if not cartridges or not state:
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_SLOTS_STATE to replay a real slot machine')
    from pokesim.gen2.core import boot, lock_clock
    from pokesim.gen2.ram import Memory, read_snapshot
    pb = boot(str(Path(cartridges) / 'silver.gbc'), sound=False)
    try:
        pb.set_emulation_speed(0)
        lock_clock(pb, True)
        with open(state, 'rb') as source:
            pb.load_state(source)
        mem, menu = Memory(pb.memory, real_data), Slots(9999, exiting=True)
        for _ in range(600):
            snapshot = read_snapshot(pb.memory, real_data, 0)
            button = menu.step(snapshot, mem)
            if button is None:
                break
            pb.button_press(button)
            pb.tick(8, True)
            pb.button_release(button)
            pb.tick(28, True)
        else:
            pytest.fail('the machine was never left')
        assert not menu.failure
    finally:
        pb.stop(save=False)
