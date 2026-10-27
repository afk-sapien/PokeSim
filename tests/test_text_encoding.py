"""Every text read and write in pokesim and tools names UTF-8, so Windows does not fall back to its ANSI code page.

Ruff's PLW1514 only sees calls on values it can tell are paths, so this walks the source instead. It checks
the builtin open, read_text and write_text, and any .open call given a text mode such as 'w' or 'a'.
Binary modes need no encoding.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('pokesim', 'tools')
TEXT_MODE = re.compile(r'[rwax+t]+')


def mode(call, position):
    for keyword in call.keywords:
        if keyword.arg == 'mode':
            return keyword.value
    return call.args[position] if len(call.args) > position else None


def unencoded(call):
    if any(keyword.arg == 'encoding' for keyword in call.keywords):
        return False
    func = call.func
    if isinstance(func, ast.Name):
        if func.id != 'open':
            return False
        given = mode(call, 1)
        return given is None or not (isinstance(given, ast.Constant) and 'b' in str(given.value))
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in {'read_text', 'write_text'}:
        return True
    if func.attr == 'open':
        given = mode(call, 0)
        return isinstance(given, ast.Constant) and isinstance(given.value, str) and bool(TEXT_MODE.fullmatch(given.value))
    return False


def test_every_text_read_and_write_names_an_encoding():
    found = []
    for path in sorted(path for source in SOURCES for path in (ROOT / source).rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and unencoded(node):
                found.append(f'{path.relative_to(ROOT)}:{node.lineno}: {ast.unparse(node)}')
    assert not found, "Pass encoding='utf-8':\n" + '\n'.join(found)


def test_the_check_catches_each_kind_of_call():
    calls = ["open(name)", "open(name, 'w')", "path.read_text()", "path.write_text(text)", "path.open('a')"]
    allowed = ["open(name, 'rb')", "path.open('wb')", "archive.open(entry)", "webbrowser.open(url)",
               "path.read_text(encoding='utf-8')", "open(name, 'w', encoding='utf-8')"]
    assert all(unencoded(ast.parse(code).body[0].value) for code in calls)
    assert not any(unencoded(ast.parse(code).body[0].value) for code in allowed)
