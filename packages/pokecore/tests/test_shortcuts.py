"""Synthetic full-sequence tests for every shortcut. No ROM needed.

``Game`` is a scripted stand-in for the cartridge. It names the screen through the
port's panel, prints text into the tilemap, and changes WRAM the way the game
would after each input. Every test checks the whole input sequence ends at a
resting screen with the effect observed, or that a refusal sends nothing.
"""
import pytest

from pokecore.controls import ControllerPort
from pokecore.gen1 import W_TILEMAP
from pokecore.shortcuts import (RunAway, buy_item, change_box, choose_move, deposit_item,
                                    deposit_pokemon, item_kind, learn_move, list_items, list_moves, list_party,
                                    release_pokemon, reorder_party, run_away, sell_item, switch_pokemon,
                                    tm_number, toss_item, use_field_move, use_item, withdraw_item,
                                    withdraw_pokemon)
from pokecore.shortcuts import current_screen
from pokecore.shortcuts.screens import _quantity, menu_rows, text_lines
from pokecore.gen1_ui import read_screen

CHARS = {' ': 0x7F, 'é': 0xBA, '!': 0xE7, '.': 0xE8, "'": 0xE0, '?': 0xE6, ',': 0xF4, '×': 0xF1, '$': 0xF0}
CONTRACTIONS = {"'s": 0xBD, "'t": 0xBE, "'l": 0xBC, "'d": 0xBB}


def encode(text):
    out, i = [], 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in CONTRACTIONS:
            out.append(CONTRACTIONS[pair])
            i += 2
            continue
        if text[i:i + 4] == 'PKMN':
            out += [0xE1, 0xE2]
            i += 4
            continue
        char = text[i]
        if 'A' <= char <= 'Z':
            out.append(0x80 + ord(char) - 65)
        elif 'a' <= char <= 'z':
            out.append(0xA0 + ord(char) - 97)
        elif char.isdigit():
            out.append(0xF6 + int(char))
        else:
            out.append(CHARS[char])
        i += 1
    return out


def put(memory, x, y, text):
    for offset, tile in enumerate(encode(text)):
        memory[W_TILEMAP + y * 20 + x + offset] = tile


def mon(nick, *, level=20, moves=(33, 45, 0, 0), hp=40, species=1):
    return {'species': species, 'trainer_id': 7, 'dvs': (1, 2, 3, 4, 5), 'nick': nick, 'level': level,
            'hp': hp, 'max_hp': 50, 'status': 0, 'moves': list(moves), 'pp': [30, 30, 0, 0]}


BACK = {'pause': 'overworld', 'bag': 'pause', 'item_action': 'bag', 'party': 'pause', 'party_action': 'party',
        'item_target': 'bag', 'move_menu': 'battle_menu', 'mart_list': 'mart', 'bills_pc': 'pc',
        'players_pc': 'pc', 'pc_party': 'bills_pc', 'pc_box': 'bills_pc', 'pc_mon_action': 'bills_pc',
        'quantity': 'bag', 'move_list': 'party', 'fly_map': 'party'}
BATTLE_BACK = {'bag': 'battle_menu', 'party': 'battle_menu', 'item_target': 'battle_menu',
               'party_action': 'party', 'move_menu': 'battle_menu'}
LISTS = ('bag', 'party', 'item_target', 'move_list', 'move_menu', 'mart_list', 'pc_party', 'pc_box', 'pc_items')


class Game:
    """Scripted cartridge. ``a``, ``choose`` and ``after`` hold the scenario's reactions."""

    def __init__(self, kind='overworld', *, battle=0, party=None, bag=None, version=None):
        self.memory = bytearray(0x10000)
        self.memory[0xD057] = battle
        self.memory[0xD015] = 40
        self.party = party if party is not None else [mon('ONE'), mon('TWO')]
        self.bag = bag if bag is not None else []
        self.inputs, self.queue, self.frame = [], [], 0
        self.kind = None
        self.a, self.choices, self.then = {}, {}, None
        self.top = 99
        self.version = version
        self.go(kind)

    # Screen and text --------------------------------------------------------
    def go(self, kind):
        if kind in LISTS and kind != self.kind:
            self.memory[0xCC26] = self.memory[0xCC36] = 0
        if kind == 'quantity':
            self.memory[0xCF96] = 1
        self.kind = kind
        if kind != 'dialogue':
            self.show('')

    def show(self, text):
        start = W_TILEMAP + 14 * 20
        self.memory[start:start + 80] = bytes([0x7F]) * 80
        put(self.memory, 1, 14, text[:18])
        put(self.memory, 1, 16, text[18:36])

    def say(self, *texts, then=None):
        """Print ``texts`` one A press at a time, then call ``then`` (a screen name or a function)."""
        self.queue = list(texts)
        self.then = then
        self.kind = 'dialogue'
        self.show(self.queue.pop(0))

    def sync(self):
        self.memory[0xD163] = len(self.party)

    # Port callbacks ---------------------------------------------------------
    def send(self, button, hold, gap):
        self.frame += hold + gap
        if button is None:
            return self.frame < 200000
        self.inputs.append(button)
        kind, memory = self.kind, self.memory
        handler = self.a.get(kind) if button == 'a' else None
        if button == 'a' and kind == 'dialogue':
            if self.queue:
                self.show(self.queue.pop(0))
            else:
                then, self.then = self.then, None
                self.go(then) if isinstance(then, str) else then()
        elif handler:
            handler()
        elif button in ('up', 'down') and kind == 'quantity':
            step = 1 if button == 'up' else -1
            memory[0xCF96] = (memory[0xCF96] - 1 + step) % self.top + 1
        elif button in ('up', 'down') and kind == 'fly_map':
            self.town = (self.town + (1 if button == 'up' else -1)) % len(self.towns)
            self.draw_fly()
        elif button in ('up', 'down'):
            memory[0xCC26] = max(0, memory[0xCC26] + (1 if button == 'down' else -1))
        elif button == 'start' and kind == 'overworld':
            self.go('pause')
        elif button == 'b':
            back = BATTLE_BACK if memory[0xD057] else BACK
            if kind in back:
                self.go(back[kind])
        return self.frame < 200000

    def choose(self, label):
        self.inputs.append(label)
        self.frame += 32
        reaction = self.choices[(self.kind, label)]
        self.go(reaction) if isinstance(reaction, str) else reaction()
        return True

    def port(self):
        self.sync()
        return ControllerPort(self.memory, self.send, self.choose, lambda: {}, lambda: self.frame,
                              continue_ready=lambda: self.kind == 'dialogue' and bool(self.queue or self.then),
                              read_party=lambda m: self.party, read_bag=lambda m: list(self.bag),
                              panel=lambda memory, ui, labels: self.kind, version=self.version)

    # Helpers ------------------------------------------------------------------
    def add(self, item, amount):
        for index, (entry, qty) in enumerate(self.bag):
            if entry == item:
                if qty + amount:
                    self.bag[index] = (entry, qty + amount)
                else:
                    del self.bag[index]
                return
        self.bag.append((item, amount))

    def selected(self):
        return self.memory[0xCC26] + self.memory[0xCC36]

    def draw_fly(self):
        start = W_TILEMAP
        self.memory[start:start + 20] = bytes([0x7F]) * 20
        put(self.memory, 0, 0, 'To ' + self.towns[self.town])
        self.memory[start + 18:start + 20] = bytes([0xED, 0xEE])


def done(result):
    return result['shortcut']['completed'] and result['shortcut']['settled']


def field_bag(game, *, on_use=None, on_target=None):
    """Overworld, START, ITEM, the bag, then USE."""
    game.choices[('pause', 'ITEM')] = 'bag'
    game.choices[('pause', 'POKéMON')] = 'party'
    game.a['bag'] = lambda: game.go('item_action')
    game.choices[('item_action', 'USE')] = on_use or 'item_target'
    if on_target:
        game.a['item_target'] = on_target


# Items ----------------------------------------------------------------------

def test_field_heal_finishes_at_the_overworld():
    game = Game(bag=[(0x14, 2), (0x11, 1)])
    field_bag(game, on_target=lambda: game.say('TWO recovered by 20!', then=lambda: (game.add(0x14, -1),
                                                                                       game.go('item_target'))))
    result = use_item(game.port(), 0x14, 1)
    assert done(result) and result['shortcut']['item_consumed']
    assert game.kind == 'overworld'
    assert game.inputs.count('USE') == 1 and game.inputs[:2] == ['start', 'ITEM']


def test_battle_heal_presses_through_recovered_text_to_the_battle_menu():
    """Regression: the finish phase used to stop on the "recovered by" screen."""
    game = Game('battle_menu', battle=1, bag=[(0x10, 1)])
    game.choices[('battle_menu', 'ITEM')] = 'bag'
    game.a['bag'] = lambda: game.go('item_target')

    def heal():
        game.add(0x10, -1)
        game.say('ONE recovered by 60!', 'Wild RATTATA used TACKLE!', then='battle_menu')
    game.a['item_target'] = heal
    result = use_item(game.port(), 0x10, 0)
    assert done(result)
    assert game.kind == 'battle_menu'
    assert game.inputs.count('a') >= 3


def test_effect_without_rest_reports_unsettled():
    game = Game('battle_menu', battle=1, bag=[(0x10, 1)])
    game.choices[('battle_menu', 'ITEM')] = 'bag'
    game.a['bag'] = lambda: game.go('item_target')

    def heal():
        game.add(0x10, -1)
        game.kind = 'dialogue'
        game.show('ONE recovered by 60!')
    game.a['item_target'] = heal
    result = use_item(game.port(), 0x10, 0, max_steps=60)
    assert result['shortcut']['completed'] and not result['shortcut']['settled']


def test_refusal_text_is_reported_without_a_retry():
    game = Game(bag=[(0x0A, 1)])
    field_bag(game, on_target=lambda: game.say("It won't have any effect.", then='item_target'))
    result = use_item(game.port(), 0x0A, 0)
    assert not result['shortcut']['completed'] and result['shortcut']['settled']
    assert 'refused' in result['outcome'] and game.inputs.count('USE') == 1
    assert game.kind == 'overworld'


def test_no_target_item_and_rare_candy():
    game = Game(bag=[(0x1E, 1)])
    field_bag(game, on_use=lambda: (game.add(0x1E, -1), game.say('REPEL used.', then='bag')))
    assert done(use_item(game.port(), 0x1E)) and game.kind == 'overworld'

    game = Game(bag=[(0x28, 1)])

    def candy():
        game.party[0]['level'] += 1
        game.add(0x28, -1)
        game.say('ONE grew to level 21!', then='item_target')
    field_bag(game, on_target=candy)
    assert done(use_item(game.port(), 0x28, 0))
    with pytest.raises(ValueError):
        use_item(game.port(), 0x1E, 0)


def test_pp_item_picks_the_move_row():
    game = Game(bag=[(0x50, 1)])

    def restore():
        assert game.memory[0xCC26] == 2
        game.add(0x50, -1)
        game.say('PP was restored.', then='item_target')
    field_bag(game, on_target=lambda: game.go('move_list'))
    game.a['move_list'] = restore
    assert done(use_item(game.port(), 0x50, 0, 1))


def test_tm_with_four_moves_forgets_the_requested_slot():
    game = Game(party=[mon('ONE', moves=(33, 45, 10, 98)), mon('TWO')], bag=[(0xCC, 1)])

    def forget():
        assert game.memory[0xCC26] == 2
        game.party[0]['moves'][2] = 0x5C
        game.add(0xCC, -1)
        game.say('1, 2 and... Poof!', 'ONE learned TOXIC!', then='bag')

    def teach():
        game.say('ONE is trying to learn TOXIC!', 'Delete an older move to make room for TOXIC?',
                 then=lambda: game.go('yes_no'))
    game.choices[('yes_no', 'YES')] = lambda: (
        game.go('item_target') if game.stage == 0 else game.say('Which move should be forgotten?',
                                                                 then='move_list'),
        setattr(game, 'stage', game.stage + 1))
    game.stage = 0
    field_bag(game, on_use=lambda: game.say('Booted up a TM!', 'It contained TOXIC!',
                                            'Teach TOXIC to a POKéMON?', then='yes_no'), on_target=teach)
    game.a['move_list'] = forget
    result = use_item(game.port(), 0xCC, 0, forget_move=2)
    assert done(result) and game.party[0]['moves'][2] == 0x5C
    assert game.kind == 'overworld'
    with pytest.raises(ValueError):
        use_item(game.port(), 0xCC, 0, forget_move=4)


def test_tm_on_a_full_moveset_needs_forget_move():
    game = Game(party=[mon('ONE', moves=(33, 45, 10, 98))], bag=[(0xCC, 1)])
    result = use_item(game.port(), 0xCC, 0)
    assert 'forget_move' in result['outcome'] and game.inputs == []


def test_ball_catch_answers_no_to_the_nickname_prompt():
    game = Game('battle_menu', battle=1, bag=[(0x04, 3)])
    game.choices[('battle_menu', 'ITEM')] = 'bag'

    def throw():
        game.add(0x04, -1)
        game.say('All right! RATTATA was caught!', 'Do you want to give a nickname to RATTATA?',
                 then='yes_no')
    game.a['bag'] = throw

    def end():
        game.memory[0xD057] = 0
        game.go('overworld')
    game.choices[('yes_no', 'NO')] = end
    assert done(use_item(game.port(), 0x04)) and game.kind == 'overworld'
    assert 'NO' in game.inputs and 'YES' not in game.inputs


def test_item_prechecks_send_nothing():
    game = Game('battle_menu', battle=2, bag=[(0x04, 3), (0x14, 1), (0x3F, 1)])
    assert 'wild battles' in use_item(game.port(), 0x04)['outcome']
    assert 'cannot be used in battle' in use_item(game.port(), 0x3F)['outcome']
    game = Game('battle_menu', battle=1, bag=[(0x04, 3)])
    game.memory[0xDA80] = 20
    assert 'box is full' in use_item(game.port(), 0x04)['outcome']
    game = Game(bag=[(0x2E, 1), (0x3F, 1)])
    assert 'cannot be used here' in use_item(game.port(), 0x2E)['outcome']
    assert 'cannot be used here' in use_item(game.port(), 0x3F)['outcome']
    assert game.inputs == []


# Battle -----------------------------------------------------------------------

def battle_game():
    game = Game('battle_menu', battle=1)
    game.memory[0xD01C:0xD020] = bytes([33, 45, 0, 0])
    game.memory[0xD02D:0xD031] = bytes([30, 0, 0, 0])
    return game


def test_choose_move_waits_for_the_turn():
    game = battle_game()
    game.memory[0xD02E] = 20

    def fight():
        game.go('move_menu')
        game.memory[0xCC26] = 1

    def pick():
        game.memory[0xCCDC] = game.memory[0xD01C + game.memory[0xCC26] - 1]
        game.say('ONE used GROWL!', then='battle_menu')
    game.choices[('battle_menu', 'FIGHT')] = fight
    game.a['move_menu'] = pick
    result = choose_move(game.port(), 1)
    assert done(result) and result['shortcut']['move_id'] == 45 and game.kind == 'battle_menu'
    assert game.inputs[:3] == ['FIGHT', 'down', 'a']


def test_choose_move_refuses_empty_and_spent_moves():
    game = battle_game()
    assert 'empty' in choose_move(game.port(), 2)['outcome']
    assert 'no PP' in choose_move(game.port(), 1)['outcome']
    assert game.inputs == []


def test_run_away_and_trainer_refusal():
    game = battle_game()

    def flee():
        game.memory[0xD057] = 0
        game.go('overworld')
    game.choices[('battle_menu', 'RUN')] = lambda: game.say('Got away safely!', then=flee)
    result = run_away(game.port())
    assert done(result) and result['shortcut']['escaped'] and game.kind == 'overworld'
    game = battle_game()
    game.memory[0xD057] = 2
    assert 'trainer battle' in run_away(game.port())['outcome'] and game.inputs == []


def test_run_away_through_step_resolves_the_battle_menu_cursor():
    game = battle_game()
    put(game.memory, 10, 14, 'FIGHT')
    put(game.memory, 16, 14, 'PKMN')
    put(game.memory, 10, 16, 'ITEM')
    put(game.memory, 16, 16, 'RUN')
    cursor = [9, 14]
    game.memory[W_TILEMAP + 14 * 20 + 9] = 0xED
    machine = RunAway()
    pressed = []
    for _ in range(40):
        action = machine.step(game.memory, {'screen': game.kind, 'continue_ready': game.kind == 'dialogue'})
        if hasattr(action, 'outcome'):
            break
        pressed.append(action)
        if action in ('down', 'right'):
            game.memory[W_TILEMAP + cursor[1] * 20 + cursor[0]] = 0x7F
            cursor = [15, 16] if action == 'right' else [cursor[0], 16]
            if action == 'down':
                cursor = [9, 16]
            game.memory[W_TILEMAP + cursor[1] * 20 + cursor[0]] = 0xED
        elif action == 'a' and game.kind == 'battle_menu':
            assert cursor == [15, 16]
            game.memory[0xD057] = 0
            game.say('Got away safely!', then='overworld')
        elif action == 'a':
            game.send('a', 8, 24)
    assert action.completed and action.settled
    assert pressed[:3] == ['down', 'right', 'a']


def test_switch_in_battle_and_in_the_field():
    game = battle_game()
    game.choices[('battle_menu', 'PKMN')] = 'party'
    game.a['party'] = lambda: game.go('party_action')
    game.choices[('party_action', 'SWITCH')] = lambda: game.say(
        'Come back ONE!', 'Go! TWO!', then=lambda: (game.memory.__setitem__(0xCC2F, 1), game.go('battle_menu')))
    assert done(switch_pokemon(game.port(), 1)) and game.kind == 'battle_menu'

    game = Game()
    game.choices[('pause', 'POKéMON')] = 'party'

    def pick():
        if getattr(game, 'switching', False):
            game.party.reverse()
            game.switching = False
            game.go('party')
        else:
            game.go('party_action')
    game.a['party'] = pick
    game.choices[('party_action', 'SWITCH')] = lambda: (setattr(game, 'switching', True), game.go('party'))
    assert done(switch_pokemon(game.port(), 1)) and game.party[0]['nick'] == 'TWO'
    assert game.kind == 'overworld'


def test_reorder_party_swaps_two_slots():
    game = Game(party=[mon('ONE'), mon('TWO'), mon('THREE')])
    game.choices[('pause', 'POKéMON')] = 'party'
    game.switching = None

    def pick():
        if game.switching is not None:
            a, b = game.switching, game.selected()
            game.party[a], game.party[b] = game.party[b], game.party[a]
            game.switching = None
            game.go('party')
        else:
            game.first = game.selected()
            game.go('party_action')
    game.a['party'] = pick
    game.choices[('party_action', 'SWITCH')] = lambda: (setattr(game, 'switching', game.first),
                                                        game.go('party'))
    assert done(reorder_party(game.port(), 0, 2))
    assert [m['nick'] for m in game.party] == ['THREE', 'TWO', 'ONE']
    assert 'outside battle' in reorder_party(battle_game().port(), 0, 1)['outcome']


# Field moves --------------------------------------------------------------------

def field_move_game(move):
    game = Game(party=[mon('ONE', moves=(move, 33, 0, 0)), mon('TWO')])
    game.memory[0xD356] = 0xFF
    game.choices[('pause', 'POKéMON')] = 'party'
    game.a['party'] = lambda: game.go('party_action')
    return game


def test_strength_and_flash():
    game = field_move_game(70)

    def strength():
        game.memory[0xD728] |= 1
        game.say('ONE used STRENGTH.', then='overworld')
    game.choices[('party_action', 'STRENGTH')] = strength
    result = use_field_move(game.port(), 'strength', 0)
    assert done(result) and result['shortcut']['move'] == 'STRENGTH'

    game = field_move_game(148)
    game.choices[('party_action', 'FLASH')] = lambda: game.say('A blinding FLASH lights the area!',
                                                               then='overworld')
    assert done(use_field_move(game.port(), 'FLASH', 0)) and game.kind == 'overworld'


def test_fly_scrolls_to_the_named_town():
    game = field_move_game(19)
    game.towns, game.town = ['PALLET TOWN', 'VIRIDIAN CITY', 'PEWTER CITY'], 0
    game.choices[('party_action', 'FLY')] = lambda: (game.go('fly_map'), game.draw_fly())

    def land():
        game.memory[0xD35E] = game.town
        game.memory[W_TILEMAP:W_TILEMAP + 20] = bytes([0x7F]) * 20
        game.go('overworld')
    game.memory[0xD35E] = 9
    game.a['fly_map'] = land
    assert done(use_field_move(game.port(), 'FLY', 0, 'Pewter City'))
    assert game.memory[0xD35E] == 2 and game.inputs.count('up') == 2


def test_field_move_prechecks():
    game = field_move_game(70)
    assert 'does not know' in use_field_move(game.port(), 'CUT', 0)['outcome']
    game.memory[0xD356] = 0
    assert 'badge' in use_field_move(game.port(), 'STRENGTH', 0)['outcome']
    assert game.inputs == []
    with pytest.raises(ValueError):
        use_field_move(game.port(), 'FLY', 0)
    with pytest.raises(ValueError):
        use_field_move(game.port(), 'DIG', 0)


# Bag quantity menus ----------------------------------------------------------------

def test_toss_sets_the_quantity_and_confirms():
    game = Game(bag=[(0x14, 5)])
    field_bag(game)
    game.top = 5
    game.choices[('item_action', 'TOSS')] = 'quantity'
    game.a['quantity'] = lambda: game.say('Is it OK to toss SUPER POTION?', then='yes_no')
    game.choices[('yes_no', 'YES')] = lambda: (game.add(0x14, -game.memory[0xCF96]),
                                               game.say('Threw away SUPER POTION.', then='bag'))
    assert done(toss_item(game.port(), 0x14, 4)) and game.bag == [(0x14, 1)]
    assert game.inputs.count('down') == 2 and 'up' not in game.inputs
    assert 'too important' in toss_item(Game(bag=[(0x06, 1)]).port(), 0x06)['outcome']


def mart_game(bag):
    game = Game('mart', bag=bag)
    game.memory[0xCF7B:0xCF7F] = bytes([2, 0x04, 0x14, 0xFF])

    def pick_stock():
        game.buying = game.memory[0xCF7C + game.selected()]
        game.go('quantity')
    game.choices[('mart', 'BUY')] = lambda: game.say('Take your time.', then='mart_list')
    game.a['mart_list'] = pick_stock
    return game


def test_buy_and_sell_at_a_mart():
    game = mart_game([(0x04, 2)])
    game.a['quantity'] = lambda: game.say('POKé BALL? That will be $600. OK?', then='yes_no')
    game.choices[('yes_no', 'YES')] = lambda: (game.add(game.buying, game.memory[0xCF96]),
                                               game.say('Here you are!', then='mart_list'))
    result = buy_item(game.port(), 0x14, 3)
    assert done(result) and (0x14, 3) in game.bag and game.kind == 'mart'
    assert 'does not sell' in buy_item(game.port(), 0x10)['outcome']

    game = mart_game([(0x04, 2), (0x14, 6)])
    game.top = 6
    game.choices[('mart', 'SELL')] = 'bag'
    game.a['bag'] = lambda: game.go('quantity')
    game.a['quantity'] = lambda: game.say('I can pay you $1000 for that.', then='yes_no')
    game.choices[('yes_no', 'YES')] = lambda: (game.add(0x14, -game.memory[0xCF96]), game.go('bag'))
    BACK['bag'] = 'mart'
    try:
        assert done(sell_item(game.port(), 0x14, 5)) and game.bag[-1] == (0x14, 1)
    finally:
        BACK['bag'] = 'pause'
    assert game.kind == 'mart'
    assert 'cannot be sold' in sell_item(Game('mart', bag=[(0xC4, 1)]).port(), 0xC4)['outcome']


def test_mart_refuses_money_shortfall_and_wrong_start():
    game = mart_game([])
    game.a['quantity'] = lambda: game.say("You don't have enough money.", then='mart_list')
    result = buy_item(game.port(), 0x04, 1)
    assert not result['shortcut']['completed'] and result['outcome'].startswith('The game refused')
    assert game.kind == 'mart'
    assert 'starts at' in buy_item(Game(bag=[]).port(), 0x04)['outcome']
    full = Game('mart', bag=[(i, 1) for i in range(0x10, 0x24)])
    assert 'bag is full' in buy_item(full.port(), 0x04)['outcome']


# PC ---------------------------------------------------------------------------------

def pc_game(party, box):
    game = Game('pc', party=party)
    game.memory[0xDA80] = box
    game.memory[0xCC24], game.memory[0xCC25], game.memory[0xCC28] = 2, 1, 2
    for row, text in enumerate(("BILL's PC", "ASH's PC", 'LOG OFF')):
        put(game.memory, 2, 2 + 2 * row, text)
    game.choices[('pc', "BILL's PC")] = lambda: game.say("Accessed BILL's PC.", then='bills_pc')
    game.choices[('pc', "ASH's PC")] = lambda: game.say('Accessed my PC.', then='players_pc')
    return game


def test_deposit_and_withdraw_pokemon():
    game = pc_game([mon('ONE'), mon('TWO')], 3)
    game.choices[('bills_pc', 'DEPOSIT PKMN')] = 'pc_party'
    game.a['pc_party'] = lambda: game.go('pc_mon_action')

    def deposit():
        del game.party[game.memory[0xCC26]]
        game.sync()
        game.memory[0xDA80] += 1
        game.say('TWO was stored in Box 1.', then='bills_pc')
    game.memory[0xCC26] = 0
    game.choices[('pc_mon_action', 'DEPOSIT')] = deposit
    original = game.a['pc_party']
    game.a['pc_party'] = lambda: (setattr(game, 'slot', game.selected()), original())
    game.choices[('pc_mon_action', 'DEPOSIT')] = lambda: (game.memory.__setitem__(0xCC26, game.slot), deposit())
    assert done(deposit_pokemon(game.port(), 1)) and [m['nick'] for m in game.party] == ['ONE']
    assert game.kind == 'pc' and game.memory[0xDA80] == 4
    assert 'last Pokemon' in deposit_pokemon(game.port(), 0)['outcome']

    game.choices[('bills_pc', 'WITHDRAW PKMN')] = 'pc_box'
    game.a['pc_box'] = lambda: game.go('pc_mon_action')

    def withdraw():
        game.party.append(mon('BOXED'))
        game.sync()
        game.memory[0xDA80] -= 1
        game.say('BOXED is taken out.', then='bills_pc')
    game.choices[('pc_mon_action', 'WITHDRAW')] = withdraw
    assert done(withdraw_pokemon(game.port(), 3)) and len(game.party) == 2
    assert 'box position' in withdraw_pokemon(game.port(), 3)['outcome']


def test_bills_pc_two_line_acknowledgment_over_visible_menu_without_readiness():
    game = pc_game([mon('ONE')], 2)
    game.choices[('pc', "BILL's PC")] = lambda: game.show("Accessed BILL's PC.")
    acknowledgments = iter(['Accessed POKéMON Storage System.', None])

    def acknowledge():
        text = next(acknowledgments)
        game.show(text) if text else game.go('bills_pc')

    game.a['pc'] = acknowledge
    game.choices[('bills_pc', 'WITHDRAW PKMN')] = 'pc_box'
    game.a['pc_box'] = lambda: game.go('pc_mon_action')
    game.choices[('pc_mon_action', 'WITHDRAW')] = lambda: (
        game.party.append(mon('BOXED')), game.sync(), game.memory.__setitem__(0xDA80, 1),
        game.say('BOXED is taken out.', then='bills_pc'))
    port = game.port()
    port.continue_ready = lambda: None
    result = withdraw_pokemon(port, 1)
    assert result['control']['completed'] and len(game.party) == 2
    assert game.inputs[:4] == ["BILL's PC", 'a', 'a', 'WITHDRAW PKMN']


def test_release_needs_the_flag_and_confirms():
    game = pc_game([mon('ONE')], 2)
    with pytest.raises(ValueError):
        release_pokemon(game.port(), 0)
    game.choices[('bills_pc', 'RELEASE PKMN')] = 'pc_box'
    game.a['pc_box'] = lambda: game.say('Once released, BOXED is gone forever. OK?', then='yes_no')
    game.choices[('yes_no', 'YES')] = lambda: (game.memory.__setitem__(0xDA80, 1),
                                               game.say('BOXED was released outside.', then='bills_pc'))
    assert done(release_pokemon(game.port(), 1, allow_release=True)) and game.memory[0xDA80] == 1
    assert game.inputs.count('YES') == 1


def test_item_pc_deposit_and_withdraw():
    game = pc_game([mon('ONE')], 0)
    game.memory[0xD53A:0xD53D] = bytes([1, 0x14, 2])
    BACK['bag'] = 'players_pc'
    try:
        game.bag = [(0x10, 4)]
        game.top = 4
        game.choices[('players_pc', 'DEPOSIT ITEM')] = 'bag'
        game.a['bag'] = lambda: game.go('quantity')
        game.a['quantity'] = lambda: (game.add(0x10, -game.memory[0xCF96]),
                                      game.say('FULL RESTORE was stored via PC.', then='bag'))
        assert done(deposit_item(game.port(), 0x10, 3)) and game.bag == [(0x10, 1)]
        assert game.kind == 'pc'
    finally:
        BACK['bag'] = 'pause'
    BACK['pc_items'] = 'players_pc'
    try:
        game.top = 2
        game.choices[('players_pc', 'WITHDRAW ITEM')] = 'pc_items'
        game.a['pc_items'] = lambda: game.go('quantity')
        game.a['quantity'] = lambda: (game.add(0x14, game.memory[0xCF96]),
                                      game.say('Withdrew SUPER POTION.', then='pc_items'))
        assert done(withdraw_item(game.port(), 0x14, 2)) and (0x14, 2) in game.bag
    finally:
        del BACK['pc_items']
    assert 'not stored' in withdraw_item(game.port(), 0x01)['outcome']
    assert 'Only 1' in deposit_item(game.port(), 0x10, 2)['outcome']


# Gen 2 and queries ---------------------------------------------------------------------

def test_queries_read_the_bag_party_and_moves():
    memory = bytearray(0x10000)
    memory[0xD31D:0xD322] = bytes([2, 0x14, 3, 0x04, 1])
    memory[0xD322] = 0xFF
    memory[0xD163] = 1
    memory[0xD164] = 1
    memory[0xD16B] = 1
    memory[0xD16B + 8:0xD16B + 12] = bytes([33, 45, 0, 0])
    memory[0xD16B + 29:0xD16B + 33] = bytes([0xC0 | 30, 20, 0, 0])
    items = list_items(memory)
    assert [(i['id'], i['qty'], i['kind'], i['usable']) for i in items] == [(0x14, 3, 'heal', True),
                                                                             (0x04, 1, 'ball', False)]
    assert list_party(memory)[0]['moves'] == [33, 45, 0, 0]
    moves = list_moves(memory, 0)
    assert [(m['index'], m['id'], m['pp'], m['pp_ups']) for m in moves] == [(0, 33, 30, 3), (1, 45, 20, 0)]
    assert list_moves(memory, 3) == []
    with pytest.raises(ValueError):
        list_moves(memory, 6)
    assert item_kind(0x14).kind == 'heal' and item_kind(0x14, 'crystal').kind != 'heal'
    assert tm_number(0xC9) == ('TM', 1) and tm_number(0xC4) == ('HM', 1)
    assert tm_number(0xBF, 'gold') == ('TM', 1) and tm_number(0xF3, 'gold') == ('HM', 1)


def test_screen_helpers_read_contractions_glyph_pairs_and_quantity_boxes():
    memory = bytearray(0x10000)
    put(memory, 1, 14, "It won't work.")
    assert text_lines(memory) == "It won't work."
    # Yellow's Vermilion PC: PK and MN print two letters each, which ran past the last row.
    memory[W_TILEMAP + 240:W_TILEMAP + 360] = bytes(120)
    put(memory, 1, 14, "PKMN won't go.")
    put(memory, 1, 17, 'PKMN PKMN PKMN PKMN')
    assert text_lines(memory) == "PKMN won't go. PKMN PKMN PKMN PKMN"
    assert text_lines(memory[:W_TILEMAP + 300]) == "PKMN won't go."
    memory[W_TILEMAP + 240:W_TILEMAP + 360] = bytes(120)
    memory[0xCC24], memory[0xCC25], memory[0xCC28] = 2, 1, 0
    put(memory, 2, 2, 'WITHDRAW PKMN')
    assert menu_rows(memory, read_screen(memory))[0]['text'] == 'WITHDRAW PKMN'
    memory[W_TILEMAP + 9 * 20 + 7] = 0x79
    put(memory, 8, 10, '×03')
    assert _quantity(read_screen(memory))


@pytest.mark.parametrize('version', ['red', 'yellow'])
def test_pre_game_screens_read_the_play_time_flag(version):
    memory = bytearray(0x10000)
    memory[0xFF40], memory[0xFF47] = 0x80, 0xE4
    # Yellow keeps wStatusFlags6 one byte below Red.
    flags = 0xD732 if version == 'red' else 0xD731
    memory[W_TILEMAP:W_TILEMAP + 360] = bytes([0x7F]) * 360
    memory[flags] = 1
    assert current_screen(memory, version=version) == 'overworld'
    # A soft reset can leave the last game in WRAM but clears the play time flag.
    memory[flags] = 0
    assert current_screen(memory, version=version) == 'title'
    memory[0xCC24], memory[0xCC25], memory[0xCC28] = 2, 0, 1
    memory[W_TILEMAP + 2 * 20] = 0xED
    put(memory, 1, 2, 'NEW GAME')
    put(memory, 1, 4, 'OPTION')
    assert current_screen(memory, version=version) == 'main_menu'
    # Title art can show a cursor tile beside stray font tiles.
    put(memory, 1, 2, 'ABCDEFGH')
    put(memory, 1, 4, 'IJKLMN')
    assert current_screen(memory, version=version) == 'title'
    memory[flags] = 1
    assert current_screen(memory, version=version) == 'menu'


def test_use_item_keeps_the_old_keyword_names():
    game = Game(bag=[(0x14, 1)])
    field_bag(game, on_target=lambda: (game.add(0x14, -1), game.say('ONE recovered by 20!', then='item_target')))
    assert done(use_item(game.port(), item_id=0x14, party_slot=0))


def test_ball_catch_can_stop_at_the_nickname_prompt():
    game = Game('battle_menu', battle=1, bag=[(0x04, 3)])
    game.choices[('battle_menu', 'ITEM')] = 'bag'
    game.a['bag'] = lambda: (game.add(0x04, -1), game.say('All right! RATTATA was caught!',
                                                          'Give a nickname to RATTATA?', then='yes_no'))
    result = use_item(game.port(), 0x04, nickname='caller')
    assert result['shortcut']['completed'] and result['shortcut']['pending'] == 'nickname', result
    assert game.kind == 'yes_no' and 'NO' not in game.inputs


def test_fight_with_no_pp_left_uses_struggle():
    game = battle_game()
    game.memory[0xD02D:0xD031] = bytes([0, 0, 0, 0])
    game.choices[('battle_menu', 'FIGHT')] = lambda: game.say('ONE has no moves left!', 'ONE used STRUGGLE!',
                                                              'Enemy RATTATA used TACKLE!', then='battle_menu')
    result = choose_move(game.port(), 0)
    assert done(result) and result['shortcut']['forced'] == 'struggle' and game.kind == 'battle_menu', result


def test_change_box_picks_the_box_and_saves():
    game = pc_game([mon('ONE')], 0)
    game.memory[0xD5A0] = 0x80
    game.choices[('bills_pc', 'CHANGE BOX')] = lambda: game.say('Data will be saved. OK?', then='yes_no')
    game.choices[('yes_no', 'YES')] = 'menu'

    def pick():
        game.memory[0xD5A0] = 0x80 | game.memory[0xCC26]
        game.say('Saving...', 'ASH saved the game.', then='bills_pc')
    game.a['menu'] = pick
    result = change_box(game.port(), 5)
    assert done(result) and game.memory[0xD5A0] & 0x7F == 5 and game.kind == 'pc', result
    assert 'already' in change_box(game.port(), 5)['outcome']
    with pytest.raises(ValueError):
        change_box(game.port(), 12)


def test_learn_move_at_level_up_replaces_or_keeps():
    game = Game('dialogue', battle=1, party=[mon('ONE', moves=(33, 45, 10, 98))])
    game.memory[0xCF92] = 0

    def prompt():
        game.say('ONE is trying to learn THUNDER!', 'Delete an older move to make room?', then='yes_no')
    prompt()

    def forget():
        game.party[0]['moves'][game.memory[0xCC26]] = 87
        game.say('1, 2 and... Poof!', 'ONE learned THUNDER!', then='battle_menu')
    game.choices[('yes_no', 'YES')] = lambda: game.say('Which move should be forgotten?', then='move_list')
    game.choices[('yes_no', 'NO')] = lambda: game.say('Abandon learning THUNDER?', then=lambda: (
        game.choices.__setitem__(('yes_no', 'YES'), lambda: game.say('ONE did not learn THUNDER!',
                                                                     then='battle_menu')),
        game.go('yes_no')))
    game.a['move_list'] = forget
    result = learn_move(game.port(), 1)
    assert done(result) and game.party[0]['moves'] == [33, 87, 10, 98] and game.kind == 'battle_menu', result

    game = Game('dialogue', battle=1, party=[mon('ONE', moves=(33, 45, 10, 98))])
    game.say('ONE is trying to learn THUNDER!', 'Delete an older move to make room?', then='yes_no')

    def abandon():
        game.say('Abandon learning THUNDER?', then='yes_no')
        game.choices[('yes_no', 'YES')] = lambda: game.say('ONE did not learn THUNDER!', then='battle_menu')
    game.choices[('yes_no', 'NO')] = abandon
    result = learn_move(game.port(), 'keep')
    assert done(result) and game.party[0]['moves'] == [33, 45, 10, 98] and game.kind == 'battle_menu', result


def test_player_pc_acknowledgment_over_visible_menu_without_readiness():
    game = pc_game([mon('ONE')], 0)
    game.memory[0xD53A:0xD53D] = bytes([1, 0x14, 1])
    game.top = 1
    game.choices[('pc', "ASH's PC")] = lambda: game.show('Accessed my PC.')
    acknowledgments = iter(['Accessed Item Storage System.', None])

    def acknowledge():
        text = next(acknowledgments)
        game.show(text) if text else game.go('players_pc')

    game.a['pc'] = acknowledge
    game.choices[('players_pc', 'WITHDRAW ITEM')] = 'pc_items'
    game.a['pc_items'] = lambda: game.go('quantity')
    game.a['quantity'] = lambda: (game.add(0x14, 1), game.go('players_pc'))
    port = game.port()
    port.continue_ready = lambda: None
    result = withdraw_item(port, 0x14, 1)
    assert done(result)
    assert game.bag == [(0x14, 1)]
    assert game.inputs[:4] == ["ASH's PC", 'a', 'a', 'WITHDRAW ITEM']



def test_choose_move_accepts_brief_forced_turn_without_pressing_fight_again():
    game = battle_game()
    game.choices[('battle_menu', 'FIGHT')] = lambda: game.say("Enemy CLOYSTER's attack continues!", then='battle_menu')
    original = game.send
    def send(button, hold, gap):
        result = original(button, hold, gap)
        if button is None and game.kind == 'dialogue':
            game.go('battle_menu')
        return result
    game.send = send
    result = choose_move(game.port(), 0)
    assert done(result), result
    assert result['shortcut']['forced'] == 'locked'
    assert game.inputs.count('FIGHT') == 1
    assert game.kind == 'battle_menu'


def test_choose_move_does_not_call_ignored_fight_a_completed_turn():
    game = battle_game()
    game.choices[('battle_menu', 'FIGHT')] = lambda: None
    result = choose_move(game.port(), 0)
    assert not result['shortcut']['completed']
    assert 'FIGHT did not open' in result['outcome']


def test_choose_move_waits_for_late_move_list_after_brief_text():
    game = battle_game()
    game.choices[('battle_menu', 'FIGHT')] = lambda: game.say('Waiting', then='move_menu')
    original = game.send
    def send(button, hold, gap):
        result = original(button, hold, gap)
        if button is None and game.kind == 'dialogue' and game.then == 'move_menu':
            game.go('move_menu')
            game.memory[0xCC26] = 1
        return result
    game.send = send
    def pick():
        game.memory[0xCCDC] = game.memory[0xD01C]
        game.say('ONE used TACKLE!', then='battle_menu')
    game.a['move_menu'] = pick
    result = choose_move(game.port(), 0)
    assert done(result), result
    assert 'forced' not in result['shortcut']
    assert game.inputs.count('FIGHT') == 1



def test_choose_move_recognizes_forced_damage_inside_blocking_label_selection():
    game = battle_game()
    game.memory[0xD015:0xD017] = bytes([0, 40])
    def fight():
        game.memory[0xD015:0xD017] = bytes([0, 23])
        game.go('battle_menu')
    game.choices[('battle_menu', 'FIGHT')] = fight
    result = choose_move(game.port(), 0)
    assert done(result), result
    assert result['shortcut']['forced'] == 'locked'
    assert game.inputs.count('FIGHT') == 1


def test_box_list_presses_a_through_a_cont_wait():
    """A box nickname holding <CONT> (0x55) stops the list redraw at a ▼ until A."""
    from types import SimpleNamespace

    from pokecore.shortcuts import WithdrawPokemon
    machine = WithdrawPokemon(5)
    position = [0]

    def look(waiting):
        machine.obs = SimpleNamespace(screen='dialogue' if waiting else 'pc_box', ui={}, ready=waiting or None)

    look(False)
    flow = machine.move_index(5, lambda obs: position[0])
    pressed = []
    try:
        button = next(flow)
        while True:
            pressed.append(button)
            if button == 'down':
                position[0] += 1
            look(button == 'down' and position[0] >= 3)
            button = flow.send(None)
    except StopIteration as stop:
        assert stop.value is True
    assert pressed == ['down', 'down', 'down', 'a', 'down', 'a', 'down', 'a'], pressed
