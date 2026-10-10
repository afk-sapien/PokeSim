"""Readable place and item names built from disassembly constants.

The constants drop apostrophes (DIGLETTS_CAVE, KINGS_ROCK), so names derived from
them read "Digletts Cave". These helpers only change what players read; map and
item constants and IDs stay the keys everywhere else.
"""
import re

# Words that are possessive when another word follows them in a place name.
_POSSESSIVE = {word: word[:-1] + "'s" for word in (
    'Agathas', 'Bills', 'Blues', 'Brunos', 'Captains', 'Champions', 'Copycats', 'Deleters',
    'Digletts', 'Dragons', 'Elms', 'Emys', 'Familys', 'Fujis', 'Gents', 'Grandpas', 'Karens',
    'Kogas', 'Kurts', 'Kyles', 'Lances', 'Loreleis', 'Manias', 'Neighbors', 'Oaks', 'Players',
    'Pokémons', 'Psychics', 'Raters', 'Reds', 'Seers', 'Sisters', 'Tims', 'Trios', 'Wardens', 'Wills')}
_POSSESSIVE.update({'Siblings': "Siblings'", 'Mr': 'Mr.', 'Poke': 'Poké'})


def place_name(name):
    """'Digletts Cave' -> "Diglett's Cave", 'Mr Fujis House' -> "Mr. Fuji's House"."""
    if not isinstance(name, str):
        return name
    words = name.split(' ')
    return ' '.join(_POSSESSIVE.get(word, word) if index < len(words) - 1 else word
                    for index, word in enumerate(words))


def title_name(text):
    """str.title() without capitalising after an apostrophe: "King's Rock", not "King'S Rock"."""
    return re.sub(r"(?<=\w')([A-Z])\b", lambda match: match[1].lower(), text.title())
