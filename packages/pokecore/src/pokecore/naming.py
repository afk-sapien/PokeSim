"""Observed, resumable name entry through the English Red/Blue and Gold/Silver/Crystal keyboards."""
from typing import NamedTuple

from .gen1_ui import read_screen

GEN2_VERSIONS = ('gold', 'silver', 'crystal')
# The Gen 2 upper case keyboard, nine keys to a row. Row 4 holds lower, DEL and END.
GEN2_KEYS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ -?!/.,'
# wNamingScreenType & 7: what is being named. Other values name a box or an unused subject.
GEN2_SUBJECTS = {0: 'pokemon', 1: 'player', 2: 'rival'}


class ButtonAction(NamedTuple):
    button: str | None
    hold: int = 6
    gap: int = 24


def validate_name(name, *, limit=10):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Name limit must be from 1 through 10')
    if not isinstance(name, str) or not 1 <= len(name) <= limit or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in name):
        raise ValueError(f'Name must contain 1 through {limit} uppercase ASCII letters')
    return name


def name_step(rows, cursor, name, *, limit=10):
    """Return the next keyboard action. Return None outside the naming screen.

    Read back entered letters on every call, including after restoring a save.
    The caller owns name selection and whether to accept a nickname prompt.
    """
    validate_name(name, limit=limit)
    if not any(row[2:19:2] in ('ABCDEFGHI', 'abcdefghi') for row in rows):
        return None
    entered = rows[2][10:10 + limit].strip()
    if not name.startswith(entered):
        return ButtonAction('b')
    if entered == name:
        return ButtonAction('start')
    if any(row[2:19:2] == 'abcdefghi' for row in rows):
        return ButtonAction('select')
    if cursor is None:
        return ButtonAction(None, 0, 12)
    offset = ord(name[len(entered)]) - ord('A')
    target_x, target_y = 1 + offset % 9 * 2, 5 + offset // 9 * 2
    x, y = cursor
    button = ('down' if y < target_y else 'up') if y != target_y else (
        ('right' if x < target_x else 'left') if x != target_x else 'a')
    return ButtonAction(button)


def validate_gen2_name(name, *, limit=10):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Name limit must be from 1 through 10')
    if not isinstance(name, str) or not 1 <= len(name) <= limit or any(c not in GEN2_KEYS for c in name):
        raise ValueError(f'Name must contain 1 through {limit} of {GEN2_KEYS!r}')
    return name


def _gen2_reader(memory, version):
    from .gen2.state import memory_reader
    return memory_reader(memory, version)


def gen2_naming(memory, version):
    """The open Gen 2 naming keyboard as a dict, or None when it is not on screen.

    ``entered`` is the text typed so far, read back from the name's destination.
    ``cursor`` is the (column, row) of the key under the cursor, with row 4 holding
    lower, DEL and END. ``subject`` names what is being named.
    """
    from .gen2.ram import tile_rows
    mem = _gen2_reader(memory, version)
    rows = tile_rows(mem.read('wTilemap', 360), mem.data)
    if not any(row[2:19:2] in ('ABCDEFGHI', 'abcdefghi') for row in rows):
        return None
    pointer = int.from_bytes(mem.read('wNamingScreenCursorObjectPointer', 2), 'little')
    if not 0xC000 <= pointer < 0xD000:
        return None
    cursor = mem.raw(0, pointer, 16)
    length = min(mem.byte('wNamingScreenCurNameLength'), 10)
    destination = int.from_bytes(mem.read('wNamingScreenDestinationPointer', 2), 'little')
    entered = None
    if 0xC000 <= destination < 0xE000:
        typed = mem.raw(1 if destination >= 0xD000 else 0, destination, length)
        entered = ''.join(mem.data.charmap.get(value, '\0') for value in typed)
    return {'entered': entered, 'length': length, 'limit': mem.byte('wNamingScreenMaxNameLength'),
            'cursor': (cursor[12], cursor[13]), 'lowercase': bool(mem.byte('wNamingScreenLetterCase')),
            'subject': GEN2_SUBJECTS.get(mem.byte('wNamingScreenType') & 7, 'other')}


def gen2_name_step(memory, version, name):
    """Return the next Gold, Silver or Crystal keyboard action, or None outside the keyboard.

    ``memory`` is banked emulator memory. Entered letters are read back on every call,
    so a restored save resumes, and a wrong letter is deleted with B. The name may use
    capital letters, space and ``-?!/.,``, up to the keyboard's own limit (10 for a
    Pokémon or a box, 7 for the player and rival).
    """
    validate_gen2_name(name)
    view = gen2_naming(memory, version)
    if view is None:
        return None
    if 1 <= view['limit'] < len(name):
        raise ValueError(f'This keyboard takes at most {view["limit"]} characters')
    entered = view['entered']
    if entered is not None and not name.startswith(entered):
        return ButtonAction('b')
    x, y = view['cursor']
    if view['length'] >= len(name):
        # START moves the cursor to END. A on END submits.
        return ButtonAction('a' if y == 4 and x >= 6 else 'start')
    if view['lowercase']:
        return ButtonAction('select')
    index = GEN2_KEYS.index(name[view['length']])
    target_x, target_y = index % 9, index // 9
    button = ('down' if y < target_y else 'up') if y != target_y else (
        ('right' if x < target_x else 'left') if x != target_x else 'a')
    return ButtonAction(button)


def enter_name(port, name, *, limit=10, max_actions=256, version=None):
    """Enter a supplied name through a ControllerPort, with a bounded result.

    Start on the naming keyboard. A successful result means the supplied text
    was observed and submitted and the keyboard subsequently closed. ``version``
    defaults to ``port.version``. Gold, Silver and Crystal use the Gen 2 keyboard.
    """
    version = version if version is not None else port.version
    gen2 = version in GEN2_VERSIONS
    (validate_gen2_name if gen2 else validate_name)(name, limit=limit)
    if type(max_actions) is not int or not 1 <= max_actions <= 1024:
        raise ValueError('max_actions must be from 1 through 1024')
    submitted = False
    for _ in range(max_actions):
        if port.stopped():
            break
        if port.observe()['kind'] == 'transition':
            if not port.send(None, 12, 0):
                break
            continue
        if gen2:
            view = gen2_naming(port.memory, version)
            action = gen2_name_step(port.memory, version, name)
            # A on END submits a Gen 2 name.
            final = action is not None and action.button == 'a' and view['length'] >= len(name)
        else:
            screen = read_screen(port.memory, raw_text=True)
            action = name_step(screen['rows'], screen['cursor'], name, limit=limit)
            final = action is not None and action.button == 'start'
        if action is None:
            return {'completed': submitted, 'outcome': 'Name submitted.' if submitted else 'Naming keyboard is not open.'}
        if submitted:
            # Never submit twice if the game is still closing its keyboard.
            action = ButtonAction(None, 12, 0)
        if not port.send(*action):
            break
        submitted |= final
    return {'completed': False, 'outcome': 'Name entry stopped at its controller budget.'}


def menu_button(current, target):
    """Choose one direction or confirmation for a zero based linear menu."""
    if any(type(value) is not int or value < 0 for value in (current, target)):
        raise ValueError('Menu positions must be nonnegative integers')
    return 'a' if current == target else 'down' if current < target else 'up'
