"""Test the verified application data preparation path without Git or a ROM."""
from pathlib import Path
import threading

from pokesim.desktop_setup import ensure_game_data

if __name__ == '__main__':
    ensure_game_data(Path('data/game-data'), print, threading.Event())
