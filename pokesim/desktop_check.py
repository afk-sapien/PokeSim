"""Check bundled runtime resources using PyBoy's own demonstration ROM."""
from importlib.metadata import version
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
        import pyboy
        from .emulator import Emulator
        from .store import Store
        from .web.app import create_app
        assert Emulator is not None
        assert version('pyboy') == '2.7.0'
        store = Store(root)
        try:
            assert create_app(None, store) is not None
            emulator = pyboy.PyBoy(str(Path(pyboy.__file__).with_name('default_rom.gb')),
                                  window='null', sound_emulated=False)
            try:
                emulator.set_emulation_speed(0)
                emulator.tick(30)
                assert emulator.screen.ndarray.shape == (144, 160, 4)
            finally:
                emulator.stop(save=False)
        finally:
            store.close()
    print('Desktop runtime passed: reference generation, native emulator, metadata, database, web resources')
