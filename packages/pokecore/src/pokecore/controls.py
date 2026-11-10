"""Bounded controller macros for English Red, Blue and Yellow. No memory writes.

Callers supply observation and controller adapters. Every input passes through
send or choose, preserving the consumer's frame budget, recording and locking.
Party slots are zero based. These helpers never decide which Pokemon to train.

``use_item`` and ``switch_pokemon`` are blocking wrappers over the resumable
machines in :mod:`pokecore.shortcuts`, which hold every other shortcut.
"""
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping
import re

from .gen1 import read_bag, read_party
from .gen1_ui import read_screen
from .menus import menu_options

RESTORATIVE_ITEMS = frozenset((11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 52, 53, 54, 82, 83))


def normalize(text):
    return re.sub('[^A-Z0-9]', '', text.upper().replace('É', 'E'))


def identity(mon):
    return mon['species'], mon['trainer_id'], tuple(mon['dvs']), mon['nick']


def panel(memory, ui, item_labels):
    """Identify only observed menus needed for these mechanical commands."""
    if ui['kind'] in ('overworld', 'battle_menu', 'move_menu', 'dialogue', 'transition'):
        return ui['kind']
    if ui['kind'] != 'menu':
        return 'unknown'
    choices = {normalize(x) for x in ui['visible_choices']}
    if {'USE', 'TOSS'} <= choices:
        return 'item_action'
    if {'SWITCH', 'STATS', 'CANCEL'} <= choices:
        return 'party_action'
    if {'ITEM', 'EXIT', 'SAVE'} <= choices:
        return 'pause'
    if {'YES', 'NO'} <= choices:
        return 'switch_prompt' if 'CHANGE POK' in ' '.join(ui['text']).upper() else 'unknown'
    options = menu_options(memory, read_screen(memory), ui['kind'])
    if options and options[0]['text'].startswith('1: ') and ui['cursor_tile'][0] == 0:
        return 'item_target' if 'USE ITEM' in ' '.join(ui['text']).upper() else 'party'
    if (memory[0xCC25] == 5 and memory[0xCC24] == 4 and ui['cursor_tile']
            and ui['cursor_tile'][0] == 5 and ui['cursor_tile'][1] in (4, 6, 8)):
        bag = read_bag(memory)
        index = memory[0xCC26] + memory[0xCC36]
        if index < len(bag):
            label = item_labels.get(str(bag[index][0]), '')
            if isinstance(label, str) and normalize(ui['selected_text'] or '') == normalize(label):
                return 'bag'
        elif normalize(ui['selected_text'] or '') == 'CANCEL':
            return 'bag'
    return 'unknown'


def _never_ready():
    """Default ``continue_ready``: the port cannot tell, so shortcuts wait for text to stop changing."""
    return False


@dataclass
class ControllerPort:
    """Adapter to a serialized, budgeted consumer controller.

    send(button, held_frames, released_frames) and choose(visible_label) return
    False on budget exhaustion. Both must account for every emulated frame.
    observe returns the visible UI kind, text, cursor_tile, selected_text and
    visible_choices. continue_ready must only approve continue-only text waits.
    version is the cartridge version ('red', 'blue', 'yellow', 'gold', ...).
    """
    memory: object
    send: Callable
    choose: Callable
    observe: Callable
    frame: Callable
    stopped: Callable = lambda: False
    continue_ready: Callable = _never_ready
    item_labels: Mapping = field(default_factory=dict)
    read_party: Callable = read_party
    read_bag: Callable = read_bag
    panel: Callable = panel
    menu_rows: Callable | None = None
    version: str | None = None


def machine_options(port, **options):
    """Keyword arguments that build a shortcut machine reading through ``port``."""
    # The port defaults are the Red and Blue readers applied to raw memory. They misread
    # Yellow, whose WRAM is shifted by one byte, and Gen 2. Dropping them lets the
    # machine read through the layout of the cartridge it observes.
    read_party_ = None if port.read_party is read_party else port.read_party
    read_bag_ = None if port.read_bag is read_bag else port.read_bag
    return {'version': port.version, 'read_party': read_party_, 'read_bag': read_bag_,
            'labels': port.item_labels, **options}


def use_item(port, item=None, target=None, move=None, *, item_id=None, party_slot=None, **options):
    """Use one bag item and finish at a resting screen. See ``shortcuts.UseItem``.

    ``item`` is an item ID or a name. ``target`` is the party slot for items that
    ask for one, ``move`` the move slot for PP items. The 0.3 keyword names
    ``item_id`` and ``party_slot`` still work.
    """
    from .shortcuts.actions import UseItem
    from .shortcuts.machine import run
    if item_id is not None:
        if item is not None:
            raise TypeError('Pass item or item_id, not both')
        item = item_id
    if party_slot is not None:
        if target is not None:
            raise TypeError('Pass target or party_slot, not both')
        target = party_slot
    if item is None:
        raise TypeError('use_item needs an item')
    if type(target) is bool:
        raise ValueError('Party slot must be an integer from 0 through 5')
    machine = UseItem(item, target, move, **machine_options(port, **options))
    return run(port, machine)


def switch_pokemon(port, party_slot, **options):
    """Switch the active battler or move an owned Pokemon to the party lead."""
    from .shortcuts.actions import SwitchPokemon
    from .shortcuts.machine import run
    if type(party_slot) is not int or not 0 <= party_slot < 6:
        raise ValueError('Party slot must be an integer from 0 through 5')
    return run(port, SwitchPokemon(party_slot, **machine_options(port, **options)))
