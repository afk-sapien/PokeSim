"""Browser waits poll with a function, so the page's CSP never has to allow eval.

Playwright evaluates a wait_for_function string once from DevTools, where the CSP does not apply. A bare
expression is evaluated again on every later poll from the page, where script-src 'self' refuses it. An
arrow function is evaluated once and then only called, so it passes however long the wait takes.
"""
import ast
import re
from pathlib import Path

BROWSER_TESTS = Path(__file__).parent / 'browser'
FUNCTION = re.compile(r'\s*(async\s+)?(\(?[\w\s,\[\]{}]*\)?\s*=>|function\b)')


def first_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return node.values[0].value
    return None


def test_every_wait_for_function_is_given_a_function():
    bare = []
    for path in sorted(BROWSER_TESTS.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'wait_for_function' and node.args:
                text = first_text(node.args[0])
                if text is not None and not FUNCTION.match(text):
                    bare.append(f'{path.name}:{node.lineno}')
    assert not bare, f'pass an arrow function, not an expression: {bare}'


def test_the_check_tells_expressions_from_functions():
    assert FUNCTION.match('() => window.ready')
    assert FUNCTION.match('([low, high]) => low < high')
    assert FUNCTION.match('selector => document.querySelector(selector)')
    assert FUNCTION.match('\n    () => {')
    assert not FUNCTION.match('window.ready === true')
    assert not FUNCTION.match('[...document.images].every(image => image.complete)')
