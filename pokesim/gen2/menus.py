"""Cartridge menu operations driven by observed labels and menu cursors."""
from dataclasses import dataclass
import re

from .screens import has_word

# A menu task that needs more steps than this is lost. It ends and the stuck path takes over.
MAX_STEPS = 600
RADIO_MAX_STEPS = 300
# A slot session is hundreds of rounds, so it is capped on a long run and on no visible change.
SLOT_MAX_STEPS = 12000


def selected(rows):
    return next((row.split('▶', 1)[1].strip() for row in rows if '▶' in row), '')


def menu_label(row):
    if row.count('│') >= 2:
        row = row.rsplit('│', 2)[-2]
    if any('\u3040' <= char <= '\u30ff' for char in row[:5]):
        row = row[5:]
    # The pack image occupies columns 0 through 4 beside TM and HM rows.
    if re.match(r'(?:H\d|\d{2})[\s▶▷]', row[5:]):
        row = row[5:]
    return re.sub(r'^[\s│▷▶]*(?:H?\d+[\s▷▶]*)?', '', row).strip(' │')


def tracked(task, snapshot):
    """Return the party member a slot task works on, or None once that member has left its slot.

    A task keeps its slot index across checkpoints and handoffs to trade preparation. The first
    step records who holds the slot, so a later deposit, trade or reorder ends the task instead
    of indexing past the party or acting on a different Pokémon.
    """
    if not 0 <= task.slot < len(snapshot.party):
        return None
    mon = snapshot.party[task.slot]
    key = [getattr(mon, 'trainer_id', None), list(getattr(mon, 'dvs', ()))]
    if task.member is None:
        task.member = key
    return mon if [task.member[0], list(task.member[1])] == key else None


def choose(rows, label, *, exact=False):
    target = next((i for i, row in enumerate(rows)
                   if (menu_label(row).casefold() == label.casefold() if exact else has_word(row.casefold(), label.casefold()))), None)
    cursor = next((i for i, row in enumerate(rows) if '▶' in row), None)
    if target is None or cursor is None:
        return None
    return 'a' if target == cursor else 'down' if target > cursor else 'up'


@dataclass
class Teach:
    move: int
    slot: int
    phase: str = 'open'
    steps: int = 0
    replace_move: int | None = None
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        mon = tracked(self, snapshot)
        party_menu = 'CANCEL' in text and 'ABLE' in text and any(row.lstrip().startswith('▶') for row in rows)
        if party_menu:
            if mem.byte('wPutativeTMHMMove') != self.move:
                self.phase = 'pack'
                return 'b'
            self.phase = 'confirm'
        if mon is None or self.move in mon.moves:
            self.phase = 'exit'
        if self.phase == 'exit':
            return 'b' if '┌' in rows[12] or 'CANCEL' in text or 'PACK' in text else None
        if self.phase == 'open':
            if 'PACK' in text:
                action = choose(rows, 'PACK')
                if action == 'a':
                    self.phase = 'pack'
                return action or 'b'
            if '┌' in rows[12] or any(label in text for label in ('TURN OFF', 'CHANGE BOX', 'CANCEL')):
                return 'b'
            return 'start'
        if self.phase == 'pack':
            if not any('▶' in row for row in rows[:12]):
                return 'wait'
            if mem.byte('wCurPocket') != 3:
                return 'right'
            label = snapshot.data.moves[self.move]['name'].upper()
            action = choose(rows, label, exact=True)
            if action == 'a':
                self.phase = 'use'
            if action:
                return action
            aliases = snapshot.data.items
            key = snapshot.data.moves[self.move].get('constant', label.replace(' ', '_').replace('-', '_'))
            item = aliases.get('TM_' + key, aliases.get('HM_' + key))
            target = next((i for i in range(1, 58)
                           if aliases.get(f'TM{i:02d}' if i <= 50 else f'HM{i - 50:02d}') == item), 57)
            visible = [(int(m[2]) + (50 if m[1] else 0), index) for index, row in enumerate(rows[:12])
                       if (m := re.match(r'(H?)(\d+)[ ▶▷]', row[5:]))]
            index = next((index for number, index in visible if number == target), None)
            cursor = next((i for i, row in enumerate(rows[:12]) if '▶' in row), None)
            if index is not None and cursor is not None:
                if index == cursor:
                    self.phase = 'use'
                    return 'a'
                return 'down' if index > cursor else 'up'
            return 'up' if visible and target < min(number for number, _ in visible) or selected(rows) == 'CANCEL' else 'down'
        if self.phase == 'use':
            if 'USE' in text:
                self.phase = 'confirm'
                return choose(rows, 'USE') or 'a'
            if '┌' in rows[12]:
                self.phase = 'confirm'
            return 'wait'
        if self.phase == 'confirm':
            if 'YES' in text and 'NO' in text:
                self.phase = 'learn'
                return choose(rows, 'YES', exact=True) or 'a'
            if party_menu:
                cursor = next((i // 2 + 1 for i, row in enumerate(rows) if '▶' in row), 1)
                target = self.slot + 1
                if cursor == target:
                    self.phase = 'learn'
                    return 'a'
                return 'down' if cursor < target else 'up'
            return 'a'
        if self.phase == 'learn':
            if 'TYPE/' in text or '▶' in text and 'Which move' in text:
                protected = {15, 19, 57, 70, 148, 250, 127}
                target = min(range(4), key=lambda i: 999 if mon.moves[i] in protected else snapshot.data.moves.get(mon.moves[i], {}).get('power', 0)) + 1
                if self.replace_move in mon.moves and self.replace_move not in protected:
                    target = mon.moves.index(self.replace_move) + 1
                cursor = mem.byte('wMenuCursorY')
                return 'a' if cursor == target else 'down' if cursor < target else 'up'
            return 'a'
        return None


@dataclass
class Buy:
    item: int
    amount: int
    initial: int
    phase: str = 'greet'
    steps: int = 0
    exit_steps: int = 0
    clear_frames: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        count = dict(snapshot.items).get(self.item, 0)
        rows, text = snapshot.tiles, snapshot.text
        price = snapshot.data.item_attributes[self.item]['price']
        # Never ask for something the wallet cannot cover: the clerk only answers "You don't have
        # enough money." and the shop would offer the same item again.
        if count > self.initial or self.steps > 240 or snapshot.money < price:
            self.phase = 'exit'
        if self.phase == 'exit':
            # The clerk's box can be blank for a frame between "Here you go!" and "Anything else?".
            # Leave only after the shop screen has stayed away for several frames, never on one gap.
            self.exit_steps += 1
            showing = '┌' in rows[12] or 'CANCEL' in text or 'BUY' in text or bool(mem.byte('wScriptRunning'))
            self.clear_frames = 0 if showing else self.clear_frames + 1
            return 'b' if self.clear_frames < 3 and self.exit_steps <= 40 else None
        if self.phase == 'greet':
            if 'BUY' in text:
                self.phase = 'list'
                return choose(rows, 'BUY') or 'a'
            return 'a'
        if self.phase == 'list':
            label = snapshot.data.item_names[self.item].upper().replace('POKE ', 'POKé ')
            action = choose(rows, label, exact=True)
            if action == 'a':
                self.phase = 'quantity'
            return action or 'down'
        if self.phase == 'quantity':
            if '×' not in text:
                return 'a'
            quantity = mem.byte('wItemQuantityChange')
            target = min(self.amount, snapshot.money // price)
            if quantity == target:
                self.phase = 'confirm'
                return 'a'
            return 'up' if quantity < target else 'down'
        return 'a'


@dataclass
class Sell:
    item: int
    initial: int
    phase: str = 'greet'
    steps: int = 0
    exit_steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        rows, text = snapshot.tiles, snapshot.text
        if dict(snapshot.items).get(self.item, 0) < self.initial or self.steps > 240:
            self.phase = 'exit'
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 12 else None
        if self.phase == 'greet':
            if 'BUY' in text and 'SELL' in text:
                button = choose(rows, 'SELL', exact=True)
                if button == 'a':
                    self.phase = 'pack'
                return button or 'a'
            return 'a'
        if self.phase == 'pack':
            if not any('▶' in row for row in rows[:12]):
                return 'wait'
            machine = next((i for i in range(1, 51) if snapshot.data.items.get(f'TM{i:02d}') == self.item), None)
            pocket = 3 if machine else 0
            if mem.byte('wCurPocket') != pocket:
                return 'right' if pocket else 'left'
            if machine:
                visible = [(int(m[1]), index) for index, row in enumerate(rows[:12])
                           if (m := re.match(r'(\d+)[ ▶▷]', row[5:]))]
                index = next((index for number, index in visible if number == machine), None)
                cursor = next((i for i, row in enumerate(rows) if '▶' in row), None)
                button = ('a' if index == cursor else 'down' if index > cursor else 'up') if index is not None and cursor is not None else (
                    'up' if visible and machine < min(number for number, _ in visible) or selected(rows) == 'CANCEL' else 'down')
            else:
                button = choose(rows, snapshot.data.item_names[self.item], exact=True) or 'down'
            if button == 'a':
                self.phase = 'confirm'
            return button
        return choose(rows, 'YES', exact=True) or 'a'


@dataclass
class Use:
    item: int
    pocket: int = 2
    phase: str = 'open'
    steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        if self.item not in dict(snapshot.items):
            return 'b' if '┌' in rows[12] or 'PACK' in text or 'CANCEL' in text else None
        if self.phase == 'open':
            if 'PACK' in text:
                action = choose(rows, 'PACK')
                if action == 'a':
                    self.phase = 'pack'
                return action or 'b'
            return 'start'
        if self.phase == 'pack':
            if not any('▶' in row for row in rows[:12]):
                return 'wait'
            if mem.byte('wCurPocket') != self.pocket:
                return 'right'
            action = choose(rows, snapshot.data.item_names[self.item].upper(), exact=True)
            if action == 'a':
                self.phase = 'use'
            return action or 'down'
        if self.phase == 'use':
            if 'USE' in text:
                self.phase = 'finish'
                return choose(rows, 'USE') or 'a'
            return 'a'
        return None


@dataclass
class Storage:
    operation: str
    slot: int
    initial_count: int
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        if len(snapshot.party) != self.initial_count:
            self.phase = 'exit'
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 12 else None
        if 'TURN OFF' in text:
            return choose(rows, 'BILL') or choose(rows, 'SOMEONE') or 'a'
        if 'CHANGE BOX' in text:
            self.phase = 'list'
            return choose(rows, self.operation) or 'a'
        if 'STATS' in text and self.operation in text:
            self.phase = 'confirm'
            return choose(rows, self.operation) or 'a'
        if self.phase == 'list' and ('Choose' in text or 'CANCEL' in text):
            cursor = mem.byte('wBillsPC_CursorPosition') + mem.byte('wBillsPC_ScrollPosition')
            if cursor == self.slot:
                self.phase = 'submenu'
                return 'a'
            return 'down' if cursor < self.slot else 'up'
        return 'a'


@dataclass
class Forget:
    slot: int
    move: int
    phase: str = 'greet'
    steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        mon = tracked(self, snapshot)
        if mon is None or self.move not in mon.moves:
            self.phase = 'exit'
        if self.phase == 'exit':
            return 'a' if any('┌' in row for row in rows[12:15]) else None
        if 'CANCEL' in text and '▶' in text and '/' in text:
            cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
            if cursor == self.slot:
                self.phase = 'move'
                return 'a'
            return 'down' if cursor < self.slot else 'up'
        if self.phase == 'move' and '▶' in text:
            label = snapshot.data.moves[self.move]['name'].upper()
            action = choose(rows, label, exact=True)
            if action:
                if action == 'a':
                    self.phase = 'confirm'
                return action
        return 'a'


@dataclass
class Remedy:
    item: int
    slot: int
    initial: int
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        if dict(snapshot.items).get(self.item, 0) < self.initial or tracked(self, snapshot) is None:
            self.phase = 'exit'
        if self.phase == 'exit':
            if snapshot.in_battle:
                return None
            self.exit_steps += 1
            return 'b' if self.exit_steps < 12 else None
        if self.phase == 'open':
            if snapshot.in_battle and 'FIGHT' in text and 'TYPE' not in text:
                if mem.byte('wMenuCursorX') > 1:
                    return 'left'
                if mem.byte('wMenuCursorY') < 2:
                    return 'down'
                self.phase = 'pack'
                return 'a'
            if 'PACK' in text:
                action = choose(rows, 'PACK')
                if action == 'a':
                    self.phase = 'pack'
                return action or 'wait'
            if not snapshot.in_battle and ('┌' in rows[12] or any(label in text for label in ('TURN OFF', 'CHANGE BOX', 'CANCEL'))):
                return 'b'
            return 'a' if snapshot.in_battle else 'start'
        if self.phase == 'pack':
            if 'USE' in text:
                self.phase = 'party'
                return choose(rows, 'USE') or 'a'
            if not any('▶' in row for row in rows[:12]):
                return 'wait'
            if mem.byte('wCurPocket') != 0:
                return 'left'
            label = snapshot.data.item_names[self.item].upper()
            return choose(rows, label, exact=True) or 'down'
        if self.phase == 'party':
            if 'CANCEL' in text and '▶' in text and ('/' in text or 'ABLE' in text):
                cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
                return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
            return 'a'
        return None


@dataclass
class ChangeBox:
    box: int
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        if snapshot.active_box == self.box:
            self.phase = 'exit'
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 16 else None
        if 'TURN OFF' in text:
            return choose(rows, 'BILL') or choose(rows, 'SOMEONE') or 'a'
        if 'CHANGE BOX' in text:
            self.phase = 'boxes'
            return choose(rows, 'CHANGE BOX') or 'a'
        if self.phase == 'open':
            if 'STATS' in text:
                return choose(rows, 'CANCEL') or 'b'
            return 'b' if 'CANCEL' in text or 'PACK' in text else 'a'
        if 'SWITCH' in text and 'NAME' in text:
            self.phase = 'save'
            return choose(rows, 'SWITCH') or 'a'
        if self.phase == 'boxes' and 'Choose a BOX' in text:
            cursor = mem.byte('wMenuSelection') - 1
            return 'a' if cursor == self.box else 'down' if cursor < self.box else 'up'
        return 'a'


@dataclass
class Radio:
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > RADIO_MAX_STEPS:
            return None
        rows, text = snapshot.tiles, snapshot.text
        if self.phase == 'open':
            if 'GEAR' in text:
                action = choose(rows, 'GEAR')
                if action == 'a':
                    self.phase = 'tune'
                return action or 'wait'
            return 'start'
        if self.phase == 'tune':
            if mem.byte('wPokegearCard') != 3:
                return 'right'
            knob = mem.byte('wRadioTuningKnob')
            if knob == 78:
                self.phase = 'listen'
                return 'wait'
            return 'up' if knob < 78 else 'down'
        if self.phase == 'listen':
            if mem.byte('wMapMusic') == 0x40:
                self.phase = 'exit'
            return 'wait'
        self.exit_steps += 1
        return 'b' if self.exit_steps < 8 else None


@dataclass
class Lead:
    slot: int
    identity: tuple
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0

    def step(self, snapshot, mem):
        self.steps += 1
        wanted = (self.identity[0], tuple(self.identity[1]))
        slots = [i for i, mon in enumerate(snapshot.party) if (mon.trainer_id, tuple(mon.dvs)) == wanted]
        # Follow the Pokémon rather than its old slot, which a deposit or trade may have moved.
        if slots:
            self.slot = slots[0]
        if not slots or self.slot == 0 or self.steps > 180:
            self.phase = 'exit'
        rows, text = snapshot.tiles, snapshot.text
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 8 else None
        if self.phase == 'open':
            if 'POKéMON' in text and 'PACK' in text:
                button = choose(rows, 'POKéMON')
                if button == 'a':
                    self.phase = 'party'
                return button or 'wait'
            return 'start'
        if self.phase == 'party':
            if 'STATS' in text and 'SWITCH' in text:
                button = choose(rows, 'SWITCH', exact=True)
                if button == 'a':
                    self.phase = 'switch'
                return button or 'wait'
            if 'CANCEL' in text and '/' in text:
                cursor = mem.byte('wMenuCursorY') - 1
                return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
            return 'wait'
        cursor = mem.byte('wMenuCursorY') - 1
        return 'a' if cursor == 0 else 'up'


@dataclass
class DayCare:
    parent: int
    slot: int | None = None
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        done = (snapshot.daycare[self.parent] is None) == (self.slot is None)
        done = done or self.slot is not None and tracked(self, snapshot) is None
        if done or self.exit_steps or self.steps > 240:
            self.exit_steps += 1
            return 'b' if self.exit_steps < 8 else None
        if self.slot is not None and 'CANCEL' in snapshot.text and 'Choose a POKéMON' in snapshot.text:
            cursor = mem.byte('wMenuCursorY') - 1
            return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
        return choose(snapshot.tiles, 'YES', exact=True) or 'a'


@dataclass
class FieldMove:
    slot: int
    label: str
    phase: str = 'open'
    steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        rows, text = snapshot.tiles, snapshot.text
        if self.phase in {'open', 'party'} and tracked(self, snapshot) is None:
            self.phase = 'exit'
        if self.steps > 180 or self.phase == 'exit':
            return 'b' if 'CANCEL' in text or 'PACK' in text or '┌' in rows[12] else None
        if self.phase == 'open':
            if 'POKéMON' in text and 'PACK' in text:
                button = choose(rows, 'POKéMON')
                if button == 'a':
                    self.phase = 'party'
                return button or 'wait'
            return 'start'
        if self.phase == 'party':
            if 'STATS' in text and 'SWITCH' in text:
                button = choose(rows, self.label, exact=True)
                if button == 'a':
                    self.phase = 'using'
                return button or 'b'
            if 'CANCEL' in text and '/' in text:
                cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
                return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
            return 'wait'
        if '┌' in rows[12]:
            return 'a'
        return None


@dataclass
class Fly:
    slot: int
    target: int
    origin: int
    destination: int
    phase: str = 'open'
    steps: int = 0
    map_wait: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if self.steps > 180 or self.phase in {'open', 'party'} and tracked(self, snapshot) is None:
            self.phase = 'exit'
        rows, text = snapshot.tiles, snapshot.text
        if self.phase == 'open':
            if 'POKéMON' in text and 'PACK' in text:
                button = choose(rows, 'POKéMON')
                if button == 'a':
                    self.phase = 'party'
                return button or 'wait'
            return 'start'
        if self.phase == 'party':
            if 'STATS' in text and 'SWITCH' in text:
                button = choose(rows, 'FLY', exact=True)
                if button == 'a':
                    self.phase = 'map'
                return button or 'b'
            if 'CANCEL' in text and '/' in text:
                cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
                return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
            return 'wait'
        if self.phase == 'map':
            self.map_wait += 1
            if self.map_wait < 5:
                return 'wait'
            if not mem.byte('wStartFlypoint') <= self.target <= mem.byte('wEndFlypoint'):
                self.phase = 'exit'
                return 'b'
            current = mem.byte('wTownMapPlayerIconLandmark')
            if current == self.target:
                self.phase = 'flying'
                return 'a'
            return 'up'
        if self.phase == 'flying':
            if snapshot.map == self.destination:
                return None
            return 'wait'
        return 'b' if 'CANCEL' in text or 'PACK' in text or '┌' in rows[12] else None


@dataclass
class Give:
    item: int
    slot: int
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        rows, text = snapshot.tiles, snapshot.text
        mon = tracked(self, snapshot)
        if mon is None or mon.held_item == self.item or self.steps > 240:
            self.phase = 'exit'
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 12 else None
        if self.phase == 'open':
            if 'PACK' in text:
                action = choose(rows, 'PACK')
                if action == 'a':
                    self.phase = 'pack'
                return action or 'wait'
            if '┌' in rows[12] or any(label in text for label in ('TURN OFF', 'CHANGE BOX', 'CANCEL')):
                return 'b'
            return 'start'
        if self.phase == 'pack':
            if 'GIVE' in text:
                action = choose(rows, 'GIVE', exact=True)
                if action == 'a':
                    self.phase = 'party'
                return action or 'wait'
            if not any('▶' in row for row in rows[:12]):
                return 'wait'
            if mem.byte('wCurPocket') != 0:
                return 'left'
            return choose(rows, snapshot.data.item_names[self.item].upper(), exact=True) or 'down'
        if 'YES' in text and 'NO' in text:
            return choose(rows, 'YES', exact=True) or 'a'
        if 'CANCEL' in text and '▶' in text and '/' in text:
            cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
            return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
        return 'a'


@dataclass
class Take:
    slot: int
    phase: str = 'open'
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        rows, text = snapshot.tiles, snapshot.text
        mon = tracked(self, snapshot)
        if mon is None or not mon.held_item or self.steps > 240:
            self.phase = 'exit'
        if self.phase == 'exit':
            self.exit_steps += 1
            return 'b' if self.exit_steps < 12 else None
        if self.phase == 'open':
            if 'PACK' in text:
                action = choose(rows, 'POKéMON')
                if action == 'a':
                    self.phase = 'party'
                return action or 'wait'
            if '┌' in rows[12] or any(label in text for label in ('TURN OFF', 'CHANGE BOX', 'CANCEL')):
                return 'b'
            return 'start'
        if 'TAKE' in text:
            return choose(rows, 'TAKE', exact=True) or 'a'
        if 'STATS' in text and 'SWITCH' in text:
            return choose(rows, 'ITEM', exact=True) or 'a'
        if 'CANCEL' in text and '▶' in text and '/' in text:
            cursor = next((i // 2 for i, row in enumerate(rows) if '▶' in row), 0)
            return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
        return 'a'


@dataclass
class ShowPartner:
    slot: int
    event: str
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if snapshot.event(self.event) or self.exit_steps or self.steps > 240 or tracked(self, snapshot) is None:
            self.exit_steps += 1
            return 'b' if self.exit_steps < 8 else None
        if 'CANCEL' in snapshot.text and '/' in snapshot.text:
            cursor = mem.byte('wMenuCursorY') - 1
            return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
        return choose(snapshot.tiles, 'YES', exact=True) or 'a'
