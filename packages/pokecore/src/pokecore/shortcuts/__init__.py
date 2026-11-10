"""Resumable menu shortcuts for Red, Blue, Yellow, Gold, Silver and Crystal, plus read-only queries.

Each action is a machine with ``step(memory, ui) -> button | None | Done``: one
input per call, no memory writes. ``run(port, machine)`` is the blocking wrapper
over a ``controls.ControllerPort`` and ``drive(machine, emulator)`` runs one on a
Core emulator. The functions below build a machine and run it on a port.
Gen 2 machines resolve menu labels themselves, so ``run`` sends only single
buttons through ``port.send`` on Gold, Silver and Crystal.
"""
from ..controls import machine_options, switch_pokemon, use_item
from .actions import (BuyItem, ChangeBox, ChooseMove, DayCare, DeleteMove, DepositItem, DepositPokemon, FieldMove,
                      GiveItem, LearnMove, Radio, ReleasePokemon, ReorderParty, TakeItem, RunAway, SellItem,
                      ShowPartner, SwitchPokemon, TossItem, UseItem, WithdrawItem, WithdrawPokemon)
from .catalog import describe, result_schema
from .dialogue import AdvanceDialogue
from .items import ItemKind, item_kind, item_names, move_names, tm_number
from .machine import STOP_REASONS, Abort, Choose, Done, Shortcut, StopReason, drive, run
from .queries import current_screen, list_box, list_items, list_moves, list_party
from .screens import SCREENS, continue_ready
from .walk import Walk


def _run(port, cls, *args, **options):
    return run(port, cls(*args, **machine_options(port, **options)))


def choose_move(port, slot, **options):
    """Pick move ``slot`` (0 to 3) in battle. Done when the turn starts."""
    return _run(port, ChooseMove, slot, **options)


def run_away(port, **options):
    """Choose RUN in a wild battle. ``shortcut['escaped']`` says whether it worked."""
    return _run(port, RunAway, **options)


def reorder_party(port, first, second, **options):
    """Swap two party slots outside battle."""
    return _run(port, ReorderParty, first, second, **options)


def use_field_move(port, move, slot, destination=None, **options):
    """Use a field move from party ``slot``. FLY needs a town ``destination``.

    Gen 1: CUT, SURF, STRENGTH, FLASH, FLY. Gen 2 adds WHIRLPOOL, WATERFALL, ROCK SMASH and HEADBUTT.
    """
    return _run(port, FieldMove, move, slot, destination, **options)


def toss_item(port, item, quantity=1, **options):
    return _run(port, TossItem, item, quantity, **options)


def buy_item(port, item, quantity=1, **options):
    """Buy at a mart. Start at the clerk's BUY/SELL/QUIT menu."""
    return _run(port, BuyItem, item, quantity, **options)


def sell_item(port, item, quantity=1, **options):
    """Sell at a mart. Start at the clerk's BUY/SELL/QUIT menu."""
    return _run(port, SellItem, item, quantity, **options)


def deposit_pokemon(port, slot, **options):
    """Deposit party ``slot`` in the current box. Start at the PC menu or BILL's PC."""
    return _run(port, DepositPokemon, slot, **options)


def withdraw_pokemon(port, position, **options):
    """Withdraw current-box ``position`` to the party. Start at the PC menu or BILL's PC."""
    return _run(port, WithdrawPokemon, position, **options)


def release_pokemon(port, position, *, allow_release=False, **options):
    """Release current-box ``position``. Refuses unless ``allow_release=True``."""
    return run(port, ReleasePokemon(position, allow_release=allow_release, **machine_options(port, **options)))


def deposit_item(port, item, quantity=1, **options):
    """Store an item in the player's PC. Start at the PC menu or the item menu."""
    return _run(port, DepositItem, item, quantity, **options)


def withdraw_item(port, item, quantity=1, **options):
    """Take an item from the player's PC. Start at the PC menu or the item menu."""
    return _run(port, WithdrawItem, item, quantity, **options)


def give_item(port, item, slot, *, swap=False, **options):
    """Gen 2: give a bag item to party ``slot`` to hold. ``swap=True`` trades a held item back to the bag."""
    return run(port, GiveItem(item, slot, swap=swap, **machine_options(port, **options)))


def take_item(port, slot, **options):
    """Gen 2: take party ``slot``'s held item into the bag."""
    return _run(port, TakeItem, slot, **options)


def learn_move(port, forget, **options):
    """Answer the learn-a-new-move prompt on screen: forget move slot ``forget`` (0 to 3), or ``'keep'``."""
    return _run(port, LearnMove, forget, **options)


def change_box(port, box, **options):
    """Make ``box`` (0 based) the current box. Start at the PC menu or BILL's PC. This saves the game."""
    return _run(port, ChangeBox, box, **options)


def delete_move(port, slot, move_slot, **options):
    """Gen 2: at the Move Deleter, make party ``slot`` forget ``move_slot``. Start at his greeting."""
    return _run(port, DeleteMove, slot, move_slot, **options)


def tune_radio(port, station=78, music=0x40, **options):
    """Gen 2: tune the Pokégear radio to ``station``. The default is the Poké Flute channel."""
    return _run(port, Radio, station, music, **options)


def day_care(port, parent, slot=None, **options):
    """Gen 2: leave party ``slot`` at Day Care place ``parent``, or take it back with ``slot=None``."""
    return _run(port, DayCare, parent, slot, **options)


def show_partner(port, slot, event, **options):
    """Gen 2: show party ``slot`` to a person who asks, until event flag ``event`` turns on."""
    return _run(port, ShowPartner, slot, event, **options)


def advance_dialogue(port, **options):
    """Advance text and collect it. Stops at a choice or menu, or once the text ends and the player has control."""
    return _run(port, AdvanceDialogue, **options)


def walk(port, direction, tiles=1, **options):
    """Walk up to ``tiles`` tiles toward ``direction``. Stops early at an obstacle, a battle, a map change or text."""
    return _run(port, Walk, direction, tiles, **options)


__all__ = ['Abort', 'AdvanceDialogue', 'BuyItem', 'ChangeBox', 'Choose', 'ChooseMove', 'DayCare', 'DeleteMove',
           'DepositItem', 'DepositPokemon', 'Done', 'FieldMove', 'GiveItem', 'ItemKind', 'LearnMove', 'Radio',
           'ReleasePokemon', 'ReorderParty', 'RunAway', 'SCREENS', 'STOP_REASONS', 'SellItem', 'Shortcut',
           'ShowPartner', 'StopReason', 'SwitchPokemon', 'TakeItem', 'TossItem', 'UseItem', 'Walk', 'WithdrawItem',
           'WithdrawPokemon', 'advance_dialogue', 'buy_item', 'change_box', 'choose_move', 'continue_ready',
           'current_screen', 'day_care', 'delete_move', 'deposit_item', 'deposit_pokemon', 'describe', 'drive',
           'give_item', 'item_kind', 'item_names', 'learn_move', 'list_box', 'list_items', 'list_moves', 'list_party',
           'move_names', 'release_pokemon', 'reorder_party', 'result_schema', 'run', 'run_away', 'sell_item',
           'show_partner', 'switch_pokemon', 'take_item', 'tm_number', 'toss_item', 'tune_radio', 'use_field_move',
           'use_item', 'walk', 'withdraw_item', 'withdraw_pokemon']
