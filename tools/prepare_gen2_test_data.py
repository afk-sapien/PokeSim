"""Generate the Gen II game data the regression tests read.

Downloads pinned pret sources through the same verified path the app uses and
writes the data folder. No cartridge is needed or read.

    python tools/prepare_gen2_test_data.py .release-local/gen2-data
    GEN2_DATA_DIR=.release-local/gen2-data pytest tests
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokesim.gen2.data import ensure  # noqa: E402

GAMES = ('gold', 'silver', 'crystal')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    for game in GAMES:
        ensure(args.directory, game, report=print)
    print(f'Gen II data ready in {args.directory}')


if __name__ == '__main__':
    main()
