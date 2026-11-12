"""Where each story step happens, read from gen1.json and gen2.json beside this file.

A row names a step's map and either a tile to stand on (x, y and the way to face) or the object to
walk up to, and what the game holds once the step is done ("done_when"). The rows are in play order,
which tools/map_audit.py walks to check each step can be reached from the one before. Which step
is offered next, and which side of a choice is taken, stay in the policy code.

A key may hold several rows, as Giovanni's door has two guards in Red and Blue, and code asks for
the first row whose done_when flags are not all set. A row may override fields for one game, as in
"yellow": {"y": 0}, and "games" limits a row to the games it names. Red stands for Red and Blue,
which share their data. "{starter}" and "{fossil}" in a row are filled with the run's choice.

In gen2.json the three "starter" rows name the starter each one picks, and a row with "points" in
place of a tile lists the spots a moving target can stand at, in the game's own order, as the lost
Farfetch'd in Ilex Forest. "then" is where the game puts the player once the step is done, when a
scene moves them on, as the Champion's room hands over to the Hall of Fame. "places" are tiles and
objects off the story chain, such as the way out of a puzzle room.
"""
import json
from functools import lru_cache
from importlib import resources

GAMES = frozenset({'red', 'yellow', 'gold', 'silver', 'crystal'})


@lru_cache(maxsize=None)
def manifest(generation):
    text = resources.files(__name__).joinpath(f'gen{generation}.json').read_text(encoding='utf-8')
    return json.loads(text)


def merged(entries, game):
    """The entries that apply to ``game``, each with its overrides for that game applied."""
    found = []
    for entry in entries:
        if game in entry.get('games', (game,)):
            shared = {key: value for key, value in entry.items() if key not in GAMES and key != 'games'}
            found.append({**shared, **entry.get(game, {})})
    return tuple(found)


@lru_cache(maxsize=None)
def steps(generation, game):
    """The story rows of ``game`` in play order, with its overrides applied."""
    return merged(manifest(generation)['steps'], game)


@lru_cache(maxsize=None)
def place(generation, game, key):
    """A place a goal off the story chain uses, such as the PC that swaps a field-move partner in."""
    found = [entry for entry in merged(manifest(generation).get('places', ()), game) if entry['key'] == key]
    if len(found) != 1:
        raise KeyError(f'{key} has {len(found)} places in {game}')
    return found[0]


def start(generation):
    """Where a new game puts the player, as {map, x, y}."""
    return manifest(generation)['start']


def rows(generation, game, key):
    """Every row of ``key`` in ``game``, in play order."""
    found = tuple(row for row in steps(generation, game) if row['key'] == key)
    if not found:
        raise KeyError(f'No story row named {key} in {game}')
    return found


def row(generation, game, key):
    """The one row of ``key`` in ``game``."""
    found = rows(generation, game, key)
    if len(found) != 1:
        raise KeyError(f'{key} has {len(found)} story rows in {game}, so name the row to use')
    return found[0]


def fill(text, **choices):
    """``text`` with "{starter}" and "{fossil}" filled from ``choices``."""
    return text.format(**choices) if '{' in text else text
