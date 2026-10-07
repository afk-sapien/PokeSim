"""Whole-word keyword search for decoded screen text.

Nicknames and item names can contain menu words (PROTOTYPE has TYPE, MOSQUITO has QUIT),
so a keyword counts only when it is not embedded in a longer run of letters.
"""
import re

_BOUNDARY = {}


def _pattern(key):
    pattern = _BOUNDARY.get(key)
    if pattern is None:
        head = r'(?<![A-Za-z])' if key[:1].isalpha() else ''
        tail = r'(?![A-Za-z])' if key[-1:].isalpha() else ''
        pattern = _BOUNDARY[key] = re.compile(head + re.escape(key) + tail)
    return pattern


def has_word(text, key):
    """True when key occurs in text and is not embedded in a longer word."""
    return key in text and _pattern(key).search(text) is not None


class ScreenText(str):
    """Screen text whose `in` operator matches whole words only."""

    def __contains__(self, key):
        if not isinstance(key, str) or not key:
            return str.__contains__(self, key)
        return has_word(str(self), key)
