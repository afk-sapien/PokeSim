"""Whether Red, Blue, Yellow, Gold, Silver or Crystal waits for a button, read from live stack words.

``input_wait`` is true while the game waits at a continue-only text prompt (``continue_ready`` in
Gen 1, ``cont_wait`` in Gen 2) or inside a menu's input loop, and its last joypad read saw every
button up. The loops are found in the home bank once per cartridge header, so no generation byte
is read:

- Red, Blue and Yellow poll every menu in HandleMenuInput_, whose loop calls AnimatePartyMon,
  JoypadLowSensitivity and HandleDownArrowBlinkTiming.
- Gold, Silver and Crystal enter every menu through StaticMenuJoypad or ScrollingMenuJoypad, home
  routines that farcall the bank 9 loop and then call GetMenuJoypad. The return of that farcall
  is in the home bank, so it is the same address whatever bank the loop runs in.

The game counts a button as pressed only when its previous read saw it up. A press that comes
before the game has read the last one's release is lost, so the held byte that read leaves must
be zero. JoypadLowSensitivity (Gen 1) and JoyTextDelay (Gen 2) load that byte right after the
read, which gives its address.
"""
from __future__ import annotations

import re

from .gen2ui import cont_returns
from .screens import _wait_returns

# HandleMenuInput_: ... / push hl / ld a, [wPartyMenuAnimMonEnabled] / and a / jr z / ... / call AnimatePartyMon
# by Bankswitch / pop hl / call JoypadLowSensitivity / ldh a, [hJoy5] / and a / jr nz / push hl / hlcoord / call
# HandleDownArrowBlinkTiming.
_GEN1_MENU = (rb'\xaf\xea..\xcd..\xcd..\xe5\xfa..\xa7\x28.\x06.\x21..\xcd..(?P<anim>)\xe1\xcd..(?P<joypad>)'
              rb'\xf0.\xa7\x20.\xe5\x21..\xcd..(?P<arrow>)')
# StaticMenuJoypad and ScrollingMenuJoypad: ld hl, loop / ld a, 9 / rst FarCall / call GetMenuJoypad / ret.
_GEN2_MENU = rb'\x21..\x3e\x09\xcf(?P<back>)\xcd..\xc9'
# JoypadLowSensitivity and JoyTextDelay: call the joypad read / ldh a, [flag] / and a / ldh a, [pressed] /
# jr z, +2 / ldh a, [held] / ldh [out], a. The held byte is hJoyHeld in Gen 1 and hJoyDown in Gen 2.
_HELD = rb'\xcd..\xf0.\xa7\xf0.\x28\x02\xf0(?P<held>.)\xe0'
_CACHE = {}


def _waits(memory):
    """The stack words that mean the game waits, and the address of the held byte its joypad read leaves."""
    header = bytes(memory[0x134:0x150])
    if header not in _CACHE:
        home = bytes(memory[0:0x4000])
        text, pokedex = _wait_returns(memory)
        returns = set()
        if text:
            menus = list(re.finditer(_GEN1_MENU, home, re.DOTALL))
            returns = text | pokedex
            if len(menus) == 1:
                returns |= {menus[0].start(name) for name in ('anim', 'joypad', 'arrow')}
        elif prompts := cont_returns(memory):
            menus = list(re.finditer(_GEN2_MENU, home, re.DOTALL))
            returns = set(prompts)
            if len(menus) == 2:
                returns |= {menu.start('back') for menu in menus}
        held = list(re.finditer(_HELD, home, re.DOTALL))
        if len(held) != 1:
            returns = set()
        _CACHE[header] = (frozenset(returns), 0xFF00 | held[0]['held'][0] if returns else None)
    return _CACHE[header]


def input_wait(memory, sp):
    """True while the game waits for a button it would read as new: a continue-only text prompt or a
    menu's input loop, with every button up at its last joypad read.

    ``memory`` is raw emulator memory and ``sp`` the CPU stack pointer. Only live stack words are
    read, in one slice. False when the stack is outside WRAM or the cartridge has none of the waits.
    """
    if not 0xC000 <= sp < 0xE000:
        return False
    memory = getattr(memory, 'raw', memory)
    returns, held = _waits(memory)
    if not returns or memory[held]:
        return False
    raw = bytes(memory[sp:min(sp + 80, 0xDFFF)])
    return any(raw[i] | raw[i + 1] << 8 in returns for i in range(0, len(raw) - 1, 2))
