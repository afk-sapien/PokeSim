"""The Gold, Silver and Crystal naming keyboard, on synthetic memory laid out by Core's memory maps."""
from collections import defaultdict
from types import SimpleNamespace

import pytest

from pokecore.gen2 import charmap, memory_map
from pokecore.naming import GEN2_KEYS, enter_name, gen2_name_step, gen2_naming

CURSOR_OBJECT = 0xC800
DESTINATION = 0xD100


class Keyboard:
    """Banked memory holding an open keyboard. ``press`` acts as the game does on each button."""

    def __init__(self, version, *, limit=7, entered='', lowercase=False):
        self.version = version
        self.banks = defaultdict(lambda: bytearray(65536))
        self.symbols = memory_map.symbols(version)
        self.encode = {char: code for code, char in charmap.charmap(version).items() if len(char) == 1}
        self.x = self.y = 0
        self.lowercase = lowercase
        self.text = entered
        self.limit = limit
        self.closed = False
        self.draw()

    def __getitem__(self, key):
        bank, address = key if isinstance(key, tuple) else (0, key)
        return self.banks[bank][address]

    def put(self, name, data):
        bank, address = self.symbols[name]
        self.banks[bank][address:address + len(data)] = bytes(data)

    def draw(self):
        rows = [' ' * 20] * 18
        if not self.closed:
            for row, start in enumerate(range(0, 27, 9)):
                keys = GEN2_KEYS[start:start + 9]
                rows[8 + 2 * row] = '  ' + ' '.join(keys.lower() if self.lowercase else keys).ljust(17) + ' '
        self.put('wTilemap', [self.encode.get(char, 0x7F) for row in rows for char in row])
        self.put('wNamingScreenCursorObjectPointer', CURSOR_OBJECT.to_bytes(2, 'little'))
        self.banks[0][CURSOR_OBJECT + 12:CURSOR_OBJECT + 14] = bytes((self.x, self.y))
        self.put('wNamingScreenDestinationPointer', DESTINATION.to_bytes(2, 'little'))
        self.banks[1][DESTINATION:DESTINATION + 11] = bytes(self.encode[c] for c in self.text) + b'\x50' * (
            11 - len(self.text))
        self.put('wNamingScreenCurNameLength', [len(self.text)])
        self.put('wNamingScreenMaxNameLength', [self.limit])
        self.put('wNamingScreenLetterCase', [int(self.lowercase)])
        self.put('wNamingScreenType', [1])

    def press(self, button):
        if button == 'start':
            self.x, self.y = 6, 4
        elif button == 'select':
            self.lowercase = not self.lowercase
        elif button == 'b':
            self.text = self.text[:-1]
        elif button in ('up', 'down'):
            self.y = (self.y + (1 if button == 'down' else -1)) % 5
        elif button in ('left', 'right'):
            self.x = (self.x + (1 if button == 'right' else -1)) % 9
        elif button == 'a':
            if self.y == 4 and self.x >= 6:
                self.closed = True
            elif self.y < 4 and len(self.text) < self.limit:
                self.text += GEN2_KEYS[self.y * 9 + self.x]
        self.draw()


@pytest.mark.parametrize('version', ['gold', 'crystal'])
def test_keyboard_reads_back_the_typed_name(version):
    keyboard = Keyboard(version, entered='GO')
    view = gen2_naming(keyboard, version)
    assert view == {'entered': 'GO', 'length': 2, 'limit': 7, 'cursor': (0, 0), 'lowercase': False,
                    'subject': 'player'}
    keyboard.closed = True
    keyboard.draw()
    assert gen2_naming(keyboard, version) is None
    assert gen2_name_step(keyboard, version, 'GOLD') is None


def test_name_step_types_deletes_and_submits():
    keyboard = Keyboard('crystal', entered='GX')
    assert gen2_name_step(keyboard, 'crystal', 'GO-L.D!').button == 'b'
    keyboard.press('b')
    keyboard.lowercase = True
    keyboard.draw()
    assert gen2_name_step(keyboard, 'crystal', 'GO').button == 'select'
    keyboard.press('select')
    presses = 0
    while not keyboard.closed:
        keyboard.press(gen2_name_step(keyboard, 'crystal', 'GO-L.D!').button)
        presses += 1
        assert presses < 100
    assert keyboard.text == 'GO-L.D!'


def test_name_step_refuses_what_the_keyboard_cannot_take():
    keyboard = Keyboard('gold', limit=7)
    with pytest.raises(ValueError, match='at most 7'):
        gen2_name_step(keyboard, 'gold', 'TOOLONGNAME'[:8])
    for invalid in ('', 'gold', 'Ä', 'ELEVENCHARS'):
        with pytest.raises(ValueError):
            gen2_name_step(keyboard, 'gold', invalid)


def test_enter_name_follows_the_port_version():
    keyboard = Keyboard('silver', entered='SIL')
    sent = []

    def send(button, hold=6, gap=24):
        sent.append(button)
        if button:
            keyboard.press(button)
        return True
    port = SimpleNamespace(memory=keyboard, version='silver', send=send, stopped=lambda: False,
                           observe=lambda: {'kind': 'naming'})
    result = enter_name(port, 'SILVER')
    assert result == {'completed': True, 'outcome': 'Name submitted.'}
    assert keyboard.text == 'SILVER' and sent[-1] == 'a' and sent.count('a') == 4
