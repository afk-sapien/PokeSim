"""The adventure seed and the random streams drawn from it, so a replay makes the same choices.

Every random choice the bot makes comes from the adventure seed: the policy's own generator, the
adventure choices, the idle after a reload, Gen II names and the gift seeds. A stream is a
generator seeded from the SHA-256 of the seed and its labels, so it needs no saved state and the
same labels always draw the same numbers. docs/design/replayable-bugs.md section 4.1.
"""
import hashlib
import random
import secrets

from . import config

KEY = 'adventure-seed-v1'
# A reload idles 1 to this many frames to move the game's random numbers along.
RELOAD_IDLE = 180


def adventure_seed(store):
    """This run's seed, created once and kept in the store. ``SEED`` overrides it for tests and gates.

    A restart clears it, so each new game from power-on gets its own starter and choices.
    """
    if config.SEED is not None:
        return config.SEED
    value = store.get(KEY)
    if not isinstance(value, int) or isinstance(value, bool):
        value = secrets.randbits(64)
        store.set(KEY, value)
    return value


def stream(seed, *labels):
    """A generator that draws the same numbers for the same seed and labels."""
    text = '\n'.join(str(part) for part in (seed, *labels))
    return random.Random(int.from_bytes(hashlib.sha256(text.encode()).digest(), 'big'))


def reload_idle(seed, clock_frames):
    """Frames to idle after a reload. PlayClock frames never rewind, so two reloads of one save differ."""
    return 1 + stream(seed, 'reload', clock_frames).randrange(RELOAD_IDLE)


def gift_seed(seed, kind, championships):
    """The seed a gift's bytes come from, one per kind and championship count."""
    return f'{stream(seed, "gift", kind, championships).getrandbits(128):032x}'
