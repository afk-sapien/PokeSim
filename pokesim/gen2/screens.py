"""Screen text helpers that keep nicknames from posing as menu words.

The Gen 2 policy classifies screens by searching the 20x18 tilemap text. A
nickname such as CANCEL, PROTOTYPE or MOSQUITO shows up in the battle HUD and
the party roster, so plain substring search would read it as a menu label.
Two defences live here. HUD name fields are blanked, and keyword search uses
letter boundaries so a keyword only matches as a whole word.
"""
from ..textmatch import ScreenText as ScreenText, has_word as has_word

KEEP = set('│┌┐└┘─▶▷▼×')


def _blank(row, start, stop):
    chars = list(row)
    for col in range(start, min(stop, len(chars))):
        if chars[col] not in KEEP:
            chars[col] = ' '
    return ''.join(chars)


def is_roster(rows):
    """The party list shows nicknames on odd rows starting at column 3."""
    if len(rows) < 14 or rows[0].strip():
        return False
    named = [row for row in rows[1:12:2] if row[3:4].strip() and not row[1:3].strip(' ▶▷')]
    return bool(named) and all(not rows[index][:3].strip(' ▶▷') for index in range(1, 12, 2))


def mask_hud(rows):
    """Blank the enemy and player name fields of the battle HUD."""
    if is_roster(rows):
        return tuple(rows)
    out = list(rows)
    out[0] = _blank(out[0], 0, 13)
    out[7] = _blank(out[7], 9, 20)
    return tuple(out)


def mask_roster(rows):
    """Blank roster nicknames, used only for in-battle menu classification."""
    if not is_roster(rows):
        return tuple(rows)
    out = list(rows)
    for index in range(1, 12, 2):
        stop = 11 if '│' in out[index][11:14] else 13
        out[index] = _blank(out[index], 3, stop)
    return tuple(out)
