"""Checks from outside the app that refuse a request's values, each answered as a Conflict.

The game, its settings and the command line share these checks, so they raise a plain
ValueError. A plain ValueError that reaches the manager's handlers is answered as an unexpected
error, so every app module imports these checks from here instead. Each wrapped check takes the
same arguments, returns the same value and refuses with the same message as the one it wraps.
"""
from functools import wraps

from .. import cartridges, nicknames, palettes, randomized
from ..runtime import settings
from .errors import Conflict

__all__ = ['unpack', 'validate_generation_settings', 'validate_palette', 'validate_parts', 'validate_play_settings',
           'validate_randomizer', 'validate_speed', 'validate_starter', 'validate_trainer_name']


def refused_as_conflict(check):
    """The same check, with a ValueError it raises turned into a Conflict that keeps its message."""
    @wraps(check)
    def checked(*args, **kwargs):
        try:
            return check(*args, **kwargs)
        except Conflict:
            raise
        except ValueError as error:
            raise Conflict(str(error)) from error
    return checked


# A ZIP without exactly one cartridge, or a file that is not a supported game, is the uploader's mistake.
unpack = refused_as_conflict(cartridges.unpack)
validate_generation_settings = refused_as_conflict(cartridges.validate_generation_settings)
validate_starter = refused_as_conflict(cartridges.validate_starter)
validate_parts = refused_as_conflict(nicknames.validate_parts)
validate_trainer_name = refused_as_conflict(nicknames.validate_trainer_name)
validate_palette = refused_as_conflict(palettes.validate_palette)
validate_randomizer = refused_as_conflict(randomized.validate)
validate_play_settings = refused_as_conflict(settings.validate_play_settings)
validate_speed = refused_as_conflict(settings.validate_speed)
