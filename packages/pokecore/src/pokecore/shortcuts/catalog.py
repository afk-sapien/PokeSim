"""Machine-readable descriptions of every shortcut, for consumers that build a tool list.

``describe()`` returns one plain dict per command, safe for ``json.dumps``:
its name, the machine class, a summary, the generations it runs on, a JSON
Schema ``arguments`` object, the ``start`` preconditions (the screens it may
start from and whether a battle is required or ruled out), and the result keys
it adds. ``result_schema()`` describes the result dict that every command
returns. Core only describes what each command does. Which commands a consumer
offers, and when, is the consumer's policy.
"""
from __future__ import annotations

import copy

from ..cartridges import generation
from .items import GEN1_FIELD_MOVES, GEN2_FIELD_MOVES
from .machine import BACKABLE, STOP_REASONS
from .walk import DIRECTIONS, MAX_TILES

# Screens a field command (one that opens the start menu) may start from.
FIELD_SCREENS = ('overworld', 'dialogue', 'transition', *BACKABLE)
# Screens a battle command may start from. Text in between is advanced.
BATTLE_SCREENS = ('battle_menu', 'move_menu', 'bag', 'party', 'party_action', 'item_action', 'item_target', 'menu',
                  'dialogue', 'transition')
PC_SCREENS = ('pc', 'bills_pc')
ITEM_PC_SCREENS = ('pc', 'players_pc')


def _int(low, high, text):
    return {'type': 'integer', 'minimum': low, 'maximum': high, 'description': text}


ITEM = {'type': ['integer', 'string'], 'minimum': 1, 'maximum': 255,
        'description': 'Item ID (1 to 255) or item name, as list_items shows it.'}
QUANTITY = _int(1, 99, 'How many.')
PARTY_SLOT = _int(0, 5, 'Party slot, 0 based.')
MOVE_SLOT = _int(0, 3, 'Move slot, 0 based.')
SLOT_OR_KEEP = {'anyOf': [{'type': 'integer', 'minimum': 0, 'maximum': 3}, {'type': 'string', 'const': 'keep'}]}
BOX_POSITION = _int(0, 19, 'Position in the current PC box, 0 based.')
OPTIONS = {
    'max_steps': {'type': 'integer', 'minimum': 1,
                  'description': 'Observation budget. The command stops with stop_reason "budget" past it.'},
    'nickname': {'type': 'string', 'enum': ['no', 'caller'], 'default': 'no',
                 'description': 'At a nickname prompt, answer NO ("no") or stop there for the caller ("caller").'},
}


def _start(screens, battle='any', note=None):
    start = {'screens': list(screens), 'battle': battle}
    if note:
        start['note'] = note
    return start


def _command(name, machine, summary, properties=None, required=(), *, start, generations=(1, 2), returns=None,
             field_and_battle=False):
    entry = {
        'name': name, 'machine': machine, 'summary': summary, 'generations': list(generations),
        'arguments': {'type': 'object', 'properties': properties or {}, 'required': list(required),
                      'additionalProperties': False},
        'options': copy.deepcopy(OPTIONS), 'start': start, 'returns': returns or {},
    }
    if field_and_battle:
        entry['start']['battle_screens'] = list(BATTLE_SCREENS)
    return entry


def _catalog():
    field_moves = sorted(set(GEN1_FIELD_MOVES) | set(GEN2_FIELD_MOVES))
    return [
        _command('use_item', 'UseItem', 'Use one bag item, in battle or outside it.',
                 {'item': ITEM,
                  'target': {**PARTY_SLOT, 'description': 'Party slot for items that ask for one, 0 based.'},
                  'move': {**MOVE_SLOT, 'description': 'Move slot for PP items, 0 based.'},
                  'forget_move': {**SLOT_OR_KEEP,
                                  'description': 'For a TM or HM when four moves are known: the slot to forget, '
                                                 'or "keep".'}},
                 ['item'], start=_start(FIELD_SCREENS, note='In battle, starts from battle_screens.'),
                 field_and_battle=True, returns={'item_id': 'integer'}),
        _command('switch_pokemon', 'SwitchPokemon',
                 'In battle, switch the active Pokemon. Outside battle, move a party Pokemon to the lead.',
                 {'party_slot': PARTY_SLOT}, ['party_slot'],
                 start=_start(FIELD_SCREENS, note='In battle, starts from battle_screens.'), field_and_battle=True),
        _command('choose_move', 'ChooseMove', 'Pick a move in battle. Done when the turn starts.',
                 {'slot': MOVE_SLOT}, ['slot'], start=_start(('battle_menu', 'move_menu'), 'required')),
        _command('run_away', 'RunAway', 'Choose RUN in a wild battle.', {}, (),
                 start=_start(BATTLE_SCREENS, 'required', note='Wild battles only.'), returns={'escaped': 'boolean'}),
        _command('reorder_party', 'ReorderParty', 'Swap two party slots outside battle.',
                 {'first': PARTY_SLOT, 'second': PARTY_SLOT}, ['first', 'second'],
                 start=_start(FIELD_SCREENS, 'forbidden')),
        _command('use_field_move', 'FieldMove', 'Use a field move from a party Pokemon outside battle.',
                 {'move': {'type': 'string', 'enum': field_moves,
                           'description': 'Gen 1 has CUT, FLY, SURF, STRENGTH and FLASH. Gen 2 adds the rest.'},
                  'slot': PARTY_SLOT,
                  'destination': {'type': 'string', 'description': 'Town name. Required for FLY.'}},
                 ['move', 'slot'], start=_start(FIELD_SCREENS, 'forbidden'),
                 returns={'move': 'string', 'party_slot': 'integer'}),
        _command('toss_item', 'TossItem', 'Toss bag items outside battle.',
                 {'item': ITEM, 'quantity': QUANTITY}, ['item'], start=_start(FIELD_SCREENS, 'forbidden')),
        _command('buy_item', 'BuyItem', 'Buy at a mart.', {'item': ITEM, 'quantity': QUANTITY}, ['item'],
                 start=_start(('mart',), 'forbidden', note="The clerk's BUY/SELL/QUIT menu."),
                 returns={'item_id': 'integer', 'quantity': 'integer'}),
        _command('sell_item', 'SellItem', 'Sell at a mart.', {'item': ITEM, 'quantity': QUANTITY}, ['item'],
                 start=_start(('mart',), 'forbidden', note="The clerk's BUY/SELL/QUIT menu."),
                 returns={'item_id': 'integer', 'quantity': 'integer'}),
        _command('deposit_pokemon', 'DepositPokemon', 'Deposit a party Pokemon in the current box.',
                 {'slot': PARTY_SLOT}, ['slot'], start=_start(PC_SCREENS, 'forbidden')),
        _command('withdraw_pokemon', 'WithdrawPokemon', 'Withdraw a Pokemon from the current box to the party.',
                 {'position': BOX_POSITION}, ['position'], start=_start(PC_SCREENS, 'forbidden'),
                 returns={'box_position': 'integer'}),
        _command('release_pokemon', 'ReleasePokemon', 'Release a Pokemon from the current box.',
                 {'position': BOX_POSITION,
                  'allow_release': {'type': 'boolean', 'default': False,
                                    'description': 'Must be true, or the command refuses.'}},
                 ['position'], start=_start(PC_SCREENS, 'forbidden'), returns={'box_position': 'integer'}),
        _command('deposit_item', 'DepositItem', "Store an item in the player's PC.",
                 {'item': ITEM, 'quantity': QUANTITY}, ['item'], start=_start(ITEM_PC_SCREENS, 'forbidden'),
                 returns={'item_id': 'integer', 'quantity': 'integer'}),
        _command('withdraw_item', 'WithdrawItem', "Take an item from the player's PC.",
                 {'item': ITEM, 'quantity': QUANTITY}, ['item'], start=_start(ITEM_PC_SCREENS, 'forbidden'),
                 returns={'item_id': 'integer', 'quantity': 'integer'}),
        _command('give_item', 'GiveItem', 'Give a bag item to a party Pokemon to hold.',
                 {'item': ITEM, 'slot': PARTY_SLOT,
                  'swap': {'type': 'boolean', 'default': False,
                           'description': 'Trade a held item back to the bag instead of refusing.'}},
                 ['item', 'slot'], start=_start(FIELD_SCREENS, 'forbidden'), generations=(2,)),
        _command('take_item', 'TakeItem', "Take a party Pokemon's held item into the bag.",
                 {'slot': PARTY_SLOT}, ['slot'], start=_start(FIELD_SCREENS, 'forbidden'), generations=(2,)),
        _command('learn_move', 'LearnMove', 'Answer the learn-a-new-move prompt on screen.',
                 {'forget': {**SLOT_OR_KEEP, 'description': 'Move slot to forget (0 to 3), or "keep".'}},
                 ['forget'], start=_start(('dialogue', 'yes_no', 'move_list'),
                                          note='A learn-a-new-move prompt is on screen.'),
                 returns={'forget': ['integer', 'string']}),
        _command('change_box', 'ChangeBox', 'Make another PC box current. This saves the game.',
                 {'box': _int(0, 13, 'Box, 0 based. Gen 1 has boxes 0 to 11.')}, ['box'],
                 start=_start(PC_SCREENS, 'forbidden'), returns={'box': 'integer'}),
        _command('delete_move', 'DeleteMove', 'Have the Move Deleter make a party Pokemon forget a move.',
                 {'slot': PARTY_SLOT, 'move_slot': MOVE_SLOT}, ['slot', 'move_slot'],
                 start=_start(('dialogue', 'yes_no'), 'forbidden', note="The Move Deleter's greeting is on screen."),
                 generations=(2,), returns={'party_slot': 'integer', 'move_slot': 'integer'}),
        _command('tune_radio', 'Radio', 'Tune the Pokegear radio to a station and listen.',
                 {'station': {**_int(0, 255, 'Tuning knob position. 78 is the Poke Flute channel.'), 'default': 78},
                  'music': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 255, 'default': 0x40,
                            'description': 'Map music ID that proves the station plays, or null for none.'}},
                 (), start=_start(('overworld', 'pause'), 'forbidden', note='The Pokegear has its radio card.'),
                 generations=(2,), returns={'station': 'integer'}),
        _command('day_care', 'DayCare', 'Leave a party Pokemon at the Day Care, or take one back.',
                 {'parent': _int(0, 1, 'Day Care place: 0 for the Day-Care Man, 1 for the Day-Care Lady.'),
                  'slot': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 5, 'default': None,
                           'description': 'Party slot to leave, 0 based, or null to take the Pokemon back.'}},
                 ['parent'], start=_start(('dialogue', 'yes_no'), 'forbidden',
                                          note="That Day Care person's greeting is on screen."),
                 generations=(2,), returns={'parent': 'integer', 'action': 'string', 'party_slot': 'integer'}),
        _command('show_partner', 'ShowPartner', 'Show a party Pokemon to a person who asks to see one.',
                 {'slot': PARTY_SLOT, 'event': _int(0, 2047, 'Event flag that turns on once the person saw it.')},
                 ['slot', 'event'], start=_start(('dialogue', 'yes_no'), 'forbidden',
                                                 note="The person's greeting is on screen."),
                 generations=(2,), returns={'party_slot': 'integer', 'event': 'integer'}),
        _command('advance_dialogue', 'AdvanceDialogue',
                 'Advance printed text and collect it. Stops at a choice or menu, or when the text ends.',
                 {'quiet': _int(1, 60, 'Observations with player control before the text counts as ended.'),
                  'patience': _int(1, 1000, 'Observations of an unchanged screen with no prompt before stopping.')},
                 (), start=_start(('dialogue', 'transition', 'unknown', 'overworld'),
                                  note='Any other screen counts as a choice and returns at once with no input.'),
                 returns={'lines': 'array', 'text': 'string', 'truncated': 'boolean', 'screen': 'string',
                          'choices': 'array'}),
        _command('walk', 'Walk',
                 'Walk up to N tiles in one direction. Stops early at an obstacle, a battle, a map change, or text.',
                 {'direction': {'type': 'string', 'enum': list(DIRECTIONS)},
                  'tiles': {**_int(1, MAX_TILES, 'Tiles to walk.'), 'default': 1},
                  'patience': _int(1, 60, 'Observations to wait for a step before calling the way blocked.')},
                 ['direction'], start=_start(('overworld',), 'forbidden', note='No game script holds the controls.'),
                 returns={'direction': 'string', 'requested': 'integer', 'tiles_moved': 'integer',
                          'start': 'object', 'end': 'object', 'facing': 'string'}),
    ]


def result_schema():
    """The result dict every command returns: ``outcome`` plus the ``shortcut`` dict."""
    return {
        'type': 'object',
        'properties': {
            'outcome': {'type': 'string', 'description': 'One plain sentence about what happened.'},
            'shortcut': {'type': 'object', 'properties': {
                'kind': {'type': 'string', 'description': 'The command name.'},
                'completed': {'type': 'boolean', 'description': 'The requested effect happened.'},
                'settled': {'type': 'boolean', 'description': 'The screen came to rest.'},
                'stop_reason': {'type': 'string', 'enum': list(STOP_REASONS), 'description': 'Why it stopped.'},
                'can_continue': {'type': 'boolean',
                                 'description': 'Another command can start without inspecting the screen first.'},
            }, 'required': ['kind', 'completed', 'settled', 'stop_reason', 'can_continue']},
        },
        'required': ['outcome', 'shortcut'],
    }


def describe(name=None, version=None):
    """Describe every command, or only ``name``. ``version`` keeps the commands that game supports.

    Returns a list of dicts, or one dict when ``name`` is given. Raises KeyError for an
    unknown name and ValueError when ``version`` does not support it.
    """
    gen = generation(version) if version is not None else None
    commands = _catalog()
    if gen is not None:
        for command in commands:
            if command['name'] == 'change_box' and gen == 1:
                command['arguments']['properties']['box']['maximum'] = 11
                command['arguments']['properties']['box']['description'] = 'Box, 0 based.'
            if command['name'] == 'use_field_move':
                moves = GEN2_FIELD_MOVES if gen == 2 else GEN1_FIELD_MOVES
                command['arguments']['properties']['move']['enum'] = sorted(moves)
        commands = [command for command in commands if gen in command['generations']]
    if name is None:
        return commands
    for command in commands:
        if command['name'] == name:
            return command
    if any(command['name'] == name for command in _catalog()):
        raise ValueError(f'{name} is not available on {version}')
    raise KeyError(name)
