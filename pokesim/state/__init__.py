"""The one owner of each adventure's pokesim.sqlite: its schema version, and later its state domains.

Outside the worker's Store, ``state.connect(path, read_only=...)`` is the one way to open the file.
See docs/design/adventure-state-store.md.
"""
from .schema import connect

__all__ = ['connect']
