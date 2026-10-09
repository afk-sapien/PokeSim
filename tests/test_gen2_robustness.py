"""Nickname and menu-word collisions, stuck recovery and trade preparation edge cases."""
import os
from collections import deque
from types import SimpleNamespace

import pytest

from pokesim import config
from pokesim.gen2.data import GameData
from pokesim.gen2.screens import mask_hud, mask_roster
from pokesim.nicknames import MENU_WORDS, name_pool, validate_parts
from pokesim.textmatch import ScreenText, has_word

# Words the Gen 2 policy, menus and Gen 1 screen classifiers search for. A mon nicknamed with
# any of them (or containing one) must never change which screen the bot thinks it sees.
KEYWORDS = (
    'CANCEL', 'QUIT', 'USE', 'TYPE', 'FIGHT', 'PACK', 'RUN', 'PKMN', 'SWITCH', 'STATS', 'SAVE', 'DEL', 'END',
    'YES', 'NO', 'ITEM', 'ABLE', 'TOSS', 'GIVE', 'TAKE', 'BUY', 'SELL', 'LEVEL', 'GEAR', 'NAME', 'GAME',
    'FORGET', 'FRESH', 'SODA', 'LEMONADE', 'RELEASED', 'HEAL', 'TECHNIQUE', 'PROTOTYPE', 'MOSQUITO',
    'TROUSERBAT', 'FIEND', 'CANCELLER', 'BALL', 'TURN OFF', 'MOVE', 'POKE',
)


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


def mon(**extra):
    base = dict(species=156, level=25, egg=False, moves=(33, 43, 52, 0), pp=(30, 30, 20, 0), hp=90, max_hp=90, status=0,
                stats=(90, 60, 50, 70, 70, 60))
    base.update(extra)
    return SimpleNamespace(**base)


def screen(rows, **extra):
    """Mimic read_snapshot: the HUD name fields are blanked before the policy sees the tilemap."""
    rows = mask_hud(tuple(row.ljust(20)[:20] for row in rows))
    base = dict(text=ScreenText('\n'.join(rows)), tiles=rows, party=[mon()], in_battle=2, enemy_species=132,
                enemy_level=10, enemy_hp=30, enemy_max_hp=30, badges=0, money=500, owned=set(), can_catch=True,
                pockets={'balls': [], 'key': []}, map=0, stored=[], items=(), event_flags=bytes(64))
    base.update(extra)
    return SimpleNamespace(**base)


def memory(**values):
    return SimpleNamespace(byte=lambda name: values.get(name, 0))


def action_of(policy, snapshot, **values):
    # A Core battle shortcut is reported by what it asks for, since the fake memory has no RAM to drive it.
    policy.battle_task = lambda task, snapshot, mem: SimpleNamespace(button=task.key(), hold=0, gap=0)
    action = policy.battle(snapshot, memory(**values))
    return action.button, action.hold, action.gap


# Battle HUD layouts captured from the Crystal ROM, with the nickname slot left open.
def fight_menu(nick):
    return [' DITTO       グゾ ボ ご ', '     ぃ10     ゲダ   ざ ', '             ゴヂ   じ ',
            ' ·ぁぁぁぁぁぁぁぁぉ  ザヅ  がず ', '             ジデバ ぎぜ ', '            ガズドビ ぐぞ ',
            '  ぢ べポ      ギゼ ブ げだ ', f'  づ ぼぱ @  {nick}', '  で  ぴ        100♂  ',
            '  どばパぷ              ', '   びピぺ     349/351” ', '   ぶプぽ # ぅ        ぇ ',
            '┌───────┌──────────┐', '│       │          │', '│       │▶FIGHT    │', '│       │          │',
            '│       │ PACK  RUN│', '└───────└──────────┘']


def move_menu(nick):
    rows = fight_menu(nick)
    rows[12:] = ['┌──────────────────┐', '│▶TACKLE   │TYPE/  │', '│ GROWL    │NORMAL │', '│ -        │ 30/ 30│',
                 '│ -        │       │', '└──────────────────┘']
    return rows


def party_menu(nick):
    rows = [''] * 18
    rows[1:12:2] = [f'▶  {nick:<10}349/351', '   MOPCHIEF  112/112', '   MOPTHIEF  110/110',
                    '   BROOMCEO   39/ 39', '   BROOMWITCH 96/ 96', '   MILKJURY   49/ 49']
    rows[2:12:2] = ['        100', '        ぃ41', '        ぃ37', '        ぃ18', '        ぃ28']
    rows[13] = ' CANCEL'
    rows[14:] = ['┌──────────────────┐', '│Choose a POKéMON. │', '│                  │', '└──────────────────┘']
    return rows


def which_screen(nick):
    rows = party_menu(nick)
    rows[14:] = ['┌──────────────────┐', '│Which   ?         │', '└──────────────────┘', '']
    return rows


def pack_quit(nick):
    return fight_menu(nick)[:12] + ['┌────────┬─────────┐', '│▶USE    │         │', '│ QUIT   │         │',
                                   '│        │         │', '│        │         │', '└────────┴─────────┘']


def dialogue(nick):
    rows = fight_menu(nick)
    rows[12:] = ['┌──────────────────┐', '│Shoot! It was so  │', '│                  │',
                 '│close too!        │', '└─────────────────▼┘', '']
    return rows


LAYOUTS = (fight_menu, move_menu, party_menu, which_screen, pack_quit, dialogue)


def decision(policy, layout, nick, **values):
    return action_of(policy, screen(layout(nick)), **values)


@pytest.mark.parametrize('layout', LAYOUTS)
def test_menu_words_as_nicknames_never_change_the_battle_decision(real_data, layout):
    from pokesim.gen2.policy import Policy
    from pokesim.nicknames import POKEMON_NAMES
    names = sorted({*KEYWORDS, *POKEMON_NAMES, *name_pool()[:200]})
    neutral = decision(Policy(real_data, seed=1, starter='cyndaquil'), layout, 'ZZZZ')
    wrong = {}
    for nick in names:
        got = decision(Policy(real_data, seed=1, starter='cyndaquil'), layout, nick[:10])
        if got != neutral:
            wrong[nick] = got
    assert not wrong, f'{layout.__name__} expected {neutral}, differing nicknames {wrong}'


def test_cancel_nickname_on_the_fight_menu_is_not_the_party_menu(real_data):
    from pokesim.gen2.policy import Policy
    button, *_ = decision(Policy(real_data, seed=1, starter='cyndaquil'), fight_menu, 'CANCEL')
    assert button != 'b'


def test_prototype_nickname_does_not_skip_the_fight_menu(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    assert decision(policy, fight_menu, 'PROTOTYPE') == decision(policy, fight_menu, 'ZZZZ')


def test_mosquito_nickname_is_not_the_quit_item_menu(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    assert decision(policy, which_screen, 'MOSQUITO') == decision(policy, which_screen, 'ZZZZ')


def test_real_crystal_hang_screens_are_read_correctly(real_data):
    """The captured hang frames from the Crystal ROM now classify as the plain menus they are."""
    rows = fight_menu('CANCEL')
    masked = mask_hud(tuple(rows))
    assert 'CANCEL' not in '\n'.join(masked)
    assert '349/351' in '\n'.join(masked)
    roster = mask_roster(tuple(which_screen('MOSQUITO')))
    assert 'MOSQUITO' not in '\n'.join(roster)
    assert 'CANCEL' in '\n'.join(roster)


def test_whole_word_search_ignores_embedded_keywords():
    text = ScreenText('PROTOTYPE\nMOSQUITO\nTROUSERBAT\nFIEND\nCANCEL')
    assert 'TYPE' not in text and 'QUIT' not in text and 'USE' not in text and 'END' not in text
    assert 'CANCEL' in text
    assert 'TYPE/' in ScreenText('TYPE/NORMAL')
    assert has_word('SURF here', 'SURF') and not has_word('SURFING', 'SURF')
    assert has_word('349/351', '/')


def test_hud_masking_keeps_hp_and_menu_frames():
    rows = fight_menu('CANCEL')
    masked = mask_hud(tuple(rows))
    assert masked[10] == rows[10] and masked[12:] == tuple(rows[12:])
    assert 'DITTO' not in masked[0] and 'CANCEL' not in masked[7]


def test_party_roster_is_not_mistaken_for_the_hud():
    rows = tuple(row.ljust(20) for row in party_menu('KEEPER'))
    assert mask_hud(rows) == rows
    assert 'KEEPER' not in '\n'.join(mask_roster(rows))


@pytest.mark.parametrize('word', sorted(MENU_WORDS))
def test_generated_names_never_equal_a_menu_word(word):
    assert word not in name_pool()
    assert word not in name_pool(('A',), ('B',))
    assert word not in name_pool(full_names=(word,))
    if len(word) <= 10:
        with pytest.raises(ValueError, match='menu word'):
            validate_parts({'nickname_prefixes': [], 'nickname_suffixes': [], 'nickname_names': [word]})


def test_default_pool_names_are_whole_word_safe_for_every_keyword():
    for name in name_pool():
        assert name not in MENU_WORDS
        text = ScreenText(name)
        for keyword in ('CANCEL', 'QUIT', 'FIGHT', 'PACK', 'SAVE', 'USE', 'YES'):
            assert keyword not in text, (name, keyword)


# Gen 1 classifiers

def test_gen1_vending_machine_needs_the_real_drink_labels():
    from pokesim.screen import Screen
    from test_events import snap
    from test_strategy import menu
    shown = Screen(menu({4: ' FRESH WATER  200', 6: ' SODA POP  300', 8: ' LEMONADE  350'}, (1, 5), top=(1, 4)))
    assert shown.kind(snap()) == 'vending'
    lookalike = Screen(menu({1: 'FRESH', 3: 'SODA', 5: 'LEMONADE', 8: 'RED', 9: '20/ 20'}, (1, 5), top=(1, 4)))
    assert lookalike.kind(snap()) != 'vending'


def test_gen1_released_nickname_does_not_abort_trade_preparation():
    from pokesim.screen import Screen
    from test_screen import fake_mem
    assert 'RELEASED' not in Screen(fake_mem({4: 'PRERELEASED', 6: 'RELEASEDX'})).text
    assert 'RELEASED' in Screen(fake_mem({4: 'RELEASED!'})).text


def test_gen1_pp_prompt_and_forget_prompt_remain_distinct():
    from pokesim.screen import Screen
    from test_champion_shop import shopper
    from test_strategy import menu
    s = shopper(textbox=True)
    pp = menu({8: '      SURF', 14: ' Raise PP of which', 16: ' technique'}, (5, 8), top=(5, 7))
    forget = menu({8: '      SURF', 14: ' Which move should', 16: ' be forgotten'}, (5, 8), top=(5, 7))
    assert Screen(pp).kind(s) == 'item_moves'
    assert Screen(forget).kind(s) == 'learn_move'
    nickname = menu({8: '      SURF', 14: ' PPUPPER of which', 16: ' PPUP'}, (5, 8), top=(5, 7))
    assert Screen(nickname).kind(s) != 'item_moves'


# Recovery

def test_policy_recovery_drops_plans_and_presses_back_out_buttons(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.menu = object()
    policy.recover(1)
    assert policy.menu is None
    assert list(policy.rescue) == ['b', 'b', 'b']
    policy.recover(2)
    assert len(policy.rescue) == 24 and set(policy.rescue) <= {'up', 'down', 'left', 'right', 'a', 'b'}
    again = Policy(real_data, seed=1, starter='cyndaquil')
    again.recoveries = 1
    again.recover(2)
    assert again.rescue == policy.rescue


def test_rescue_buttons_are_played_before_the_normal_plan(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    policy.recover(1)
    snapshot = screen(['Huh?'] * 18, started=True, valid=True, in_battle=0)
    pressed = []
    for _ in range(3):
        pressed.append(policy.step(snapshot, memory()).button)
    assert pressed == ['b', 'b', 'b']
    assert policy.recoveries == 1


@pytest.mark.parametrize('name,limit', [('Teach', 'MENU_STEP_LIMIT'), ('Radio', 'MENU_STEP_LIMITS')])
def test_menu_tasks_give_up_after_their_step_limit(real_data, name, limit):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    ran = []
    menu = type(name, (), {'step': lambda self, snapshot, mem: ran.append(1) or 'press'})()
    policy.menu = menu
    cap = policy.MENU_STEP_LIMITS.get(name, policy.MENU_STEP_LIMIT)
    for _ in range(cap):
        assert policy.menu_step(None, None) == 'press'
    assert policy.menu_step(None, None) is None
    assert policy.menu is None
    assert 'made no progress' in policy.take_failure()
    assert policy.take_failure() is None
    assert len(ran) == cap


def test_every_menu_task_has_a_step_limit():
    import inspect
    from pokesim.gen2 import menus
    for name in ('Teach', 'Use', 'Storage', 'Forget', 'Remedy', 'ChangeBox'):
        assert 'MAX_STEPS' in inspect.getsource(getattr(menus, name).step), name
    assert 'RADIO_MAX_STEPS' in inspect.getsource(menus.Radio.step)
    assert menus.RADIO_MAX_STEPS < menus.MAX_STEPS


def make_emulator(**extra):
    from pokesim.gen2.emulator import Emulator
    events = []
    recoveries = []
    reloads = []
    policy = SimpleNamespace(recoveries=0, failure=None, details=lambda: {},
                             take_failure=lambda: None,
                             recover=lambda level: recoveries.append(level))
    values = dict(paused=False, manual_mode=False, preparation=None, store=SimpleNamespace(get=lambda key: None),
                  snapshot=SimpleNamespace(valid=True, started=True, map_name='Route 29'), frame=100000,
                  last_reload_frame=0, policy=policy, failure_streak=0, invalid_frame=None, battle_frame=None,
                  stuck_frame=100000, screen_frame=100000, progress_frame=100000, stuck_ts=0.0,
                  stall=SimpleNamespace(check=lambda frame, now: None))
    values.update(extra)
    emu = SimpleNamespace(**values)
    emu._unstick = lambda since, why: reloads.append(why)
    emu._check_stall = lambda: None
    emu._event = lambda event, snapshot: events.append(event)
    guard = lambda: Emulator._check_guards(emu)
    return emu, guard, recoveries, reloads, events


def test_unchanged_screen_escalates_policy_recovery_before_any_reload():
    from pokesim.gen2.emulator import SCREEN_FRAMES
    emu, guard, recoveries, reloads, _ = make_emulator(screen_frame=100000 - SCREEN_FRAMES)
    guard()
    assert recoveries == [1] and not reloads
    assert emu.screen_frame == emu.frame
    guard()
    assert recoveries == [1]


def test_recovery_level_rises_when_gentle_recovery_did_not_help():
    from pokesim.gen2.emulator import SCREEN_FRAMES
    emu, guard, recoveries, _, _ = make_emulator(screen_frame=100000 - SCREEN_FRAMES)
    emu.policy.recoveries = 1
    guard()
    assert recoveries == [2]


def test_glitched_state_and_repeated_menu_failures_reload_an_older_save():
    emu, guard, _, reloads, _ = make_emulator(invalid_frame=100000 - 601)
    guard()
    assert reloads == ['game state glitched']
    emu, guard, _, reloads, _ = make_emulator(failure_streak=3)
    guard()
    assert reloads == ['a menu task kept failing']


def test_hung_battle_and_no_position_change_reload():
    emu, guard, _, reloads, _ = make_emulator(battle_frame=100000 - config.BATTLE_TIMEOUT_SECONDS * 60 - 1)
    guard()
    assert reloads == ['battle never ended']
    emu, guard, _, reloads, _ = make_emulator(stuck_frame=100000 - config.STUCK_RELOAD_SECONDS * 60 - 1)
    guard()
    assert reloads == ['stuck']


def test_long_battle_that_keeps_bringing_out_new_opponents_is_not_hung():
    """Regression: a level 80 lead against Red's six Pokémon took about 50k frames, past the 54k
    battle timeout once healing was included, and the run reloaded a save from before Brock."""
    from pokesim.gen2.emulator import Emulator
    emu = SimpleNamespace(frame=0, battle_frame=None)
    seen = lambda species, level=80: SimpleNamespace(in_battle=2, enemy_species=species, enemy_level=level)
    Emulator._time_battle(emu, seen(25))
    assert emu.battle_frame == 0
    for frame, species in [(9000, 25), (18000, 196), (27000, 143), (36000, 25), (45000, 3), (54000, 6)]:
        emu.frame = frame
        Emulator._time_battle(emu, seen(species))
    assert emu.battle_frame == 54000
    emu.frame = 120000
    for species in (25, 196, 143):
        Emulator._time_battle(emu, seen(species))
    assert emu.battle_frame == 54000
    Emulator._time_battle(emu, SimpleNamespace(in_battle=0))
    assert emu.battle_frame is None and emu.battle_opponents == set()


def test_a_menu_failure_is_counted_once_per_failure():
    failures = deque(['The Teach menu task made no progress'])
    emu, guard, _, reloads, _ = make_emulator()
    emu.policy.take_failure = lambda: failures.popleft() if failures else None
    guard()
    assert emu.failure_streak == 1 and not reloads


def test_guards_stand_down_while_paused_or_in_manual_control():
    from pokesim.gen2.emulator import SCREEN_FRAMES
    for flag in ({'paused': True}, {'manual_mode': True}, {'preparation': {'phase': 'travelling'}}):
        emu, guard, recoveries, reloads, _ = make_emulator(screen_frame=100000 - SCREEN_FRAMES * 5,
                                                          stuck_frame=0, **flag)
        guard()
        assert not recoveries and not reloads
        assert emu.stuck_frame == emu.frame


def test_second_consecutive_unstick_raises_a_stuck_event():
    from pokesim.gen2.emulator import Emulator
    events = []
    saves = []
    emu = SimpleNamespace(unstick_streak=1, snapshot=SimpleNamespace(valid=True, started=True, map_name='Route 29'),
                          store=SimpleNamespace(autosaves=lambda: saves),
                          policy=SimpleNamespace(recoveries=4, menu=None, on_restore=lambda: None),
                          reloads=0, last_reload=0, audio=SimpleNamespace(clear=lambda: None),
                          statistics=SimpleNamespace(previous=None), options_applied=True, _tick=lambda n: None,
                          _reset_watch=lambda: None, _boot=lambda: SimpleNamespace(),
                          pb=SimpleNamespace(stop=lambda save: None),
                          _event=lambda event, snapshot: events.append(event))
    Emulator._unstick(emu, 0.0, 'stuck')
    assert emu.reloads == 1 and emu.unstick_streak == 2
    assert [event.type for event in events] == ['stall']
    assert events[0].title.startswith('Stuck?')


# Smaller fixes

def test_trade_inventory_before_the_game_starts_does_not_raise(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    assert policy.constant(SimpleNamespace(map=0)) == ''
    assert policy.constant(SimpleNamespace(map=987654)) == ''


def yes_no_snapshot(question):
    rows = [''] * 18
    rows[8] = '       ▶YES'
    rows[9] = '        NO'
    rows[13] = question
    return screen(rows, in_battle=0)


def test_unknown_yes_no_prompts_default_to_no(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    assert policy.unknown_yes_no(yes_no_snapshot('Save the game?')) == 'b'
    assert policy.unknown_yes_no(yes_no_snapshot('Put your money in the bank?')) == 'b'
    assert policy.unknown_yes_no(yes_no_snapshot('Heal your POKéMON?')) is None


def test_unknown_yes_no_refuses_three_times_then_lets_the_story_continue(real_data):
    from pokesim.gen2.policy import Policy
    policy = Policy(real_data, seed=1, starter='cyndaquil')
    question = yes_no_snapshot('Would you like a free lecture?')
    assert [policy.unknown_yes_no(question) for _ in range(5)] == ['b', 'b', 'b', None, 'b']


def test_full_pc_aborts_gen2_preparation_with_a_clear_error():
    from pokesim.gen2.preparation import Preparation
    full = SimpleNamespace(box_counts=(20,) * 14)
    with pytest.raises(ValueError, match='Every PC box is full'):
        Preparation.open_box(full)
    assert Preparation.open_box(SimpleNamespace(box_counts=(20, 20, 7, 20))) == 2


def test_stale_trade_hold_is_cleared_when_the_exchange_is_gone(monkeypatch):
    from pokesim.gen2.emulator import Emulator
    monkeypatch.setattr('pokesim.runtime.participant._records', lambda store: [{'id': 'other', 'phase': 'staged'}])
    data = {'trade_hold': {'id': 'gone'}}
    store = SimpleNamespace(get=data.get, set=data.__setitem__)
    Emulator._clear_stale_hold(SimpleNamespace(store=store))
    assert data['trade_hold'] is None
