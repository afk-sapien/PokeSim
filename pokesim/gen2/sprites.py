"""Gen II front portraits from the owner's verified cartridge, as PNG files.

Core decodes the pictures and palettes (``pokesim_core.gen2.sprites``). This module writes
them as PNG files for the web page.
"""
from pathlib import Path

from pokesim_core.gen2.sprites import decompress, offset, portrait as _portrait
from pokesim_core.sprites import png

from .data import GameData

__all__ = ['decompress', 'install', 'offset', 'portrait']


def portrait(raw, data, dex, *, shiny=False):
    """The 56 by 56 front portrait of ``dex`` as PNG bytes, with a transparent margin."""
    canvas, palette = _portrait(raw, data.game, dex, shiny=shiny)
    return png(canvas, palette)


def install(raw, root, destination, game):
    from ..checkpoints import CheckpointStore
    data = GameData.load(root, game)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'shiny').mkdir(exist_ok=True)
    for dex in range(1, 252):
        CheckpointStore.atomic_write(destination / f'{dex}.png', portrait(raw, data, dex))
        CheckpointStore.atomic_write(destination / 'shiny' / f'{dex}.png', portrait(raw, data, dex, shiny=True))
    return 251
