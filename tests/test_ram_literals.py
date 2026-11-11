"""PokeSim reads game memory through pokecore names, never through new raw addresses.

Two kinds of read are counted in each module under pokesim/:

1. Hex literals that fall in cartridge RAM or WRAM (0xA000 to 0xDFFF) or in HRAM (0xFF80 to 0xFFFE).
2. Direct symbol reads, a string such as 'wEnemySubStatus5' passed as the first argument of a call
   (mem.byte, mem.word, mem.read, symbols.get) or used as a subscript key.

ALLOWED holds what each module had when this guard was added. A module may go below its allowance
but never above it, and a module not listed may have none. To fix a failure, name the address in
pokecore (pokecore.gen1, or a pokecore.state reader for Gen II) and read it by that name. When a
pull request removes reads, lower the module's numbers here with it. Run this file with Python to
print the current counts.
"""
import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'pokesim'
RAM_RANGES = ((0xA000, 0xDFFF), (0xFF80, 0xFFFE))
SYMBOL = re.compile(r'^[wsh][A-Z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)?$')

# Module: (raw RAM literals, direct symbol reads).
ALLOWED = {
    'pokesim/activity_ledger.py': (18, 0),
    'pokesim/catches.py': (8, 0),
    'pokesim/emulator.py': (2, 0),
    'pokesim/experimental/gen2.py': (18, 0),
    'pokesim/fair_dvs.py': (6, 0),
    'pokesim/gen2/activity.py': (1, 21),
    'pokesim/gen2/cable_verification.py': (0, 5),
    'pokesim/gen2/celebi.py': (0, 4),
    'pokesim/gen2/collection.py': (0, 8),
    'pokesim/gen2/contest.py': (0, 20),
    'pokesim/gen2/emulator.py': (0, 5),
    'pokesim/gen2/flight.py': (0, 2),
    'pokesim/gen2/gamecorner.py': (0, 1),
    'pokesim/gen2/headless.py': (0, 1),
    'pokesim/gen2/item_sources.py': (0, 5),
    'pokesim/gen2/kanto.py': (0, 2),
    'pokesim/gen2/legendary.py': (0, 2),
    'pokesim/gen2/menus.py': (0, 5),
    'pokesim/gen2/naming.py': (2, 4),
    'pokesim/gen2/navigation.py': (0, 2),
    'pokesim/gen2/npc_trades.py': (0, 3),
    'pokesim/gen2/policy.py': (0, 72),
    'pokesim/gen2/preparation.py': (0, 3),
    'pokesim/gen2/quests.py': (0, 2),
    'pokesim/gen2/returns.py': (0, 4),
    'pokesim/gen2/rewards.py': (0, 1),
    'pokesim/gen2/steps.py': (0, 1),
    'pokesim/gen2/store_stock.py': (1, 0),
    'pokesim/gen2/timecapsule.py': (0, 1),
    'pokesim/gen2/tower.py': (0, 7),
    'pokesim/gen2/tracking.py': (5, 17),
    'pokesim/gen2/trading.py': (0, 3),
    'pokesim/gen2/training.py': (0, 2),
    'pokesim/interactions/verification.py': (0, 6),
    'pokesim/policies/battle.py': (5, 0),
    'pokesim/policies/navigation.py': (2, 0),
    'pokesim/policies/strategic.py': (11, 0),
    'pokesim/policies/travel.py': (1, 0),
    'pokesim/ram.py': (1, 0),
    'pokesim/replay/rung.py': (2, 0),
    'pokesim/runtime/preparation.py': (5, 0),
    'pokesim/runtime/tm_purchase.py': (1, 0),
    'pokesim/scenarios.py': (4, 5),
    'pokesim/screen.py': (9, 0),
    'pokesim/shiny.py': (6, 0),
    'pokesim/step_events.py': (1, 0),
    'pokesim/trade/boxes.py': (1, 0),
    'pokesim/trade_statistics.py': (5, 0),
}


def raw_literals(source: str) -> int:
    count = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NUMBER and token.string[:2].lower() == '0x':
            value = int(token.string, 16)
            count += any(low <= value <= high for low, high in RAM_RANGES)
    return count


def _symbol(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(SYMBOL.match(node.value))


def symbol_reads(source: str) -> int:
    count = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and node.args and _symbol(node.args[0]):
            count += 1
        elif isinstance(node, ast.Subscript) and _symbol(node.slice):
            count += 1
    return count


def counts() -> dict[str, tuple[int, int]]:
    out = {}
    for path in sorted(ROOT.rglob('*.py')):
        source = path.read_text(encoding='utf-8')
        found = (raw_literals(source), symbol_reads(source))
        if any(found):
            out[path.relative_to(ROOT.parent).as_posix()] = found
    return out


def test_counters_see_each_kind_of_read():
    source = ("A = mem[0xD057] + mem[0xff80] + mem[2, 0xA000]\n"
              "B = 0x50 + 0xFFFF + 0x8000 + 53335\n"
              "C = mem.byte('wBattleMode') + data.symbols['hJoyPressed'] + mem.word('sBox.count')\n"
              "D = mem.byte(NAME) + names['party'] + log('wild')\n")
    assert raw_literals(source) == 3
    assert symbol_reads(source) == 3


def test_no_new_raw_ram_reads():
    failures = []
    for module, (literals, symbols) in counts().items():
        allowed_literals, allowed_symbols = ALLOWED.get(module, (0, 0))
        if literals > allowed_literals:
            failures.append(f'{module} has {literals} raw RAM literals, {allowed_literals} allowed')
        if symbols > allowed_symbols:
            failures.append(f'{module} has {symbols} direct symbol reads, {allowed_symbols} allowed')
    assert not failures, ('Read game memory through a pokecore name, not a raw address or symbol '
                          'string. See the docstring of tests/test_ram_literals.py.\n' + '\n'.join(failures))


if __name__ == '__main__':
    for module, found in counts().items():
        print(f'    {module!r}: {found},')
