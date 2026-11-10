"""Synthetic tests for advance_dialogue, walk, stop reasons and the command catalog. No ROM needed."""
import inspect
import json

import pytest

import pokecore.shortcuts as shortcuts
from pokecore.controls import ControllerPort, switch_pokemon, use_item
from pokecore.gen1 import W_CUR_MAP, W_TILEMAP, W_X, W_Y
from pokecore.shortcuts import (STOP_REASONS, AdvanceDialogue, StopReason, Walk, advance_dialogue, describe,
                                    result_schema, walk)
from pokecore.shortcuts.dialogue import merge_lines
from pokecore.shortcuts.machine import Done
from pokecore.shortcuts.walk import W_PLAYER_FACING

from test_shortcuts import Game, put
from test_shortcuts_gen2 import Game2

DELTA = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
FACING = ('down', 'up', 'left', 'right')


class Field:
    """A Gen 1 overworld with walls, tile events, a framed text box and a YES/NO menu."""

    def __init__(self, x=5, y=5, facing='down', version=None):
        self.memory = bytearray(0x10000)
        self.memory[0xD163] = 1
        self.version = version
        self.x, self.y, self.map, self.facing = x, y, 1, facing
        self.walls, self.events = set(), {}
        self.kind, self.pages, self.then = 'overworld', [], None
        self.inputs, self.frame = [], 0
        self.locked_for = 0
        self.sync()

    def sync(self):
        memory = self.memory
        memory[W_CUR_MAP], memory[W_X], memory[W_Y] = self.map, self.x, self.y
        memory[W_PLAYER_FACING] = FACING.index(self.facing) << 2
        memory[0xCD6B] = 0xFF if self.locked_for else 0
        memory[W_TILEMAP:W_TILEMAP + 360] = bytes([0x7F]) * 360
        if self.kind == 'dialogue':
            memory[W_TILEMAP + 12 * 20] = 0x79
            first, _, second = self.pages[0].partition('|')
            put(memory, 1, 14, first)
            put(memory, 1, 16, second)
        elif self.kind == 'yes_no':
            put(memory, 15, 8, 'YES')
            put(memory, 15, 10, 'NO')
            memory[W_TILEMAP + 8 * 20 + 14] = 0xED

    def say(self, *pages, then='overworld'):
        self.kind, self.pages, self.then = 'dialogue', list(pages), then

    def send(self, button, hold, gap):
        self.frame += hold + gap
        if button is None:
            self.locked_for = max(0, self.locked_for - 1)
        else:
            self.inputs.append(button)
            self.press(button)
        self.sync()
        return self.frame < 200000

    def press(self, button):
        if self.kind == 'dialogue' and button == 'a':
            self.pages.pop(0)
            if not self.pages:
                then, self.kind = self.then, 'overworld'
                then() if callable(then) else setattr(self, 'kind', then)
        elif self.kind == 'overworld' and button in DELTA and not self.locked_for:
            if self.facing != button:
                self.facing = button
                return
            dx, dy = DELTA[button]
            if (self.x + dx, self.y + dy) in self.walls:
                return
            self.x, self.y = self.x + dx, self.y + dy
            event = self.events.pop((self.x, self.y), None)
            if event:
                event()

    def port(self):
        self.sync()
        return ControllerPort(self.memory, self.send, lambda label: False, lambda: {}, lambda: self.frame,
                              continue_ready=lambda: self.kind == 'dialogue',
                              panel=lambda memory, ui, labels: self.kind, version=self.version)


class Field2(Game2):
    """Game2 with a position, walls and tile events on the overworld."""

    def __init__(self, **kwargs):
        self.x, self.y, self.facing = 5, 5, 'down'
        self.walls, self.events = set(), {}
        super().__init__(**kwargs)

    def press_overworld(self, button):
        if button not in DELTA:
            return super().press_overworld(button)
        if self.facing != button:
            self.facing = button
            return
        dx, dy = DELTA[button]
        if (self.x + dx, self.y + dy) not in self.walls:
            self.x, self.y = self.x + dx, self.y + dy
            event = self.events.pop((self.x, self.y), None)
            if event:
                event()

    def sync(self):
        super().sync()
        self.put('wXCoord', [self.x])
        self.put('wYCoord', [self.y])
        self.put('wPlayerDirection', [FACING.index(self.facing) << 2])


def sc(result):
    return result['shortcut']


# Stop reasons on existing commands ---------------------------------------------

def test_every_result_carries_a_stop_reason_and_can_continue():
    game = Game(bag=[(0x14, 2)])
    refused = shortcuts.toss_item(game.port(), 0x99)
    assert sc(refused)['stop_reason'] == 'refused' and sc(refused)['can_continue'] is True
    assert game.inputs == []
    budget = shortcuts.reorder_party(Game().port(), 0, 1, max_steps=1)
    assert sc(budget)['stop_reason'] == 'budget' and sc(budget)['can_continue'] is False
    assert set(STOP_REASONS) == {reason.value for reason in StopReason}


def test_done_derives_a_reason_when_none_is_set():
    assert Done('x', True, True).stop_reason is StopReason.COMPLETED
    assert Done('x', True, False).stop_reason is StopReason.UNSETTLED
    assert Done('x', False, False).can_continue is False
    result = Done('x', True, True, {}, StopReason.PROMPT).as_result('demo')
    assert sc(result)['stop_reason'] == 'prompt' and sc(result)['can_continue'] is True


# Dialogue ----------------------------------------------------------------------

def test_merge_lines_skips_scrolled_lines_and_replaces_typing_ones():
    lines = []
    merge_lines(lines, ['Hello there!'])
    merge_lines(lines, ['Hello there!', 'Welcome to'])
    merge_lines(lines, ['Hello there!', 'Welcome to the world'])
    merge_lines(lines, ['Welcome to the world', 'of POKéMON!'])
    assert lines == ['Hello there!', 'Welcome to the world', 'of POKéMON!']


def test_dialogue_collects_every_page_and_stops_at_yes_no():
    field = Field()
    field.say('Hello there!|Welcome to', 'the world of|POKéMON!', 'Are you a boy?', then='yes_no')
    result = advance_dialogue(field.port())
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'choice' and shortcut['screen'] == 'yes_no'
    assert shortcut['completed'] and shortcut['can_continue']
    assert shortcut['lines'] == ['Hello there!', 'Welcome to', 'the world of', 'POKéMON!', 'Are you a boy?']
    assert shortcut['text'].startswith('Hello there! Welcome to')
    assert field.inputs == ['a', 'a', 'a'] and field.kind == 'yes_no'


def test_dialogue_stops_when_the_text_ends_and_never_answers_a_choice():
    field = Field()
    field.say('A sign.|Nothing more.')
    result = advance_dialogue(field.port())
    assert sc(result)['stop_reason'] == 'text_end' and sc(result)['completed']
    assert sc(result)['lines'] == ['A sign.', 'Nothing more.']
    field.kind = 'yes_no'
    again = advance_dialogue(field.port())
    assert sc(again)['stop_reason'] == 'choice' and field.inputs == ['a']


def test_dialogue_with_no_text_sends_nothing():
    field = Field()
    result = advance_dialogue(field.port())
    assert sc(result)['stop_reason'] == 'text_end' and not sc(result)['completed']
    assert sc(result)['can_continue'] and field.inputs == []


def test_dialogue_waits_out_a_script_after_the_box_closes():
    field = Field()
    field.say('Wait here.', then=lambda: (setattr(field, 'locked_for', 6), field.say('Okay, go!')))
    result = advance_dialogue(field.port())
    assert sc(result)['lines'] == ['Wait here.', 'Okay, go!'] and sc(result)['stop_reason'] == 'text_end'


def test_dialogue_gen2_collects_pages_and_stops_at_yes_no():
    game = Game2()
    game.say('Hello! Welcome to the world of POKéMON!', 'Are you ready?',
             then=lambda: game.yes_no('Are you ready?', yes=game.go_overworld, no=game.go_overworld))
    game.sync()
    result = advance_dialogue(game.port())
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'choice', result
    assert shortcut['choices'] == ['YES', 'NO']
    assert 'Welcome to the' in shortcut['text'] and shortcut['lines'][-1] == 'Are you ready?'
    assert game.inputs == ['a', 'a']


def test_dialogue_rejects_bad_options():
    with pytest.raises(ValueError):
        AdvanceDialogue(quiet=0)


# Walk --------------------------------------------------------------------------

def test_walk_turns_then_walks_the_full_distance():
    field = Field(facing='down')
    result = walk(field.port(), 'right', 3)
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'completed' and shortcut['completed'] and shortcut['can_continue']
    assert shortcut['tiles_moved'] == 3 and (field.x, field.y) == (8, 5)
    assert shortcut['start'] == {'map': 1, 'x': 5, 'y': 5} and shortcut['end'] == {'map': 1, 'x': 8, 'y': 5}
    assert shortcut['facing'] == 'right' and field.inputs.count('right') == 4


def test_walk_stops_at_a_wall():
    field = Field(facing='up')
    field.walls.add((5, 3))
    result = walk(field.port(), 'up', 5)
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'blocked' and not shortcut['completed'] and shortcut['can_continue']
    assert shortcut['tiles_moved'] == 1 and field.y == 4


def test_walk_stops_when_a_battle_starts():
    field = Field(facing='left')
    field.events[(3, 5)] = lambda: field.memory.__setitem__(0xD057, 1)
    result = walk(field.port(), 'left', 6)
    assert sc(result)['stop_reason'] == 'battle' and sc(result)['tiles_moved'] == 2


def test_walk_stops_at_a_map_change():
    field = Field(facing='down')
    field.events[(5, 6)] = lambda: (setattr(field, 'map', 2), setattr(field, 'y', 0))
    result = walk(field.port(), 'down', 4)
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'map_change' and shortcut['tiles_moved'] == 1
    assert shortcut['end'] == {'map': 2, 'x': 5, 'y': 0}


def test_walk_stops_when_text_opens():
    field = Field(facing='right')
    field.events[(6, 5)] = lambda: field.say('Hey! You there!')
    result = walk(field.port(), 'right', 4)
    assert sc(result)['stop_reason'] == 'dialogue' and field.kind == 'dialogue'
    assert field.inputs == ['right']


def test_walk_refuses_off_the_overworld_or_in_battle():
    field = Field()
    field.say('Hi.')
    assert sc(walk(field.port(), 'up'))['stop_reason'] == 'refused'
    field = Field()
    port = field.port()
    field.memory[0xD057] = 1
    assert sc(walk(port, 'up'))['stop_reason'] == 'refused' and field.inputs == []
    with pytest.raises(ValueError):
        Walk('north')
    with pytest.raises(ValueError):
        Walk('up', 0)


def test_walk_gen2_turns_walks_and_stops_at_a_wall():
    game = Field2()
    game.walls.add((5, 2))
    game.sync()
    result = walk(game.port(), 'up', 5)
    shortcut = sc(result)
    assert shortcut['stop_reason'] == 'blocked' and shortcut['tiles_moved'] == 2
    assert shortcut['start'] == {'map': [10, 1], 'x': 5, 'y': 5} and shortcut['facing'] == 'up'


def test_walk_gen2_stops_at_a_map_change():
    game = Field2()
    game.events[(6, 5)] = lambda: setattr(game, 'map', (10, 2))
    game.sync()
    result = walk(game.port(), 'right', 3)
    assert sc(result)['stop_reason'] == 'map_change' and sc(result)['end']['map'] == [10, 2]


# Catalog -----------------------------------------------------------------------

def test_catalog_describes_every_command_with_matching_arguments():
    described = {command['name']: command for command in describe()}
    json.dumps(described)
    commands = [name for name in shortcuts.__all__ if name.islower() and name not in (
        'continue_ready', 'current_screen', 'describe', 'drive', 'item_kind', 'item_names', 'list_box', 'list_items',
        'list_moves', 'list_party', 'move_names', 'result_schema', 'run', 'tm_number')]
    assert sorted(commands) == sorted(described)
    legacy = {'item_id', 'party_slot'}
    for name in commands:
        signature = inspect.signature(getattr(shortcuts, name))
        params = {p.name: p for p in signature.parameters.values()
                  if p.name != 'port' and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)}
        if name == 'use_item':
            params = {key: value for key, value in params.items() if key not in legacy}
        arguments = described[name]['arguments']
        assert set(params) <= set(arguments['properties']), name
        required = {key for key, p in params.items() if p.default is p.empty}
        if name == 'use_item':
            # item defaults to None only so the 0.3 name item_id can stand in for it.
            required.add('item')
        assert required == set(arguments['required']), name
        machine = getattr(shortcuts, described[name]['machine'])
        assert machine.kind == name


def test_catalog_filters_by_version():
    names = {command['name'] for command in describe(version='red')}
    assert 'give_item' not in names and 'walk' in names
    assert describe('change_box', version='red')['arguments']['properties']['box']['maximum'] == 11
    with pytest.raises(ValueError):
        describe('give_item', version='red')
    with pytest.raises(KeyError):
        describe('fly_anywhere')
    assert set(result_schema()['properties']['shortcut']['properties']['stop_reason']['enum']) == set(STOP_REASONS)


def test_merge_lines_keeps_a_finished_line_that_prefixes_the_next_page():
    lines = ['Welcome']
    merge_lines(lines, ['Welcome back!'], final=True)
    assert lines == ['Welcome', 'Welcome back!']
    lines = ['Welcome']
    merge_lines(lines, ['Welcome back!'])
    assert lines == ['Welcome back!']


def _abort_port(kind, after):
    from types import SimpleNamespace
    state = SimpleNamespace(kind=kind, frame=0, inputs=[])
    memory = bytearray(65536)
    memory[0xD057] = int(kind.startswith('battle') or kind == 'move_menu')

    def send(button, hold, gap):
        state.inputs.append(button)
        state.frame += hold + gap
        state.kind = after(state.kind, button)
        return True
    party = [dict(species=1, trainer_id=1, dvs=(0,) * 5, nick=n, hp=5, max_hp=9) for n in 'AB']
    port = ControllerPort(memory, send, lambda label: True, lambda: {}, lambda: state.frame,
                          read_party=lambda m: party, read_bag=lambda m: [(16, 1)], panel=lambda *a: state.kind)
    return state, port


@pytest.mark.parametrize('start, button, call', [
    ('overworld', 'start', lambda port: use_item(port, 16, 0)),
    ('move_menu', 'b', lambda port: switch_pokemon(port, 1)),
])
def test_abort_after_inputs_does_not_claim_the_screen_settled(start, button, call):
    state, port = _abort_port(start, lambda kind, pressed: 'naming' if pressed == button else kind)
    shortcut = sc(call(port))
    assert state.inputs and shortcut['settled'] is False and shortcut['can_continue'] is False


def test_abort_at_an_unanswered_prompt_reports_the_prompt():
    from pokecore.controls import machine_options
    from pokecore.shortcuts.machine import Abort, Shortcut, run

    class PromptAbort(Shortcut):
        def flow(self):
            yield 'a'
            raise Abort('Stopped at a game prompt the shortcut does not answer.', completed=False)
    state, port = _abort_port('overworld', lambda kind, pressed: 'yes_no' if pressed == 'a' else kind)
    shortcut = sc(run(port, PromptAbort(**machine_options(port))))
    assert state.kind == 'yes_no' and shortcut['stop_reason'] == 'prompt'
