"""Describe mechanical controls. Consumers decide which ones a task may expose."""
from copy import deepcopy
from .movement import DIRECTIONS

_SPECS = {
    'walk_tiles': {'function': 'pokecore.movement.walk_tiles', 'versions': ['red', 'blue'],
                   'starts': ['overworld'], 'arguments': {
                       'direction': {'type': 'string', 'enum': list(DIRECTIONS)},
                       'count': {'type': 'integer', 'minimum': 1, 'maximum': 8}},
                   'decisions': 'Caller chooses direction and distance. No route planning.'},
    'collect_dialogue': {'function': 'pokecore.dialogue.collect_dialogue', 'versions': ['red', 'blue'],
                         'starts': ['dialogue', 'transition', 'overworld'], 'arguments': {},
                         'decisions': 'Continues text only. Stops before choices.'},
    'choose_move': {'function': 'pokecore.shortcuts.choose_move', 'versions': ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'],
                    'starts': ['battle_menu', 'move_menu'], 'arguments': {
                        'slot': {'type': 'integer', 'minimum': 0, 'maximum': 3}},
                    'decisions': 'Caller selects the move slot. Battle turns still occur.'},
    'switch_pokemon': {'function': 'pokecore.shortcuts.switch_pokemon', 'versions': ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'],
                       'starts': ['overworld', 'pause', 'party', 'battle_menu', 'move_menu', 'switch_prompt'],
                       'arguments': {'party_slot': {'type': 'integer', 'minimum': 0, 'maximum': 5}},
                       'decisions': 'Caller selects the party member.'},
    'use_item': {'function': 'pokecore.shortcuts.use_item', 'versions': ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal'],
                 'starts': ['overworld', 'pause', 'bag', 'party', 'item_target', 'battle_menu', 'move_menu'],
                 'arguments': {'item': {'type': 'integer', 'minimum': 1, 'maximum': 255},
                               'target': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 5},
                               'move': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 3}},
                 'decisions': 'Caller selects the item and all required targets.'},
}


def capabilities(version='red'):
    """Return detached descriptors for this control family, not an exhaustive Core API list.

    Starts describe normal entry screens, not permission to act or proof a target
    is available. Controls validate the actual game state when called. Consumers
    must intersect these capabilities with their own task permissions.
    """
    if version not in ('red', 'blue', 'yellow', 'gold', 'silver', 'crystal'):
        raise ValueError('Unsupported cartridge version')
    return {name: deepcopy(spec) for name, spec in _SPECS.items() if version in spec['versions']}


def capability(name, version='red'):
    """Return one descriptor, rejecting unsupported commands or game versions."""
    options = capabilities(version)
    if name not in options:
        raise ValueError(f'{name} is not supported for {version}')
    return options[name]
