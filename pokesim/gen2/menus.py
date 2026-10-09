"""Cartridge menu operations for Gold, Silver and Crystal.

Item, mart, PC, party, box change, Move Deleter and battle menus run Core shortcut machines one
input per policy step. The tasks kept here cover menus Core has no shortcut for: the radio, the
Day Care and showing a Pokémon to a person.
"""
from dataclasses import KW_ONLY, dataclass, fields
import re

from pokesim_core.shortcuts import (BuyItem, ChangeBox as CoreChangeBox, ChooseMove, DeleteMove, DepositPokemon,
                                    Done, FieldMove as CoreFieldMove, GiveItem, LearnMove, ReleasePokemon, ReorderParty,
                                    RunAway, SellItem, SwitchPokemon, TakeItem, UseItem, WithdrawPokemon, current_screen)
from pokesim_core.shortcuts.machine import BACKABLE

from .screens import has_word

# A menu task that needs more steps than this is lost. It ends and the stuck path takes over.
MAX_STEPS = 600
RADIO_MAX_STEPS = 300
# A slot session is hundreds of rounds, so it is capped on a long run and on no visible change.
SLOT_MAX_STEPS = 12000


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


def close_pc(snapshot):
    """The button that leaves a Pokémon Center PC whose list (BILL's PC ... TURN OFF) is on screen.

    The list stays drawn under messages such as "BILL's PC accessed." and "POKéMON Storage System
    opened.", and those hold the cursor until they are dismissed. Moving toward TURN OFF works only
    while the list asks "Access whose PC?". Otherwise B dismisses the message and backs out.
    """
    if 'whose PC' in snapshot.text:
        return choose(snapshot.tiles, 'TURN OFF') or 'b'
    return 'b'


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


def restore(cls, state):
    """Rebuild a saved task, ignoring fields an older version of the task kept."""
    names = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in state.items() if key in names})


# Moves a taught machine never replaces: the HMs the journey needs, Flash and Headbutt.
PROTECTED_MOVES = frozenset({15, 19, 57, 70, 148, 250, 127})
# The in-game Fly map names of fly points whose map has another name.
FLY_NAMES = {'Route 10 North': 'ROUTE 10', 'Route 23': 'INDIGO PLATEAU', 'Silver Cave Outside': 'SILVER CAVE'}


def fly_name(data, index):
    name = data.maps[data.fly_points[index]['map']]['name']
    return FLY_NAMES.get(name, name.upper())


@dataclass
class CoreTask:
    """Drive one Core shortcut machine from the policy's per-step loop.

    The machine is rebuilt after a checkpoint restore, since only the dataclass fields are
    saved. ``finished`` guards against repeating an effect that already happened. Mart and PC
    tasks first reach the clerk's or the PC's menu and press B back to the overworld afterwards.
    """
    _: KW_ONLY
    phase: str = 'start'
    steps: int = 0
    exit_steps: int = 0

    battle = False
    # Screens the machine starts from. None lets the machine open the menus itself.
    start = None
    leave = False

    def build(self, snapshot):
        raise NotImplementedError

    def finished(self, snapshot):
        return False

    def after(self, done):
        """Called once with the machine's Done."""

    def approach(self, screen):
        if self.start is None:
            if screen in ('pc', 'mart', 'menu', 'yes_no', 'players_pc'):
                return 'b'
            return None
        if screen in BACKABLE or screen == 'yes_no':
            return 'b'
        return 'a'

    def step(self, snapshot, mem):
        self.steps += 1
        if self.phase == 'exit':
            return self.exit(mem)
        machine = getattr(self, 'machine', None)
        if machine is None:
            if self.steps > MAX_STEPS or self.finished(snapshot):
                return self.end(mem)
            version = snapshot.data.game
            screen = current_screen(mem.memory, version)
            if self.start is None or screen not in self.start:
                button = self.approach(screen)
                if button and self.steps < 60:
                    return button
            machine = self.machine = self.build(snapshot)
            if machine is None:
                return self.end(mem)
        action = machine.step(mem.memory, None)
        if isinstance(action, Done):
            self.result = action
            self.after(action)
            return self.end(mem)
        return 'wait' if action is None else action

    def end(self, mem):
        if self.leave:
            self.phase = 'exit'
            return 'wait'
        return None

    def exit(self, mem):
        """Press B until the overworld shows on two steps in a row."""
        self.exit_steps += 1
        resting = current_screen(mem.memory, mem.data.game) == 'overworld'
        self.clear = getattr(self, 'clear', 0) + 1 if resting else 0
        if self.clear >= 2 or self.exit_steps > 40:
            return None
        return 'wait' if resting else 'b'

    def key(self):
        """What the task asks for, so a refused request is not repeated at once."""
        return (type(self).__name__, *(getattr(self, field.name) for field in fields(self) if not field.kw_only
                                       and field.name not in ('initial', 'initial_count', 'member', 'box_full')
                                       and isinstance(getattr(self, field.name), (int, str))))

    @staticmethod
    def options(snapshot):
        return {'version': snapshot.data.game}


@dataclass
class Teach(CoreTask):
    move: int
    slot: int
    replace_move: int | None = None
    member: list | None = None

    def finished(self, snapshot):
        mon = tracked(self, snapshot)
        return mon is None or self.move in mon.moves

    def build(self, snapshot):
        data = snapshot.data
        key = data.moves[self.move].get('constant', data.moves[self.move]['name'].upper().replace(' ', '_'))
        item = data.items.get('TM_' + key, data.items.get('HM_' + key))
        if item is None:
            return None
        mon = snapshot.party[self.slot]
        forget = None
        if all(mon.moves):
            forget = min(range(4), key=lambda i: 999 if mon.moves[i] in PROTECTED_MOVES
                         else data.moves.get(mon.moves[i], {}).get('power', 0))
            if self.replace_move in mon.moves and self.replace_move not in PROTECTED_MOVES:
                forget = mon.moves.index(self.replace_move)
        return UseItem(item, self.slot, forget_move=forget, **self.options(snapshot))


@dataclass
class Buy(CoreTask):
    item: int
    amount: int
    initial: int

    start = ('mart',)
    leave = True

    def finished(self, snapshot):
        return dict(snapshot.items).get(self.item, 0) > self.initial

    def build(self, snapshot):
        price = snapshot.data.item_attributes[self.item]['price']
        # Never ask for more than the wallet covers or the pack holds.
        amount = min(self.amount, snapshot.money // price if price else self.amount, 99 - self.initial)
        return BuyItem(self.item, amount, **self.options(snapshot)) if amount > 0 else None


@dataclass
class Sell(CoreTask):
    item: int
    initial: int

    start = ('mart',)
    leave = True

    def finished(self, snapshot):
        return dict(snapshot.items).get(self.item, 0) < self.initial

    def build(self, snapshot):
        return SellItem(self.item, 1, **self.options(snapshot))


@dataclass
class Use(CoreTask):
    item: int

    def finished(self, snapshot):
        return self.item not in dict(snapshot.items)

    def build(self, snapshot):
        return UseItem(self.item, **self.options(snapshot))


@dataclass
class Storage(CoreTask):
    operation: str
    slot: int
    initial_count: int
    box_full: bool = False

    start = ('pc', 'bills_pc')
    leave = True

    def finished(self, snapshot):
        return len(snapshot.party) != self.initial_count

    def build(self, snapshot):
        shortcut = DepositPokemon if self.operation == 'DEPOSIT' else WithdrawPokemon
        return shortcut(self.slot, **self.options(snapshot))

    def after(self, done):
        # The policy changes to a box with room and starts the deposit again.
        self.box_full = not done.completed and 'box is full' in done.outcome.lower()


@dataclass
class Remedy(CoreTask):
    item: int
    slot: int
    initial: int
    member: list | None = None

    battle = True

    def finished(self, snapshot):
        return dict(snapshot.items).get(self.item, 0) < self.initial or tracked(self, snapshot) is None

    def build(self, snapshot):
        return UseItem(self.item, self.slot, **self.options(snapshot))


@dataclass
class Lead(CoreTask):
    slot: int
    identity: tuple

    def finished(self, snapshot):
        # Follow the Pokémon rather than its old slot, which a deposit or trade may have moved.
        wanted = (self.identity[0], tuple(self.identity[1]))
        slots = [i for i, mon in enumerate(snapshot.party) if (mon.trainer_id, tuple(mon.dvs)) == wanted]
        if slots:
            self.slot = slots[0]
        return not slots or self.slot == 0

    def build(self, snapshot):
        return ReorderParty(self.slot, 0, **self.options(snapshot))


@dataclass
class FieldMove(CoreTask):
    slot: int
    label: str
    member: list | None = None

    def finished(self, snapshot):
        return tracked(self, snapshot) is None

    def build(self, snapshot):
        return CoreFieldMove(self.label, self.slot, **self.options(snapshot))


@dataclass
class Fly(CoreTask):
    slot: int
    target: int
    origin: int
    destination: int
    member: list | None = None

    def finished(self, snapshot):
        return snapshot.map == self.destination or tracked(self, snapshot) is None

    def build(self, snapshot):
        return CoreFieldMove('FLY', self.slot, fly_name(snapshot.data, self.target), **self.options(snapshot))


@dataclass
class Give(CoreTask):
    item: int
    slot: int
    member: list | None = None

    def finished(self, snapshot):
        mon = tracked(self, snapshot)
        return mon is None or mon.held_item == self.item

    def build(self, snapshot):
        return GiveItem(self.item, self.slot, swap=True, **self.options(snapshot))


@dataclass
class Take(CoreTask):
    slot: int
    member: list | None = None

    def finished(self, snapshot):
        mon = tracked(self, snapshot)
        return mon is None or not mon.held_item

    def build(self, snapshot):
        return TakeItem(self.slot, **self.options(snapshot))


@dataclass
class Throw(CoreTask):
    """Throw a ball in a wild battle."""
    item: int

    battle = True

    def build(self, snapshot):
        # The policy names caught Pokémon, so the nickname prompt is handed back to it.
        return UseItem(self.item, nickname='caller', **self.options(snapshot))


@dataclass
class ChangeBox(CoreTask):
    """Make ``box`` the current box through BILL's PC. The game saves as part of the change."""
    box: int

    start = ('pc', 'bills_pc')
    leave = True

    def finished(self, snapshot):
        return snapshot.active_box == self.box

    def build(self, snapshot):
        return CoreChangeBox(self.box, **self.options(snapshot))


@dataclass
class Release(CoreTask):
    """Let the spare at ``position`` of the open box go through BILL's PC. Releasing is permanent.

    ``member`` records who the spare is, so the task ends without input when anyone else sits in
    that slot. Core releases whoever is there and does not check.
    """
    box: int
    position: int
    member: list | None = None

    start = ('pc', 'bills_pc')
    leave = True

    def spare(self, snapshot):
        mon = next((mon for mon in snapshot.stored if mon.box == self.box and mon.position == self.position), None)
        return mon is not None and not mon.egg and [mon.species, mon.trainer_id, list(mon.dvs)] == self.member

    def finished(self, snapshot):
        return snapshot.active_box != self.box or not self.spare(snapshot)

    def build(self, snapshot):
        return ReleasePokemon(self.position, allow_release=True, **self.options(snapshot))


@dataclass
class Forget(CoreTask):
    """Have the Move Deleter remove ``move`` from the party member in ``slot``. Start at its greeting."""
    slot: int
    move: int
    member: list | None = None

    start = ('dialogue', 'yes_no')

    def approach(self, screen):
        # The greeting is still opening after the A press that started the task.
        return 'wait'

    def finished(self, snapshot):
        mon = tracked(self, snapshot)
        return mon is None or self.move not in mon.moves

    def build(self, snapshot):
        mon = snapshot.party[self.slot]
        return DeleteMove(self.slot, mon.moves.index(self.move), **self.options(snapshot))


@dataclass
class Learn(CoreTask):
    """Answer a level-up learn-a-new-move prompt in battle. ``forget`` is a move slot or 'keep'."""
    forget: int | str

    battle = True

    def build(self, snapshot):
        return LearnMove(self.forget, **self.options(snapshot))


@dataclass
class Send(CoreTask):
    """Send out a party member in battle, from the battle menu or the forced party screen."""
    slot: int

    battle = True

    def build(self, snapshot):
        return SwitchPokemon(self.slot, **self.options(snapshot))


@dataclass
class Attack(CoreTask):
    """Choose a move from FIGHT."""
    slot: int

    battle = True

    def approach(self, screen):
        # The battle menu reads as dialogue while it draws. ChooseMove refuses there.
        return 'wait' if screen in ('dialogue', 'transition') else None

    def build(self, snapshot):
        return ChooseMove(self.slot, **self.options(snapshot))


@dataclass
class Flee(CoreTask):
    battle = True

    def build(self, snapshot):
        return RunAway(**self.options(snapshot))


TASKS = {cls.__name__: cls for cls in (Teach, Buy, Sell, Use, Storage, Remedy, Lead, FieldMove, Fly, Give, Take,
                                       Throw, Send, Attack, Flee, Forget, ChangeBox, Release, Learn, Radio, DayCare, ShowPartner)}
