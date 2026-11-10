"""Synthetic full-sequence tests for the Gold, Silver and Crystal shortcuts. No ROM needed.

``Game2`` is a scripted stand-in for a Gen 2 cartridge. It keeps a small model of
the party, pack, PC and battle, writes it to WRAM through the version's symbol
map, and draws each screen into the 20x18 tilemap the way the game lays it out.
The shortcuts read only that memory: the screen comes from Core's own classifier.
Every input goes through ``port.send``. ``port.choose`` fails the test if called.
"""
from collections import defaultdict
from functools import lru_cache

import pytest

from pokecore.controls import ControllerPort
from pokecore.gen2.charmap import charmap
from pokecore.shortcuts import (ChooseMove, buy_item, change_box, choose_move, current_screen, day_care,
                                    delete_move, deposit_item, deposit_pokemon, give_item, learn_move, list_box,
                                    list_items, list_moves, list_party, release_pokemon, reorder_party, run_away,
                                    sell_item, show_partner, switch_pokemon, take_item, toss_item, tune_radio,
                                    use_field_move, use_item, withdraw_item, withdraw_pokemon)
from pokecore.shortcuts import gen2ui
from pokecore.shortcuts.items import GEN2_FIELD_MOVES, gen2_pocket, gen2_tm_item, item_kind, key_item

POTION, SUPER_POTION, ESCAPE_ROPE, BERRY, ETHER = 0x12, 0x11, 0x13, 0xAD, 0x3F
SUPER_ROD = 0x3D
POKE_BALL, BICYCLE, LEFTOVERS, MAIL = 0x05, 0x07, 0x92, 0x9E
TM01, HM01 = gen2_tm_item(0), gen2_tm_item(50)
TM_INDEX = {gen2_tm_item(index): index for index in range(57)}
TL, H, TR, V, BL, BR = 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E
CURSOR, IDLE, MORE, SPACE = 0xED, 0xEC, 0xEE, 0x7F
MOVE_IDS = {name: move_id for name, (move_id, _) in GEN2_FIELD_MOVES.items()}
FIELD_TEXT = {'CUT': 'used CUT!', 'FLASH': 'A blinding FLASH lights the area!', 'WHIRLPOOL': 'used WHIRLPOOL!',
              'WATERFALL': 'used WATERFALL!', 'ROCKSMASH': 'used ROCK SMASH!', 'HEADBUTT': 'did a HEADBUTT!'}
FIELD_LABELS = {'ROCKSMASH': 'ROCK SMASH'}


@lru_cache(maxsize=3)
def _codes(version):
    codes = {}
    for tile, value in sorted(charmap(version).items()):
        if len(value) == 1:
            codes.setdefault(value, tile)
    codes[' '] = SPACE
    return codes


def encode(text, version='crystal'):
    codes = _codes(version)
    return bytes(codes[char] for char in text)


def name(text, version='crystal'):
    return (encode(text, version) + b'\x50').ljust(11, b'\x50')


def wrap(text, width=18):
    lines, line = [], ''
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}' if line else word
    return lines + ([line] if line else [])


def mon(nick, *, species=1, level=20, moves=(33, 45, 0, 0), hp=40, item=0, egg=False):
    return {'species': species, 'nick': nick, 'level': level, 'moves': list(moves), 'pp': [30, 30, 0, 0],
            'hp': hp, 'max_hp': 50, 'item': item, 'egg': egg, 'tid': 7 + len(nick)}


def struct(mon, party=True):
    raw = bytearray(48 if party else 32)
    raw[0], raw[1], raw[2:6] = mon['species'], mon['item'], bytes(mon['moves'])
    raw[6:8] = mon['tid'].to_bytes(2, 'big')
    raw[21], raw[22] = 0x12, 0x34
    raw[23:27] = bytes(mon['pp'])
    raw[31] = mon['level']
    if party:
        raw[34:36] = mon['hp'].to_bytes(2, 'big')
        raw[36:38] = mon['max_hp'].to_bytes(2, 'big')
    return bytes(raw)


class BankedMemory:
    """Core's banked memory shape: ``memory[bank, a:b]`` for WRAM and SRAM, ``memory[a:b]`` otherwise."""

    def __init__(self):
        self.banks = defaultdict(lambda: bytearray(0x10000))
        self.banks[0][0xFF40] = 0x80
        # wGameTimerPaused for Gold and Silver, then Crystal: the game has started.
        self.banks[1][0xD8B8] = self.banks[0][0xCFBC] = 1

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]


class Game2:
    """A menu-level model of a Gen 2 game. ``screen`` is the fake's own state name."""

    def __init__(self, version='crystal', *, party=None, items=(), balls=(), key=(), tms=(), pc=(), box=(),
                 battle=0, screen='overworld', stock=(), badges=0xFF, towns=('VIOLET CITY', 'CHERRYGROVE CITY'),
                 cuttable=True, water=True, incompatible=()):
        self.version = version
        self.symbols = gen2ui.tables(version).symbols
        self.memory = BankedMemory()
        self.party = [dict(member) for member in (party or [mon('ONE'), mon('TWO')])]
        self.pockets = {'items': [list(entry) for entry in items], 'balls': [list(entry) for entry in balls],
                        'key': [[item, 1] for item in key], 'tms_hms': sorted(([item, qty] for item, qty in tms),
                                                                            key=lambda entry: TM_INDEX[entry[0]])}
        self.pc = [list(entry) for entry in pc]
        self.box = [dict(member) for member in box]
        self.battle = battle
        self.active = 0
        self.player_move = self.move_num = 0
        self.disabled = 0
        self.player_state = self.bike = 0
        self.map = (10, 1)
        self.badges = badges
        self.stock = list(stock)
        self.towns = list(towns)
        self.cuttable, self.water = cuttable, water
        self.incompatible = set(incompatible)
        self.casting = 0
        self.inputs = []
        self.frame = 0
        self.pocket = 0
        self.index = 0
        self.menu = None
        self.pages = []
        self.after = None
        self.qty = 1
        self.loaded = 0
        self.cur_box = 0
        self.cur_party = 0
        self.selection = 0
        self.daycare = [None, None]
        self.event_flags = bytearray(256)
        self.pokegear = self.card = self.knob = self.music = 0
        self.screen = screen
        if screen == 'battle_menu':
            self.go_battle_menu()
        elif screen == 'mart':
            self.go_mart()
        elif screen == 'pc':
            self.go_pc()
        self.sync()

    # Port ---------------------------------------------------------------------------
    def port(self, **extra):
        def choose(label):
            raise AssertionError(f'Gen 2 run() must not call port.choose ({label})')
        return ControllerPort(self.memory, self.send, choose, lambda: {}, lambda: self.frame,
                              version=self.version, **extra)

    def send(self, button, held=0, released=0):
        self.frame += held + released
        if button is None and self.casting:
            # The rod is out on the overworld. Its message prints after the cast.
            self.casting -= 1
            if not self.casting:
                self.say('Not even a nibble!', then=self.go_overworld)
                self.sync()
        if button is not None:
            self.inputs.append(button)
            getattr(self, 'press_' + self.screen)(button)
            self.sync()
        return True

    # Model helpers ------------------------------------------------------------------
    def pocket_name(self, item):
        return gen2_pocket(item, self.version)

    def count(self, item):
        return sum(qty for entry, qty in self.pockets[self.pocket_name(item)] if entry == item)

    def add(self, item, amount=1, where=None):
        entries = where if where is not None else self.pockets[self.pocket_name(item)]
        for entry in entries:
            if entry[0] == item:
                entry[1] += amount
                break
        else:
            entries.append([item, amount])
            if where is None and self.pocket_name(item) == 'tms_hms':
                entries.sort(key=lambda entry: TM_INDEX[entry[0]])
        entries[:] = [entry for entry in entries if entry[1] > 0]

    def remove(self, item, amount=1, where=None):
        self.add(item, -amount, where)

    def mon_name(self, index):
        return self.party[index]['nick']

    # Screens ------------------------------------------------------------------------
    def say(self, *pages, then):
        self.pages, self.after, self.screen = list(pages), then, 'text'

    def press_text(self, button):
        if button not in ('a', 'b'):
            return
        self.pages.pop(0)
        if not self.pages:
            self.after()

    def open_menu(self, labels, actions, back, *, x0=0, y0=0, text='', index=0, visible=None):
        self.menu = {'labels': list(labels), 'actions': actions, 'back': back, 'x0': x0, 'y0': y0, 'text': text,
                     'index': index, 'visible': visible}
        self.screen = 'menu'

    def yes_no(self, text, yes, no):
        self.open_menu(['YES', 'NO'], {'YES': yes, 'NO': no}, no, x0=14, y0=5, text=text)

    def press_menu(self, button):
        menu = self.menu
        if button == 'up':
            menu['index'] = max(0, menu['index'] - 1)
        elif button == 'down':
            menu['index'] = min(len(menu['labels']) - 1, menu['index'] + 1)
        elif button == 'a':
            menu['actions'].get(menu['labels'][menu['index']], lambda: None)()
        elif button == 'b':
            menu['back']()

    def press_overworld(self, button):
        if button == 'start':
            self.go_pause()

    def go_overworld(self):
        self.screen = 'overworld'

    def go_pause(self):
        gear = ['POKéGEAR'] if self.pokegear else []
        self.open_menu(['POKéDEX', 'POKéMON', 'PACK', *gear, 'KRIS', 'SAVE', 'OPTION', 'EXIT'],
                       {'POKéMON': lambda: self.go_party('field'), 'PACK': lambda: self.go_bag('field'),
                        'POKéGEAR': self.go_pokegear, 'EXIT': self.go_overworld}, self.go_overworld, index=2)

    # Pokégear: the clock card first, the radio card (3) last. The Poké Flute plays at knob 78.
    def go_pokegear(self):
        self.card, self.screen = 0, 'pokegear'

    def press_pokegear(self, button):
        if button == 'right' and self.pokegear & 0x02:
            self.card = min(3, self.card + 1)
        elif button == 'left':
            self.card = max(0, self.card - 1)
        elif button in ('up', 'down') and self.card == 3:
            self.knob = max(0, min(80, self.knob + (1 if button == 'up' else -1)))
            self.music = 0x40 if self.knob == 78 else 0
        elif button == 'b':
            self.go_overworld()

    # Pack
    def entries(self):
        return self.pockets[gen2ui.POCKETS[self.pocket]]

    def go_bag(self, mode):
        self.bag_mode, self.screen, self.index = mode, 'bag', 0

    def leave_bag(self):
        mode = self.bag_mode
        if mode == 'field':
            self.go_pause()
        elif mode == 'battle':
            self.go_battle_menu()
        elif mode == 'sell':
            self.say('Is there anything else I can do?', then=self.go_mart)
        else:
            self.go_players_pc()

    def press_bag(self, button):
        entries = self.entries()
        if button in ('left', 'right'):
            self.pocket = (self.pocket + (1 if button == 'right' else -1)) % 4
            self.index = 0
        elif button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(len(entries), self.index + 1)
        elif button == 'b' or (button == 'a' and self.index == len(entries)):
            self.leave_bag()
        elif button == 'a':
            self.pick_bag(entries[self.index][0], entries[self.index][1])

    def pick_bag(self, item, qty):
        self.item = item
        mode, kind = self.bag_mode, item_kind(item, self.version)
        back = lambda: self.go_bag(mode)  # noqa: E731
        if mode == 'sell':
            if key_item(item, self.version) or kind.kind in ('tm', 'hm'):
                self.say("I can't put a price on that.", then=back)
            else:
                self.go_quantity('sell', qty)
        elif mode == 'deposit':
            if kind.kind in ('tm', 'hm'):
                self.say("TMs can't be stored.", then=back)
            elif key_item(item, self.version):
                self.remove(item)
                self.add(item, 1, self.pc)
                self.say('Stored the item.', then=back)
            else:
                self.go_quantity('deposit', qty)
        elif mode == 'battle':
            self.open_menu(['USE', 'QUIT'], {'USE': self.use, 'QUIT': back}, back, x0=10, y0=6)
        else:
            labels = (['USE', 'QUIT'] if kind.kind in ('tm', 'hm') else ['USE', 'SEL', 'QUIT']
                      if key_item(item, self.version) else ['USE', 'GIVE', 'TOSS', 'SEL', 'QUIT'])
            self.open_menu(labels, {'USE': self.use, 'GIVE': lambda: self.go_party('give'),
                                    'TOSS': lambda: self.go_quantity('toss', qty), 'QUIT': back},
                           back, x0=10, y0=6)

    def use(self):
        item, kind = self.item, item_kind(self.item, self.version)
        if kind.kind == 'ball':
            self.remove(item)
            caught = mon('WILD', species=16)
            self.box.append(caught)
            self.say('KRIS used POKé BALL!', 'Gotcha! WILD was caught.',
                     then=lambda: self.yes_no('Give a nickname to WILD?', yes=self.end_battle, no=self.end_battle))
        elif kind.kind in ('tm', 'hm'):
            self.say('Booted up a TM.', then=lambda: self.yes_no(
                'It contained a move. Teach it to a POKéMON?', yes=lambda: self.go_party('teach'),
                no=lambda: self.go_bag('field')))
        elif kind.target in ('party', 'move'):
            self.go_party('use')
        elif item == ESCAPE_ROPE:
            self.remove(item)
            self.map = (10, 2)
            self.say('KRIS used the ESCAPE ROPE.', then=self.go_overworld)
        elif kind.kind == 'fishing':
            self.go_overworld()
            self.casting = 40 if self.water else 0
        elif item == BICYCLE:
            self.player_state = 0 if self.player_state == 1 else 1
            self.say('KRIS got on the BICYCLE.', then=self.go_overworld)
        else:
            self.say("OAK: KRIS! This isn't the time to use that!", then=lambda: self.go_bag(self.bag_mode))

    # Party
    PROMPTS = {'use': 'Use on which POKéMON?', 'teach': 'Teach which POKéMON?', 'give': 'Give to which POKéMON?',
               'switch': 'Move to where?', 'battle': 'Choose a POKéMON.', 'field': 'Choose a POKéMON.',
               'deleter': 'Choose a POKéMON.', 'daycare': 'Which one should I raise?', 'show': 'Show me which one?'}

    def go_party(self, mode, source=None):
        self.party_mode, self.source, self.screen = mode, source, 'party'
        self.index = 0 if source is None else source

    def press_party(self, button):
        mode = self.party_mode
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(len(self.party) - 1, self.index + 1)
        elif button == 'b':
            if mode == 'field':
                self.go_pause()
            elif mode == 'switch':
                self.go_party('field', self.source)
            elif mode == 'battle':
                if self.party[self.active]['hp']:
                    self.go_battle_menu()
            elif mode in ('daycare', 'show'):
                self.say('Oh, fine then.', then=self.go_overworld)
            else:
                self.go_bag(self.bag_mode)
        elif button == 'a':
            getattr(self, 'party_' + mode)(self.index)

    def party_field(self, slot):
        member = self.party[slot]
        moves = [name for name, move_id in MOVE_IDS.items() if move_id in member['moves']]
        labels = [FIELD_LABELS.get(name, name) for name in moves] + ['STATS', 'SWITCH', 'MOVE', 'ITEM', 'CANCEL']
        actions = {FIELD_LABELS.get(name, name): (lambda name=name: self.field_move(slot, name)) for name in moves}
        actions.update({'SWITCH': lambda: self.go_party('switch', slot), 'ITEM': lambda: self.held_menu(slot),
                        'CANCEL': lambda: self.go_party('field', slot)})
        self.open_menu(labels, actions, lambda: self.go_party('field', slot), x0=0, y0=0, visible=8)

    def party_switch(self, slot):
        source = self.source
        self.party[source], self.party[slot] = self.party[slot], self.party[source]
        self.go_party('field', slot)

    def party_battle(self, slot):
        def switch():
            if slot == self.active:
                self.say(f'{self.mon_name(slot)} is already out.', then=lambda: self.go_party('battle', slot))
                return
            old, self.active = self.active, slot
            self.say(f'{self.mon_name(old)}, come back!', f'Go! {self.mon_name(slot)}!',
                     then=self.go_battle_menu)
        self.open_menu(['SWITCH', 'STATS', 'CANCEL'], {'SWITCH': switch,
                                                      'CANCEL': lambda: self.go_party('battle', slot)},
                       lambda: self.go_party('battle', slot), x0=0, y0=0)

    def party_use(self, slot):
        member, item, kind = self.party[slot], self.item, item_kind(self.item, self.version)
        then = self.enemy_turn if self.battle else (lambda: self.go_bag('field'))
        if kind.target == 'move':
            self.learning = None
            self.move_list(slot, 'pp')
            return
        if member['hp'] == member['max_hp']:
            self.say("It won't have any effect.", then=lambda: self.go_bag(self.bag_mode))
            return
        self.remove(item)
        member['hp'] = member['max_hp']
        self.say(f"{member['nick']}'s HP was restored.", then=then)

    def party_teach(self, slot):
        member = self.party[slot]
        if slot in self.incompatible:
            self.say(f"{member['nick']} is not compatible with the move.", then=lambda: self.go_bag('field'))
            return
        if 0 in member['moves']:
            member['moves'][member['moves'].index(0)] = 99
            self.remove(self.item)
            self.say(f"{member['nick']} learned the move!", then=lambda: self.go_bag('field'))
            return

        def stop():
            self.yes_no('Stop learning the move?', yes=lambda: self.say(
                f"{member['nick']} did not learn the move.", then=lambda: self.go_bag('field')), no=delete)

        def delete():
            self.yes_no('Delete an older move to make room?', yes=lambda: self.move_list(slot, 'learn'), no=stop)
        self.say(f"{member['nick']} is trying to learn a new move.", then=delete)

    def party_deleter(self, slot):
        self.say('Which move should it forget, then?', then=lambda: self.move_list(slot, 'delete'))

    def move_deleter(self):
        def ask():
            self.yes_no('Shall I make a POKéMON forget a move?',
                        yes=lambda: self.say('Which POKéMON?', then=lambda: self.go_party('deleter')),
                        no=lambda: self.say('No? Come visit me again.', then=self.go_overworld))
        self.say("Um... Oh, yes, I'm the MOVE DELETER.", then=ask)

    def day_care(self, parent=0):
        held = self.daycare[parent]

        def deposit(slot):
            self.daycare[parent] = self.party.pop(slot)
            self.say('Come back for it later.', then=self.go_overworld)

        def withdraw():
            self.party.append(self.daycare[parent])
            self.daycare[parent] = None
            self.say('Here you go.', then=self.go_overworld)
        self.party_daycare = deposit
        if held is None:
            self.say("I'm the DAY-CARE MAN.", then=lambda: self.yes_no(
                'Should I raise one of your POKéMON?', yes=lambda: self.go_party('daycare'),
                no=lambda: self.say('Oh, fine then.', then=self.go_overworld)))
        else:
            self.yes_no('Do you want your POKéMON back?', yes=withdraw,
                        no=lambda: self.say('Oh, fine then.', then=self.go_overworld))

    def show_me(self, species, flag):
        def show(slot):
            if self.party[slot]['species'] == species:
                self.event_flags[flag // 8] |= 1 << flag % 8
                self.say('Wow! Thank you!', then=self.go_overworld)
            else:
                self.say("That's not the one.", then=self.go_overworld)
        self.party_show = show
        self.yes_no('Would you show me a POKéMON?', yes=lambda: self.go_party('show'),
                    no=lambda: self.say('Oh well.', then=self.go_overworld))

    def battle_learn(self, slot):
        member = self.party[slot]
        self.cur_party = slot

        def stop():
            self.yes_no('Stop learning the move?', yes=lambda: self.say(
                f"{member['nick']} did not learn the move.", then=self.go_battle_menu), no=delete)

        def delete():
            self.yes_no('Delete an older move to make room?', yes=lambda: self.say(
                'Which move should be forgotten?', then=lambda: self.move_list(slot, 'level')), no=stop)
        self.say(f"{member['nick']} is trying to learn a new move.",
                 then=delete)

    def party_give(self, slot):
        member, item = self.party[slot], self.item

        def hold():
            old = member['item']
            member['item'] = item
            self.remove(item)
            if old:
                self.add(old)
            self.say('Made it hold the item.', then=lambda: self.go_bag('field'))
        if member['item']:
            self.yes_no(f"{member['nick']} is already holding an item. Switch items?", yes=hold,
                        no=lambda: self.go_bag('field'))
        else:
            hold()

    def held_menu(self, slot):
        member = self.party[slot]

        def take():
            if not member['item']:
                self.say(f"{member['nick']} isn't holding anything.", then=lambda: self.go_party('field', slot))
                return
            self.add(member['item'])
            member['item'] = 0
            self.say(f"Took the item from {member['nick']}.", then=lambda: self.go_party('field', slot))
        self.open_menu(['GIVE', 'TAKE', 'QUIT'], {'TAKE': take, 'QUIT': lambda: self.go_party('field', slot)},
                       lambda: self.go_party('field', slot), x0=10, y0=6)

    def move_list(self, slot, mode):
        self.move_slot, self.move_mode, self.index, self.screen = slot, mode, 0, 'move_list'

    def press_move_list(self, button):
        member = self.party[self.move_slot]
        count = sum(1 for move in member['moves'] if move)
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(count - 1, self.index + 1)
        elif button == 'b' and self.move_mode in ('delete', 'level'):
            self.go_overworld() if self.move_mode == 'delete' else self.go_battle_menu()
        elif button == 'b':
            self.go_bag(self.bag_mode)
        elif button == 'a' and self.move_mode == 'delete':
            move = member['moves'][self.index]

            def forget():
                member['moves'] = [m for m in member['moves'] if m != move] + [0]
                self.say('Done! Your POKéMON forgot the move.', then=self.go_overworld)
            self.yes_no(f'Make it forget MOVE {move}?', yes=forget,
                        no=lambda: self.say('No? Come visit me again.', then=self.go_overworld))
        elif button == 'a' and self.move_mode == 'level':
            if member['moves'][self.index] in (15, 19, 57, 70, 148, 250, 127):
                self.say("HM moves can't be forgotten now.", then=lambda: self.move_list(self.move_slot, 'level'))
                return
            member['moves'][self.index] = 99
            self.say('1, 2 and... Poof!', f"{member['nick']} learned the move!", then=self.go_battle_menu)
        elif button == 'a' and self.move_mode == 'pp':
            self.remove(self.item)
            member['pp'][self.index] = 30
            self.say('PP was restored.', then=lambda: self.go_bag(self.bag_mode))
        elif button == 'a':
            member['moves'][self.index] = 99
            self.remove(self.item)
            self.say('1, 2 and... Poof!', f"{member['nick']} learned the move!", then=lambda: self.go_bag('field'))

    # Field moves
    def field_move(self, slot, move):
        nick = self.mon_name(slot)
        back = lambda: self.go_party('field', slot)  # noqa: E731
        if move == 'STRENGTH':
            self.bike |= 1
            self.say(f'{nick} used STRENGTH!', then=self.go_overworld)
        elif move == 'SURF':
            if not self.water:
                self.say("You can't SURF here.", then=back)
                return
            self.player_state = 4
            self.say(f'{nick} used SURF!', then=self.go_overworld)
        elif move == 'FLY':
            self.town, self.screen = 0, 'fly_map'
        elif move == 'CUT' and not self.cuttable:
            self.say("There's nothing to CUT here.", then=back)
        else:
            text = FIELD_TEXT[move]
            self.say(text if text.startswith('A ') else f'{nick} {text}', then=self.go_overworld)

    def press_fly_map(self, button):
        if button == 'up':
            self.town = (self.town + 1) % len(self.towns)
        elif button == 'down':
            self.town = (self.town - 1) % len(self.towns)
        elif button == 'b':
            self.go_party('field')
        elif button == 'a':
            self.map = (self.map[0] + 1 + self.town, 3)
            self.go_overworld()

    # Battle
    def go_battle_menu(self):
        self.screen, self.battle_cursor = 'battle_menu', getattr(self, 'battle_cursor', (9, 14))

    def press_battle_menu(self, button):
        x, y = self.battle_cursor
        if button in ('up', 'down'):
            self.battle_cursor = (x, 14 if button == 'up' else 16)
        elif button in ('left', 'right'):
            self.battle_cursor = (9 if button == 'left' else 15, y)
        elif button == 'a':
            label = gen2ui.BATTLE_MENU[self.battle_cursor]
            if label == 'FIGHT':
                self.index, self.screen = 0, 'move_menu'
            elif label == 'PKMN':
                self.go_party('battle', self.active)
            elif label == 'PACK':
                self.go_bag('battle')
            elif self.battle == 2:
                self.say("No! There's no running from a trainer battle!", then=self.go_battle_menu)
            else:
                self.say('Got away safely!', then=self.end_battle)

    def press_move_menu(self, button):
        member = self.party[self.active]
        count = sum(1 for move in member['moves'] if move)
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(count - 1, self.index + 1)
        elif button == 'b':
            self.go_battle_menu()
        elif button == 'a':
            self.player_move, self.move_num = member['moves'][self.index], self.index
            member['pp'][self.index] -= 1
            self.say(f"{member['nick']} used a move!", then=self.enemy_turn)

    def enemy_turn(self):
        self.say('The foe used TACKLE!', then=self.go_battle_menu)

    def end_battle(self):
        self.battle = 0
        self.go_overworld()

    def switch_prompt(self):
        self.yes_no('Will KRIS change POKéMON?', yes=lambda: self.go_party('battle', self.active),
                    no=self.go_battle_menu)

    # Quantities
    def go_quantity(self, mode, top):
        self.qty_mode, self.qty_top, self.qty, self.screen = mode, top, 1, 'quantity'

    def press_quantity(self, button):
        mode, item = self.qty_mode, self.item
        if button == 'up':
            self.qty = 1 if self.qty >= self.qty_top else self.qty + 1
        elif button == 'down':
            self.qty = self.qty_top if self.qty <= 1 else self.qty - 1
        elif button == 'b':
            self.go_mart_list() if mode == 'buy' else self.go_pc_items() if mode == 'withdraw' else self.go_bag(
                self.bag_mode)
        elif button == 'a':
            amount = self.qty
            if mode == 'toss':
                def toss():
                    self.remove(item, amount)
                    self.say('Threw away the item.', then=lambda: self.go_bag('field'))
                self.yes_no(f'Throw away {amount}?', yes=toss, no=lambda: self.go_bag('field'))
            elif mode == 'buy':
                def buy():
                    self.add(item, amount)
                    self.say('Here you are. Thank you!', then=self.go_mart_list)
                self.yes_no(f'That will be ¥{amount * 300}. OK?', yes=buy, no=self.go_mart_list)
            elif mode == 'sell':
                def sell():
                    self.remove(item, amount)
                    self.say(f'Got ¥{amount * 150} for it.', then=lambda: self.go_bag('sell'))
                self.yes_no(f'I can pay ¥{amount * 150}. OK?', yes=sell, no=lambda: self.go_bag('sell'))
            elif mode == 'deposit':
                self.remove(item, amount)
                self.add(item, amount, self.pc)
                self.say('Stored the item.', then=lambda: self.go_bag('deposit'))
            else:
                self.remove(item, amount, self.pc)
                self.add(item, amount)
                self.say('Withdrew the item.', then=self.go_pc_items)

    # Mart
    def go_mart(self):
        self.open_menu(['BUY', 'SELL', 'QUIT'], {'BUY': self.go_mart_list, 'SELL': lambda: self.go_bag('sell'),
                                                'QUIT': self.go_overworld}, self.go_overworld)

    def go_mart_list(self):
        self.screen, self.index = 'mart_list', 0

    def press_mart_list(self, button):
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(len(self.stock), self.index + 1)
        elif button == 'b' or (button == 'a' and self.index == len(self.stock)):
            self.say('Is there anything else I can do?', then=self.go_mart)
        elif button == 'a':
            self.item = self.stock[self.index]
            self.go_quantity('buy', 99)

    # PC
    def go_pc(self):
        self.open_menu(["BILL'S PC", "KRIS'S PC", 'TURN OFF'],
                       {"BILL'S PC": self.go_bills_pc, "KRIS'S PC": self.go_players_pc,
                        'TURN OFF': self.go_overworld}, self.go_overworld)

    def go_bills_pc(self):
        self.open_menu(['WITHDRAW PKMN', 'DEPOSIT PKMN', 'CHANGE BOX', 'SEE YA!'],
                       {'WITHDRAW PKMN': lambda: self.go_bills_list(1), 'DEPOSIT PKMN': lambda: self.go_bills_list(0),
                        'CHANGE BOX': self.go_box_list, 'SEE YA!': self.go_pc}, self.go_pc)

    def go_box_list(self, index=None):
        labels = [f'BOX{n}' if n > 9 else f'BOX {n}' for n in range(1, 15)]

        def pick():
            chosen = self.menu['index']

            def switch():
                self.cur_box = chosen
                self.say('Saving... Do not turn off the power.', 'KRIS saved the game.', then=self.go_bills_pc)
            self.open_menu(['SWITCH', 'NAME', 'PRINT', 'QUIT'], {
                'SWITCH': lambda: self.yes_no('When you change a BOX, data will be saved. OK?', yes=switch,
                                              no=lambda: self.go_box_list(chosen)),
                'QUIT': lambda: self.go_box_list(chosen)}, lambda: self.go_box_list(chosen), x0=11, y0=4)
        self.open_menu(labels, {label: pick for label in labels}, self.go_bills_pc,
                       index=self.cur_box if index is None else index, visible=5)
        self.menu['box_list'] = True

    def go_players_pc(self):
        self.open_menu(['WITHDRAW ITEM', 'DEPOSIT ITEM', 'TOSS ITEM', 'MAIL BOX', 'DECORATION', 'LOG OFF'],
                       {'WITHDRAW ITEM': self.go_pc_items, 'DEPOSIT ITEM': lambda: self.go_bag('deposit'),
                        'LOG OFF': self.go_pc}, self.go_pc)

    def bills_mons(self):
        return self.box if self.loaded else self.party

    def go_bills_list(self, loaded, index=0):
        self.loaded, self.index, self.screen = loaded, index, 'bills_list'

    def press_bills_list(self, button):
        mons = self.bills_mons()
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(len(mons), self.index + 1)
        elif button == 'b' or (button == 'a' and self.index == len(mons)):
            self.go_bills_pc()
        elif button == 'a':
            self.pc_action(self.index)

    def pc_action(self, index):
        loaded = self.loaded
        back = lambda: self.go_bills_list(loaded, index)  # noqa: E731
        member = self.bills_mons()[index]

        def move():
            if loaded == 0:
                if len(self.box) >= 20:
                    self.say('The BOX is full.', then=back)
                    return
                self.box.append(self.party.pop(index))
                self.say(f"Stored {member['nick']}.", then=lambda: self.go_bills_list(0))
            else:
                if len(self.party) >= 6:
                    self.say("You can't take any more POKéMON.", then=back)
                    return
                self.party.append(self.box.pop(index))
                self.say(f"Got {member['nick']}.", then=lambda: self.go_bills_list(1))

        def release():
            self.bills_mons().pop(index)
            self.say(f"{member['nick']} was released.", then=lambda: self.go_bills_list(loaded))
        self.open_menu(['DEPOSIT' if loaded == 0 else 'WITHDRAW', 'STATS', 'RELEASE', 'CANCEL'],
                       {'DEPOSIT': move, 'WITHDRAW': move, 'CANCEL': back,
                        'RELEASE': lambda: self.yes_no(f"Release {member['nick']}? Once released, it is gone.",
                                                       yes=release, no=back)}, back, x0=8, y0=6)

    def go_pc_items(self):
        self.screen, self.index = 'pc_items', 0

    def press_pc_items(self, button):
        if button == 'up':
            self.index = max(0, self.index - 1)
        elif button == 'down':
            self.index = min(len(self.pc), self.index + 1)
        elif button == 'b' or (button == 'a' and self.index == len(self.pc)):
            self.go_players_pc()
        elif button == 'a':
            self.item, qty = self.pc[self.index]
            if key_item(self.item, self.version):
                self.remove(self.item, 1, self.pc)
                self.add(self.item)
                self.say('Withdrew the item.', then=self.go_pc_items)
            else:
                self.go_quantity('withdraw', qty)

    # Memory -------------------------------------------------------------------------
    def put(self, symbol, data, offset=0):
        bank, address = self.symbols[symbol]
        self.memory.banks[bank][address + offset:address + offset + len(data)] = bytes(data)

    def sync(self):
        put, party = self.put, self.party
        put('wPartyCount', [len(party)])
        put('wPartySpecies', [0xFD if member['egg'] else member['species'] for member in party] + [0xFF])
        put('wPartyMons', b''.join(struct(member) for member in party).ljust(48 * 6, b'\0'))
        put('wPartyMonNicknames', b''.join(name(member['nick'], self.version) for member in party).ljust(66, b'\x50'))
        put('wPartyMonOTs', name('KRIS', self.version) * 6)
        for symbol, entries in (('wNumItems', self.pockets['items']), ('wNumBalls', self.pockets['balls']),
                                ('wNumPCItems', self.pc)):
            put(symbol, [len(entries)] + [value for entry in entries for value in entry] + [0xFF])
        keys = [item for item, _ in self.pockets['key']]
        put('wNumKeyItems', [len(keys)] + keys + [0xFF])
        tms = [0] * 57
        for item, qty in self.pockets['tms_hms']:
            tms[TM_INDEX[item]] = qty
        put('wTMsHMs', tms)
        box = bytearray(1102)
        box[0] = len(self.box)
        box[1:2 + len(self.box)] = bytes([0xFD if m['egg'] else m['species'] for m in self.box] + [0xFF])
        for index, member in enumerate(self.box):
            box[22 + 32 * index:54 + 32 * index] = struct(member, party=False)
            box[22 + 32 * 20 + 11 * index:22 + 32 * 20 + 11 * index + 11] = name('KRIS', self.version)
            box[22 + 43 * 20 + 11 * index:22 + 43 * 20 + 11 * index + 11] = name(member['nick'], self.version)
        put('wCurBox', [self.cur_box])
        put('wCurPartyMon', [self.cur_party])
        if self.screen == 'menu' and self.menu.get('box_list'):
            put('wMenuSelection', [self.menu['index'] + 1])
        put('sBox', box)
        put('wBattleMode', [self.battle])
        active = party[self.active] if self.active < len(party) else mon('NONE')
        put('wCurBattleMon', [self.active])
        put('wBattleMonMoves', active['moves'])
        put('wBattleMonPP', active['pp'])
        put('wBattleMonHP', active['hp'].to_bytes(2, 'big'))
        put('wCurPlayerMove', [self.player_move])
        put('wDisabledMove', [self.disabled])
        put('wPlayerDisableCount', [0x13 if self.disabled else 0])
        put('wCurMoveNum', [self.move_num])
        put('wPlayerState', [self.player_state])
        put('wBikeFlags', [self.bike])
        put('wMapGroup', [self.map[0]])
        put('wMapNumber', [self.map[1]])
        put('wJohtoBadges', [self.badges])
        put('wCurMartCount', [len(self.stock)])
        put('wCurMartItems', self.stock + [0xFF])
        put('wItemQuantityChange', [self.qty])
        put('wCurPocket', [self.pocket])
        put('wBillsPC_LoadedBox', [self.loaded])
        put('wWindowStackSize', [0 if self.screen == 'overworld' else 1])
        for index, held in enumerate(self.daycare, 1):
            put('wDayCareMan' if index == 1 else 'wDayCareLady', [1 if held else 0])
            put(f'wBreedMon{index}', struct(held, party=False) if held else bytes(32))
            put(f'wBreedMon{index}Nickname', name(held['nick'], self.version) if held else bytes(11))
        put('wEventFlags', self.event_flags)
        put('wPokegearFlags', [self.pokegear])
        if self.screen == 'pokegear':
            # The card byte is shared with other menus, so it is written only while the Pokégear is open.
            put('wPokegearCard', [self.card])
        put('wRadioTuningKnob', [self.knob])
        put('wMapMusic', [self.music])
        self.tiles = bytearray([SPACE] * 360)
        getattr(self, 'draw_' + self.screen)()
        put('wTilemap', self.tiles)

    # Drawing ------------------------------------------------------------------------
    def text_at(self, x, y, text):
        data = encode(text, self.version)
        self.tiles[y * 20 + x:y * 20 + x + len(data)] = data

    def tile(self, x, y, value):
        self.tiles[y * 20 + x] = value

    def box_at(self, x0, y0, x1, y1):
        for x in range(x0, x1 + 1):
            self.tile(x, y0, H)
            self.tile(x, y1, H)
        for y in range(y0, y1 + 1):
            self.tile(x0, y, V)
            self.tile(x1, y, V)
        self.tile(x0, y0, TL)
        self.tile(x1, y0, TR)
        self.tile(x0, y1, BL)
        self.tile(x1, y1, BR)

    def text_box(self, text, top=12, more=False):
        self.box_at(0, top, 19, 17)
        rows = (14, 16) if top == 12 else (15, 16)
        for row, line in zip(rows, wrap(text)):
            self.text_at(1, row, line)
        if more:
            self.tile(18, 17, MORE)

    def list_rows(self, entries, x, y0, visible, cursor_x=None):
        """Draw a scrolling list and set the menu bytes. Returns (scroll, cursor row 1 based)."""
        scroll = max(0, self.index - visible + 1)
        for row in range(visible):
            index = scroll + row
            if index < len(entries):
                self.text_at(x, y0 + 2 * row, entries[index])
            elif index == len(entries):
                self.text_at(x, y0 + 2 * row, 'CANCEL')
        cursor = self.index - scroll + 1
        if cursor_x is not None:
            self.tile(cursor_x, y0 + 2 * (cursor - 1), CURSOR)
        self.put('wMenuScrollPosition', [scroll])
        self.put('wMenuCursorY', [cursor])
        return scroll, cursor

    def draw_overworld(self):
        pass

    def draw_pokegear(self):
        self.text_at(1, 1, 'SUN 10:00')
        if self.card == 3:
            self.text_at(1, 9, f'TUNING {self.knob}')

    def draw_text(self):
        self.text_box(self.pages[0], more=True)

    def draw_menu(self):
        menu = self.menu
        x0, y0, labels = menu['x0'], menu['y0'], menu['labels']
        # A menu longer than its window scrolls to keep the cursor in view.
        top = max(0, menu['index'] - menu['visible'] + 1) if menu['visible'] else 0
        labels = labels[top:top + menu['visible']] if menu['visible'] else labels
        limit = 11 if menu['text'] else 17
        step = 2 if y0 + 2 * len(labels) + 2 <= limit else 1
        y0 = min(y0, limit - step * len(labels) - step)
        self.box_at(x0, y0, 19, y0 + step * len(labels) + step)
        for row, label in enumerate(labels):
            self.text_at(x0 + 2, y0 + step + step * row, label)
        self.tile(x0 + 1, y0 + step + step * (menu['index'] - top), CURSOR)
        if menu['text']:
            self.text_box(menu['text'])
        self.put('wMenuCursorY', [menu['index'] - top + 1])

    def draw_party(self):
        for index, member in enumerate(self.party):
            self.text_at(3, 2 * index + 1, 'EGG' if member['egg'] else member['nick'])
        self.tile(0, 2 * self.index + 1, CURSOR)
        self.text_box(self.PROMPTS[self.party_mode], top=14)
        self.put('wMenuCursorY', [self.index + 1])

    def draw_bag(self):
        scroll, _ = self.list_rows([f'ITEM {item:02X}' for item, _ in self.entries()], 8, 2, 5, cursor_x=7)
        self.put('wTMHMPocketScrollPosition', [scroll])

    def draw_quantity(self):
        self.box_at(14, 9, 19, 11)
        self.text_at(15, 10, f'×{self.qty:02d}')

    def draw_move_list(self):
        member = self.party[self.move_slot]
        self.box_at(5, 2, 19, 11)
        for row, move in enumerate(move for move in member['moves'] if move):
            self.text_at(7, 4 + 2 * row, f'MOVE {move}')
        self.tile(6, 4 + 2 * self.index, CURSOR)
        self.put('wMenuCursorY', [self.index + 1])

    def draw_fly_map(self):
        self.text_at(2, 0, 'Where?')
        self.text_at(2, 1, self.towns[self.town])

    def draw_battle_menu(self):
        self.box_at(8, 12, 19, 17)
        for (x, y), label in gen2ui.BATTLE_MENU.items():
            self.text_at(x + 1, y, label)
        self.tile(*self.battle_cursor, CURSOR)

    def draw_move_menu(self):
        member = self.party[self.active]
        self.box_at(0, 7, 9, 11)
        moves = [move for move in member['moves'] if move]
        self.text_at(1, 9, 'Disabled!') if moves[self.index] == self.disabled else self.text_at(1, 8, 'TYPE/')
        self.box_at(4, 12, 19, 17)
        for row, move in enumerate(move for move in member['moves'] if move):
            self.text_at(6, 13 + row, f'MOVE {move}')
        self.tile(5, 13 + self.index, CURSOR)
        self.put('wMenuCursorY', [self.index + 1])

    def draw_mart_list(self):
        self.box_at(0, 0, 10, 2)
        self.text_at(1, 1, '¥3000')
        self.list_rows([f'ITEM {item:02X}' for item in self.stock], 2, 4, 4, cursor_x=1)

    def draw_pc_items(self):
        self.box_at(0, 0, 19, 11)
        self.list_rows([f'ITEM {item:02X}' for item, _ in self.pc], 5, 2, 4, cursor_x=4)

    def draw_bills_list(self):
        self.box_at(8, 0, 19, 2)
        self.text_at(9, 1, 'BOX 1')
        mons = self.bills_mons()
        scroll = max(0, self.index - 4)
        for row in range(5):
            if scroll + row < len(mons):
                self.text_at(9, 4 + 2 * row, mons[scroll + row]['nick'])
        self.put('wBillsPC_CursorPosition', [self.index - scroll])
        self.put('wBillsPC_ScrollPosition', [scroll])


def done(result):
    return result['shortcut']['completed'] and result['shortcut']['settled']


def refused(result, game, text):
    assert text in result['outcome'], result
    assert not result['shortcut']['completed'] and game.inputs == []


# Items ----------------------------------------------------------------------------------

@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_field_heal_turns_to_the_pocket_and_finishes_at_the_overworld(version):
    game = Game2(version, items=[(ESCAPE_ROPE, 1), (POTION, 2)], balls=[(POKE_BALL, 3)])
    game.pocket = 1
    result = use_item(game.port(), POTION, 1)
    assert done(result) and result['shortcut']['item_consumed'], result
    assert game.count(POTION) == 1 and game.party[1]['hp'] == 50
    assert game.screen == 'overworld' and 'left' in game.inputs


def test_berry_and_battle_heal_rest_at_the_battle_menu():
    game = Game2(items=[(BERRY, 1)], battle=1, screen='battle_menu')
    result = use_item(game.port(), BERRY, 0)
    assert done(result) and game.count(BERRY) == 0 and game.screen == 'battle_menu'


def test_no_effect_is_reported_without_a_second_use():
    game = Game2(items=[(POTION, 2)], party=[mon('ONE', hp=50)])
    result = use_item(game.port(), POTION, 0)
    assert not result['shortcut']['completed'] and 'refused' in result['outcome']
    assert game.count(POTION) == 2 and game.screen == 'overworld' and result['shortcut']['settled']


def test_pp_item_picks_the_move():
    game = Game2(items=[(ETHER, 1)], party=[mon('ONE', moves=(33, 45, 10, 0))])
    game.party[0]['pp'] = [30, 30, 2, 0]
    assert done(use_item(game.port(), ETHER, 0, 2))
    assert game.party[0]['pp'][2] == 30 and game.count(ETHER) == 0


def test_escape_rope_has_no_target():
    game = Game2(items=[(ESCAPE_ROPE, 1)])
    result = use_item(game.port(), ESCAPE_ROPE)
    assert done(result) and game.map == (10, 2) and game.screen == 'overworld'


def test_a_rod_waits_on_the_overworld_for_the_cast():
    game = Game2(key=[SUPER_ROD])
    result = use_item(game.port(), SUPER_ROD)
    assert done(result) and result['outcome'] == 'Used the rod. Nothing bit.', result
    assert game.screen == 'overworld' and game.inputs.count('a') == 4


def test_a_rod_with_no_message_stops_without_a_second_cast():
    game = Game2(key=[SUPER_ROD], water=False)
    result = use_item(game.port(), SUPER_ROD)
    assert not result['shortcut']['completed'] and 'without a confirmed effect' in result['outcome'], result
    assert game.screen == 'overworld'


def test_tm_into_an_empty_slot_and_over_a_full_moveset():
    game = Game2(tms=[(TM01, 1)])
    assert done(use_item(game.port(), TM01, 0))
    assert game.party[0]['moves'][2] == 99 and game.count(TM01) == 0
    game = Game2(tms=[(TM01, 2)], party=[mon('ONE', moves=(33, 45, 10, 11))])
    result = use_item(game.port(), TM01, 0, forget_move=1)
    assert done(result) and game.party[0]['moves'] == [33, 99, 10, 11] and game.count(TM01) == 1


def test_tm_keep_and_refusals():
    game = Game2(tms=[(TM01, 1)], party=[mon('ONE', moves=(33, 45, 10, 11))])
    result = use_item(game.port(), TM01, 0, forget_move='keep')
    assert 'Kept the old moves' in result['outcome'] and not result['shortcut']['completed']
    assert game.count(TM01) == 1 and game.screen == 'overworld'
    game = Game2(tms=[(TM01, 1)], party=[mon('ONE', moves=(33, 45, 10, 11))])
    refused(use_item(game.port(), TM01, 0), game, 'forget_move')
    game = Game2(tms=[(TM01, 1)], party=[mon('ONE', moves=(33, 15, 10, 11))])
    refused(use_item(game.port(), TM01, 0, forget_move=1), game, 'HM moves')
    game = Game2(tms=[(TM01, 1)], incompatible={0})
    result = use_item(game.port(), TM01, 0)
    assert not result['shortcut']['completed'] and 'compatible' in result['outcome']


def test_ball_catch_answers_no_to_the_nickname():
    game = Game2(balls=[(POKE_BALL, 1)], battle=1, screen='battle_menu')
    result = use_item(game.port(), POKE_BALL)
    assert done(result) and game.count(POKE_BALL) == 0 and game.screen == 'overworld'
    assert [member['nick'] for member in game.box] == ['WILD']


def test_item_prechecks_send_nothing():
    game = Game2(items=[(POTION, 1), (LEFTOVERS, 1)], balls=[(POKE_BALL, 1)])
    refused(use_item(game.port(), 0x10, 0), game, 'not in the bag')
    refused(use_item(game.port(), POKE_BALL), game, 'cannot be used here')
    refused(use_item(game.port(), LEFTOVERS), game, 'give_item')
    refused(use_item(game.port(), POTION, 3), game, 'unavailable')
    game = Game2(balls=[(POKE_BALL, 1)], battle=2, screen='battle_menu')
    refused(use_item(game.port(), POKE_BALL), game, 'wild battles')
    game = Game2(items=[(ESCAPE_ROPE, 1)], battle=1, screen='battle_menu')
    refused(use_item(game.port(), ESCAPE_ROPE), game, 'cannot be used in battle')
    game = Game2(items=[(POTION, 1)], party=[mon('EGG', egg=True)])
    refused(use_item(game.port(), POTION, 0), game, 'Egg')


def test_toss_sets_the_quantity_and_confirms():
    game = Game2(items=[(POTION, 9)])
    result = toss_item(game.port(), POTION, 7)
    assert done(result) and game.count(POTION) == 2 and game.screen == 'overworld'
    assert game.inputs.count('down') >= 3
    game = Game2(items=[(POTION, 2)], key=[BICYCLE])
    refused(toss_item(game.port(), POTION, 3), game, 'Only 2')
    refused(toss_item(game.port(), BICYCLE), game, 'too important')


# Held items -----------------------------------------------------------------------------

def test_give_and_take_a_held_item():
    game = Game2(items=[(LEFTOVERS, 1), (POTION, 1)])
    result = give_item(game.port(), LEFTOVERS, 1)
    assert done(result) and game.party[1]['item'] == LEFTOVERS and game.count(LEFTOVERS) == 0
    result = take_item(game.port(), 1)
    assert done(result) and game.party[1]['item'] == 0 and game.count(LEFTOVERS) == 1
    assert result['shortcut']['item_id'] == LEFTOVERS and game.screen == 'overworld'


def test_give_swaps_only_when_asked():
    game = Game2(items=[(POTION, 1)], party=[mon('ONE', item=LEFTOVERS), mon('TWO')])
    refused(give_item(game.port(), POTION, 0), game, 'swap=True')
    result = give_item(game.port(), POTION, 0, swap=True)
    assert done(result) and game.party[0]['item'] == POTION and game.count(LEFTOVERS) == 1
    assert result['shortcut']['returned_item'] == LEFTOVERS


def test_held_item_prechecks_send_nothing():
    game = Game2(items=[(POTION, 1), (MAIL, 1)], key=[BICYCLE], tms=[(TM01, 1)],
                 party=[mon('ONE'), mon('EGG', egg=True)])
    refused(give_item(game.port(), BICYCLE, 0), game, 'cannot be held')
    refused(give_item(game.port(), TM01, 0), game, 'cannot be held')
    refused(give_item(game.port(), MAIL, 0), game, 'Mail')
    refused(give_item(game.port(), POTION, 1), game, 'Egg')
    refused(take_item(game.port(), 0), game, 'not holding')
    game = Game2(items=[(POTION, 1)], battle=1, screen='battle_menu')
    refused(give_item(game.port(), POTION, 0), game, 'outside battle')


# Party and battle -----------------------------------------------------------------------

def test_switch_in_battle_from_the_menu_and_from_the_switch_prompt():
    game = Game2(battle=2, screen='battle_menu', party=[mon('ONE'), mon('TWO'), mon('SIX')])
    result = switch_pokemon(game.port(), 2)
    assert done(result) and game.active == 2 and game.screen == 'battle_menu'
    game.switch_prompt()
    game.sync()
    assert current_screen(game.memory, 'crystal') == 'switch_prompt'
    game.inputs.clear()
    assert done(switch_pokemon(game.port(), 1)) and game.active == 1
    assert game.inputs[0] == 'a'
    game.inputs.clear()
    refused(switch_pokemon(game.port(), 1), game, 'already active')


def test_forced_switch_waits_for_the_party_screen_under_which_pkmn():
    game = Game2(battle=1, party=[mon('ONE', hp=0), mon('TWO'), mon('SIX')])
    waits = []

    def press_text(button):
        waits.append(button)
        if button is None and len(waits) >= 3:
            game.go_party('battle', 0)
    game.press_text = press_text
    send = game.send

    def send_any(button, held=0, released=0):
        if button is None and game.screen == 'text':
            game.press_text(None)
            game.sync()
        return send(button, held, released)
    game.send = send_any
    game.say('Which PKMN?', then=lambda: None)
    game.sync()
    result = switch_pokemon(game.port(), 1)
    assert done(result) and game.active == 1
    assert game.inputs[:2] == ['down', 'a']


def test_switch_and_reorder_in_the_field():
    game = Game2(party=[mon('ONE'), mon('TWO'), mon('SIX')])
    assert done(switch_pokemon(game.port(), 2))
    assert [member['nick'] for member in game.party] == ['SIX', 'TWO', 'ONE']
    assert done(reorder_party(game.port(), 1, 2))
    assert [member['nick'] for member in game.party] == ['SIX', 'ONE', 'TWO'] and game.screen == 'overworld'
    game.inputs.clear()
    refused(switch_pokemon(game.port(), 0), game, 'already the lead')
    game = Game2(battle=1, screen='battle_menu')
    refused(reorder_party(game.port(), 0, 1), game, 'outside battle')


def test_reorder_a_member_whose_party_submenu_scrolls():
    # Four field moves push CANCEL below the submenu window, as on the cartridge.
    game = Game2(party=[mon('ONE'), mon('SURFER', moves=(57, 250, 15, 70))])
    assert done(reorder_party(game.port(), 1, 0))
    assert [member['nick'] for member in game.party] == ['SURFER', 'ONE'] and game.screen == 'overworld'


def test_choose_move_from_the_battle_menu():
    game = Game2(battle=1, screen='battle_menu', party=[mon('ONE', moves=(33, 45, 10, 0))])
    game.party[0]['pp'] = [30, 30, 5, 0]
    game.sync()
    result = choose_move(game.port(), 2)
    assert done(result) and (game.player_move, game.move_num) == (10, 2)
    assert game.screen == 'battle_menu' and result['shortcut']['move_id'] == 10
    game.party[0]['pp'] = [0, 30, 30, 0]
    game.sync()
    game.inputs.clear()
    refused(choose_move(game.port(), 0), game, 'no PP')
    refused(choose_move(game.port(), 3), game, 'empty')
    game = Game2()
    refused(choose_move(game.port(), 0), game, 'Not in battle')


def test_choose_move_past_a_disabled_move_and_refuse_it():
    game = Game2(battle=1, screen='battle_menu', party=[mon('ONE', moves=(33, 45, 10, 0))])
    game.disabled = 33
    game.sync()
    result = choose_move(game.port(), 1)
    assert done(result) and (game.player_move, game.move_num) == (45, 1)
    game.inputs.clear()
    refused(choose_move(game.port(), 0), game, 'disabled')


def test_choose_move_steps_without_a_port():
    game = Game2(battle=1, screen='battle_menu')
    machine = ChooseMove(1, version='crystal')
    for _ in range(200):
        action = machine.step(game.memory)
        if hasattr(action, 'outcome'):
            break
        game.send(action, 8, 24)
    assert action.completed and game.move_num == 1


def test_run_away_and_trainer_refusal():
    game = Game2(battle=1, screen='battle_menu')
    result = run_away(game.port())
    assert done(result) and result['shortcut']['escaped'] and game.screen == 'overworld'
    game = Game2(battle=2, screen='battle_menu')
    refused(run_away(game.port()), game, 'trainer')


# Field moves ----------------------------------------------------------------------------

@pytest.mark.parametrize('move', ['STRENGTH', 'SURF', 'CUT', 'FLASH', 'WHIRLPOOL', 'WATERFALL', 'ROCKSMASH',
                                  'HEADBUTT'])
def test_field_moves(move):
    game = Game2(party=[mon('ONE'), mon('TWO', moves=(33, MOVE_IDS[move], 0, 0))])
    result = use_field_move(game.port(), move, 1)
    assert done(result) and game.screen == 'overworld', result
    if move == 'STRENGTH':
        assert game.bike & 1
    if move == 'SURF':
        assert game.player_state == 4


def test_field_move_refusals():
    game = Game2(cuttable=False, party=[mon('ONE', moves=(15, 57, 0, 0))])
    result = use_field_move(game.port(), 'CUT', 0)
    assert 'refused' in result['outcome'] and not result['shortcut']['completed'] and game.screen == 'overworld'
    game = Game2(water=False, party=[mon('ONE', moves=(15, 57, 0, 0))])
    result = use_field_move(game.port(), 'SURF', 0)
    assert 'refused' in result['outcome'] and game.player_state == 0
    game = Game2(badges=0, party=[mon('ONE', moves=(15, 0, 0, 0))])
    refused(use_field_move(game.port(), 'CUT', 0), game, 'badge')
    refused(use_field_move(game.port(), 'SURF', 0), game, 'does not know')
    game = Game2(battle=1, screen='battle_menu', party=[mon('ONE', moves=(15, 0, 0, 0))])
    refused(use_field_move(game.port(), 'CUT', 0), game, 'outside battle')


def test_fly_scrolls_to_the_named_town():
    game = Game2(party=[mon('ONE', moves=(19, 0, 0, 0))])
    result = use_field_move(game.port(), 'FLY', 0, 'Cherrygrove City')
    assert done(result) and game.map == (12, 3) and game.screen == 'overworld'
    game = Game2(party=[mon('ONE', moves=(19, 0, 0, 0))])
    result = use_field_move(game.port(), 'FLY', 0, 'Goldenrod City')
    assert 'VIOLET CITY, CHERRYGROVE CITY' in result['outcome'] and game.screen == 'overworld'


def test_fly_needs_the_storm_badge_not_the_mineral_badge():
    # Johto badge bits: MINERALBADGE is 4 and STORMBADGE is 5.
    game = Game2(badges=0x2F, party=[mon('ONE', moves=(19, 0, 0, 0))])
    assert done(use_field_move(game.port(), 'FLY', 0, 'Cherrygrove City'))
    game = Game2(badges=0x1F, party=[mon('ONE', moves=(19, 0, 0, 0))])
    refused(use_field_move(game.port(), 'FLY', 0, 'Cherrygrove City'), game, 'badge')


# Mart -----------------------------------------------------------------------------------

@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_buy_and_sell_at_a_mart(version):
    game = Game2(version, screen='mart', stock=[POKE_BALL, POTION, ESCAPE_ROPE, 0x0E, 0x09], items=[(POTION, 1)])
    result = buy_item(game.port(), 0x09, 3)
    assert done(result) and game.count(0x09) == 3 and game.screen == 'menu'
    assert current_screen(game.memory, version) == 'mart'
    result = sell_item(game.port(), POTION)
    assert done(result) and game.count(POTION) == 0
    assert current_screen(game.memory, version) == 'mart'


def test_mart_refusals():
    game = Game2(screen='mart', stock=[POKE_BALL], items=[(POTION, 1)], key=[BICYCLE])
    result = buy_item(game.port(), POTION)
    assert 'does not sell' in result['outcome'] and result['shortcut']['settled']
    assert current_screen(game.memory, 'crystal') == 'mart'
    game.inputs.clear()
    refused(sell_item(game.port(), BICYCLE), game, 'cannot be sold')
    refused(sell_item(game.port(), POTION, 2), game, 'Only 1')
    game = Game2(items=[(POTION, 1)])
    refused(buy_item(game.port(), POTION), game, 'mart')
    game = Game2(screen='mart', stock=[POTION], items=[(POTION, 99)])
    refused(buy_item(game.port(), POTION), game, 'more than 99')


# PC -------------------------------------------------------------------------------------

def pc_game(**options):
    options.setdefault('party', [mon('ONE'), mon('TWO'), mon('SIX')])
    options.setdefault('box', [mon('ROCK'), mon('BIRD')])
    return Game2(screen='pc', **options)


def test_deposit_withdraw_and_release():
    game = pc_game()
    result = deposit_pokemon(game.port(), 1)
    assert done(result) and [m['nick'] for m in game.box] == ['ROCK', 'BIRD', 'TWO']
    assert current_screen(game.memory, 'crystal') == 'pc'
    result = withdraw_pokemon(game.port(), 1)
    assert done(result) and [m['nick'] for m in game.party] == ['ONE', 'SIX', 'BIRD']
    with pytest.raises(ValueError):
        release_pokemon(game.port(), 0)
    result = release_pokemon(game.port(), 1, allow_release=True)
    assert done(result) and [m['nick'] for m in game.box] == ['ROCK'] and game.screen == 'menu'


def test_pc_prechecks_send_nothing():
    game = pc_game(box=[mon(f'M{i}') for i in range(20)])
    refused(deposit_pokemon(game.port(), 0), game, 'full')
    game = pc_game(party=[mon(f'P{i}') for i in range(6)])
    refused(withdraw_pokemon(game.port(), 0), game, 'party is full')
    refused(withdraw_pokemon(game.port(), 5), game, 'No Pokemon')
    game = pc_game(party=[mon('ONE')])
    refused(deposit_pokemon(game.port(), 0), game, 'last')
    game = pc_game(party=[mon('ONE'), mon('TWO', hp=0)])
    refused(deposit_pokemon(game.port(), 0), game, 'No other')
    game = pc_game(box=[mon('EGG', egg=True)])
    refused(release_pokemon(game.port(), 0, allow_release=True), game, 'Eggs')
    game = Game2()
    refused(deposit_pokemon(game.port(), 0), game, 'PC menu')


def test_item_pc_deposit_and_withdraw():
    game = pc_game(items=[(POTION, 5)], key=[BICYCLE], pc=[(SUPER_POTION, 4)])
    assert done(deposit_item(game.port(), POTION, 3)) and game.count(POTION) == 2
    assert [POTION, 3] in game.pc and current_screen(game.memory, 'crystal') == 'pc'
    assert done(deposit_item(game.port(), BICYCLE)) and game.count(BICYCLE) == 0 and [BICYCLE, 1] in game.pc
    assert done(withdraw_item(game.port(), SUPER_POTION, 2)) and game.count(SUPER_POTION) == 2
    assert done(withdraw_item(game.port(), BICYCLE)) and game.count(BICYCLE) == 1
    game.inputs.clear()
    refused(withdraw_item(game.port(), ETHER), game, 'not stored')
    refused(deposit_item(game.port(), POTION, 3), game, 'Only 2')
    game = pc_game(tms=[(TM01, 1)])
    refused(deposit_item(game.port(), TM01), game, 'TMs and HMs')


# Queries --------------------------------------------------------------------------------

def test_queries_and_screens_read_gen2_memory():
    game = Game2(items=[(POTION, 2)], balls=[(POKE_BALL, 1)], tms=[(TM01, 1), (HM01, 1)],
                 party=[mon('ONE', item=LEFTOVERS), mon('TWO')], box=[mon('ROCK')])
    assert current_screen(game.memory, 'crystal') == 'overworld'
    party = list_party(game.memory, 'crystal')
    assert [(m['nick'], m['held_item'], m['hp'], m['max_hp']) for m in party] == [('ONE', LEFTOVERS, 40, 50),
                                                                                  ('TWO', 0, 40, 50)]
    assert [(m['index'], m['id'], m['pp']) for m in list_moves(game.memory, 0, 'crystal')] == [(0, 33, 30),
                                                                                             (1, 45, 30)]
    assert [m['nick'] for m in list_box(game.memory, version='crystal')] == ['ROCK']
    for screen, expected in (('pause', 'pause'), ('battle', 'battle_menu'), ('mart', 'mart'), ('pc', 'pc')):
        game = Game2(battle=1 if screen == 'battle' else 0,
                     screen={'battle': 'battle_menu'}.get(screen, screen if screen != 'pause' else 'overworld'))
        if screen == 'pause':
            game.go_pause()
            game.sync()
        assert current_screen(game.memory, 'crystal') == expected



@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_pre_game_screens_read_the_play_time_flag(version):
    bank, timer = (0, 0xCFBC) if version == 'crystal' else (1, 0xD8B8)
    game = Game2(version)
    game.sync()
    assert current_screen(game.memory, version) == 'overworld'
    # A soft reset leaves the last game in WRAM but clears the play time flag.
    game.memory.banks[bank][timer] = 0
    assert current_screen(game.memory, version) == 'title'
    # hMapAnims only runs in the overworld, so an animating map is never the title.
    anims = 0xFFDE if version == 'crystal' else 0xFFE0
    game.memory.banks[0][anims] = 1
    assert current_screen(game.memory, version) == 'overworld'
    game.memory.banks[0][anims] = 0
    game.open_menu(['CONTINUE', 'NEW GAME', 'OPTION'], {}, game.go_overworld)
    game.sync()
    assert current_screen(game.memory, version) == 'main_menu'
    # Title art can show a cursor tile beside stray font tiles.
    game.open_menu(['ABCDEF', 'GHIJKL'], {}, game.go_overworld)
    game.sync()
    assert current_screen(game.memory, version) == 'title'
    game.memory.banks[bank][timer] = 1
    assert current_screen(game.memory, version) == 'menu'


def test_list_items_reads_every_pocket(monkeypatch):
    from pokecore.shortcuts import queries
    monkeypatch.setattr(queries, 'item_names', lambda memory, version: {POTION: 'POTION'})
    game = Game2(items=[(POTION, 2)], balls=[(POKE_BALL, 1)], key=[BICYCLE], tms=[(TM01, 1)])
    items = list_items(game.memory, 'crystal')
    assert [(i['id'], i['pocket'], i['kind'], i['usable']) for i in items] == [
        (POTION, 'items', 'heal', True), (POKE_BALL, 'balls', 'ball', False), (BICYCLE, 'key', 'key', True),
        (TM01, 'tms_hms', 'tm', True)]
    assert items[0]['name'] == 'POTION'


# Box change, learning and the Move Deleter -----------------------------------------------

@pytest.mark.parametrize('box', [3, 12])
def test_change_box_switches_and_saves(box):
    game = Game2(screen='pc')
    result = change_box(game.port(), box)
    assert done(result) and game.cur_box == box and game.screen == 'menu', result
    assert current_screen(game.memory, 'crystal') == 'pc' and result['shortcut']['box'] == box + 1
    assert game.inputs.count('a') >= 4


def test_change_box_refuses_the_current_box_and_bad_numbers():
    game = Game2(screen='pc')
    refused(change_box(game.port(), 0), game, 'already')
    with pytest.raises(ValueError):
        change_box(game.port(), 14)


def test_learn_move_in_battle_replaces_the_requested_slot():
    game = Game2(battle=1, screen='battle_menu', party=[mon('ONE', moves=(33, 45, 10, 98)), mon('TWO')])
    game.battle_learn(0)
    game.sync()
    result = learn_move(game.port(), 2)
    assert done(result) and game.party[0]['moves'] == [33, 45, 99, 98] and game.screen == 'battle_menu', result
    assert result['shortcut']['forgotten_move_id'] == 10


def test_learn_move_keep_and_hm_refusal():
    game = Game2(battle=1, screen='battle_menu', party=[mon('ONE', moves=(15, 45, 10, 98))])
    game.battle_learn(0)
    game.sync()
    refused(learn_move(game.port(), 0), game, 'HM')
    result = learn_move(game.port(), 'keep')
    assert done(result) and game.party[0]['moves'] == [15, 45, 10, 98] and game.screen == 'battle_menu', result


def test_move_deleter_forgets_the_requested_move():
    game = Game2(party=[mon('ONE'), mon('TWO', moves=(15, 45, 70, 0))])
    game.move_deleter()
    game.sync()
    result = delete_move(game.port(), 1, 2)
    assert done(result) and game.party[1]['moves'] == [15, 45, 0, 0] and game.screen == 'overworld', result
    game = Game2(party=[mon('ONE'), mon('TWO', moves=(15, 45, 70, 0))])
    game.move_deleter()
    game.sync()
    refused(delete_move(game.port(), 1, 3), game, 'empty')
    game = Game2()
    refused(delete_move(game.port(), 0, 0), game, 'No input sent')



# Day Care, showing a partner and the radio ------------------------------------------------

def test_day_care_takes_the_requested_pokemon_and_gives_it_back():
    game = Game2(party=[mon('ONE'), mon('TWO', species=4), mon('SIX')])
    game.day_care(0)
    game.sync()
    result = day_care(game.port(), 0, 1)
    assert done(result) and game.daycare[0]['nick'] == 'TWO' and game.screen == 'overworld', result
    assert [m['nick'] for m in game.party] == ['ONE', 'SIX'] and result['shortcut']['action'] == 'deposit'
    game.inputs.clear()
    game.day_care(0)
    game.sync()
    result = day_care(game.port(), 0)
    assert done(result) and game.daycare[0] is None and game.party[-1]['nick'] == 'TWO', result


def test_day_care_never_counts_a_look_alike():
    # ONE and TWO share species, trainer and DVs. Only the nickname tells them apart, and the
    # game leaving ONE where TWO was asked for is no deposit of TWO.
    game = Game2(party=[mon('ONE'), mon('TWO'), mon('SIX')])
    game.day_care(0)
    game.sync()
    original = game.party_daycare
    game.party_daycare = lambda slot: original(0)
    result = day_care(game.port(), 0, 1)
    assert not result['shortcut']['completed'] and game.daycare[0]['nick'] == 'ONE', result


def test_day_care_refusals_send_no_input():
    game = Game2(party=[mon('ONE')])
    game.day_care(0)
    game.sync()
    refused(day_care(game.port(), 0, 3), game, 'unavailable')
    refused(day_care(game.port(), 0), game, 'empty')
    game.party.append(mon('EGG', egg=True))
    game.sync()
    refused(day_care(game.port(), 0, 1), game, 'Egg')
    game.daycare[1] = mon('HELD')
    game.sync()
    refused(day_care(game.port(), 1, 0), game, 'taken')
    game = Game2(party=[mon(str(index)) for index in range(6)])
    game.daycare[0] = mon('HELD')
    game.day_care(0)
    game.sync()
    refused(day_care(game.port(), 0), game, 'full')
    refused(day_care(Game2().port(), 0, 0), Game2(), 'greeting')


def test_day_care_stops_when_another_pokemon_takes_the_slot():
    game = Game2(party=[mon('ONE'), mon('TWO'), mon('SIX')])
    game.day_care(0)
    game.sync()
    original = game.go_party

    def go_party(mode, source=None):
        game.party.pop(0)    # a stale slot: SIX now sits where TWO was
        original(mode, source)
    game.go_party = go_party
    result = day_care(game.port(), 0, 1)
    assert not result['shortcut']['completed'] and 'Party changed' in result['outcome'], result
    assert game.daycare[0] is None


def test_show_partner_sets_the_event_flag():
    game = Game2(party=[mon('ONE'), mon('TWO', species=25)])
    game.show_me(25, 300)
    game.sync()
    result = show_partner(game.port(), 1, 300)
    assert done(result) and game.event_flags[300 // 8] >> 300 % 8 & 1 and game.screen == 'overworld', result
    game.inputs.clear()
    game.show_me(25, 300)
    game.sync()
    refused(show_partner(game.port(), 1, 300), game, 'already')
    game = Game2(party=[mon('ONE'), mon('TWO', species=25)])
    game.show_me(25, 300)
    game.sync()
    result = show_partner(game.port(), 0, 300)
    assert not result['shortcut']['completed'] and game.screen == 'overworld', result
    game = Game2(party=[mon('ONE')])
    game.show_me(25, 300)
    game.sync()
    refused(show_partner(game.port(), 2, 300), game, 'unavailable')
    with pytest.raises(ValueError):
        show_partner(game.port(), 0, 2048)


def test_radio_tunes_to_the_poke_flute_and_returns():
    game = Game2(screen='overworld')
    game.pokegear = 0x82
    game.sync()
    result = tune_radio(game.port())
    assert done(result) and game.knob == 78 and game.music == 0x40 and game.screen == 'overworld', result
    assert result['shortcut']['station'] == 78
    game = Game2(screen='overworld')
    game.pokegear = 0x80
    game.sync()
    refused(tune_radio(game.port()), game, 'radio card')
    with pytest.raises(ValueError):
        tune_radio(game.port(), 256)


def test_menu_labels_and_choices_read_like_the_screen():
    assert gen2ui.menu_label('│▶POKéMON      │') == 'POKéMON'
    assert gen2ui.menu_label(' 12 ▶TM12       ×1') == 'TM12       ×1'
    rows = ['│ BILL\'s PC    │', '│▶KRIS\'s PC    │', '│ TURN OFF     │']
    assert gen2ui.choose(rows, 'TURN OFF') == 'down' and gen2ui.choose(rows, 'turn') == 'down'
    assert gen2ui.choose(rows, "KRIS's PC", exact=True) == 'a'
    assert gen2ui.choose(rows, 'TURN', exact=True) is None and gen2ui.choose(['  YES'], 'YES') is None
    assert gen2ui.close_pc(rows, 'Access whose PC?') == 'down'
    assert gen2ui.close_pc(rows, "BILL's PC accessed.") == 'b'

def test_throw_can_hand_the_nickname_prompt_to_the_caller():
    game = Game2(balls=[(POKE_BALL, 2)], battle=1, screen='battle_menu')
    result = use_item(game.port(), POKE_BALL, nickname='caller')
    assert result['shortcut']['completed'] and result['shortcut']['pending'] == 'nickname', result
    assert game.screen == 'menu' and 'NICKNAME' in gen2ui.text_box(gen2ui.View(game.memory, 'crystal')).upper().replace(' ', '')
    game = Game2(balls=[(POKE_BALL, 2)], battle=1, screen='battle_menu')
    assert done(use_item(game.port(), POKE_BALL)) and game.screen == 'overworld'


def test_fight_with_no_pp_left_uses_struggle():
    game = Game2(battle=1, screen='battle_menu')
    game.party[0]['pp'] = [0, 0, 0, 0]
    game.sync()

    def fight():
        game.say('ONE has no moves left!', 'ONE used STRUGGLE!', then=game.enemy_turn)
    original = game.press_battle_menu
    game.press_battle_menu = lambda button: fight() if button == 'a' and game.battle_cursor == (9, 14) else original(
        button)
    result = choose_move(game.port(), 0)
    assert done(result) and result['shortcut']['forced'] == 'struggle' and game.screen == 'battle_menu', result


def without_egg_field(game):
    def read_party(raw):
        return [{key: value for key, value in member.items() if key != 'egg'}
                for member in gen2ui.read_party(raw, game.version)]
    return read_party


def test_party_checks_accept_a_reader_without_the_egg_field():
    game = Game2(party=[mon('ONE'), mon('TWO', moves=(15, 45, 70, 0))])
    game.move_deleter()
    game.sync()
    result = delete_move(game.port(read_party=without_egg_field(game)), 1, 2)
    assert done(result) and game.party[1]['moves'] == [15, 45, 0, 0], result
    game = pc_game()
    result = deposit_pokemon(game.port(read_party=without_egg_field(game)), 1)
    assert done(result) and [m['nick'] for m in game.box] == ['ROCK', 'BIRD', 'TWO'], result


# A traded nickname holding <CONT> (0x55) ----------------------------------------------

def cont_memory(header):
    """Raw memory holding _ContText at 0x1200, whose PromptButton (0x0A60) call returns to 0x120D.

    A <PARA> handler at 0x1180 calls PromptButton too and returns to 0x1183.
    """
    raw = bytearray(0x10000)
    raw[0x134:0x13C] = header
    raw[0x1200:0x1212] = bytes.fromhex('b72003cd5009cd7009d5cd600ad1fa0000b7')
    raw[0x1180:0x1183] = bytes.fromhex('cd600a')
    return raw


def test_cont_wait_reads_the_prompt_return_from_live_stack_words():
    raw = cont_memory(b'CONTTEST')
    assert not gen2ui.cont_wait(raw, 0xDF00)
    raw[0xDF06:0xDF08] = (0x120D).to_bytes(2, 'little')
    assert gen2ui.cont_wait(raw, 0xDF00)
    # Any text engine call to PromptButton counts, and the other calls in _ContText do not.
    for address, waiting in ((0x1183, True), (0x1206, False), (0x1209, False)):
        raw[0xDF06:0xDF08] = address.to_bytes(2, 'little')
        assert gen2ui.cont_wait(raw, 0xDF00) is waiting, hex(address)
    # Words below the stack pointer are dead, and a stack outside WRAM is never read.
    assert not gen2ui.cont_wait(raw, 0xDF08) and not gen2ui.cont_wait(raw, 0xFFFE)
    # A cartridge without the routine never reports the wait.
    empty = bytearray(0x10000)
    empty[0x134:0x13C], empty[0xDF00:0xDF02] = b'NOROUTIN', (0x120D).to_bytes(2, 'little')
    assert not gen2ui.cont_wait(empty, 0xDF00)


def test_box_list_presses_a_through_a_cont_wait():
    """Scrolling Bill's PC redraws the names, and the 0x55 one stops the list until A."""
    from types import SimpleNamespace

    from pokecore.shortcuts import WithdrawPokemon
    raw = cont_memory(b'CONTLIST')
    machine = WithdrawPokemon(5, version='gold')
    position = [0]

    def look(waiting):
        raw[0xDF00:0xDF02] = (0x120D if waiting else 0).to_bytes(2, 'little')
        machine.obs = SimpleNamespace(screen='pc_box', ui={'sp': 0xDF00}, raw=raw, ready=None)

    look(False)
    flow = machine.move_index(5, lambda obs: position[0])
    pressed = []
    try:
        button = next(flow)
        while True:
            pressed.append(button)
            if button == 'down':
                position[0] += 1
            # Every move that scrolls the 0x55 name back into view stops the list again.
            look(button == 'down' and position[0] >= 3)
            button = flow.send(None)
    except StopIteration as stop:
        assert stop.value is True
    assert pressed == ['down', 'down', 'down', 'a', 'down', 'a', 'down', 'a'], pressed
