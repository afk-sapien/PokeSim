"""The one owner of each adventure's pokesim.sqlite: its schema version, and later its state domains.

Outside the worker's Store, ``state.connect(path, read_only=...)`` is the one way to open the file.
See docs/design/adventure-state-store.md.
"""
from sqlite3 import Error

from .schema import connect

# Error is what a failed statement raises, for a caller that keeps going without it.
__all__ = ['Error', 'connect']
