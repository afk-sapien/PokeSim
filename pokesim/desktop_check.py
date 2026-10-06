"""Check bundled runtime resources using PyBoy's own demonstration ROM."""
import os
from pathlib import Path
import sys
import tempfile
import threading

from .desktop_setup import ensure_game_data


def check_runtime(reference_archive=None):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    with tempfile.TemporaryDirectory(prefix='pokesim-runtime-check-') as temporary:
        root = Path(temporary)
        ensure_game_data(root / 'game-data', print, threading.Event(), reference_archive)
        os.environ['DATA_DIR'] = str(root)
        os.environ['GAME_DATA_DIR'] = str(root / 'game-data')
        from pokesim_core.emulator import check_runtime as check_emulator
        from .emulator import Emulator
        from .store import Store
        from .web.app import create_app
        assert Emulator is not None
        store = Store(root)
        try:
            assert create_app(None, store) is not None
            check_emulator()
        finally:
            store.close()
    print('Desktop runtime passed: reference generation, native emulator, metadata, database, web resources')
