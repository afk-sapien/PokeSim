"""Fail unless the release pins are final. See tools/release_pins.py for what is checked."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_pins  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, default=release_pins.ROOT, help='checkout to inspect')
    parser.add_argument('--remote', action='store_true',
                        help='download every locked emulator asset and compare it with uv.lock and the Dockerfile')
    arguments = parser.parse_args()
    problems = release_pins.local_problems(arguments.tree)
    if arguments.remote and not problems:
        problems = release_pins.remote_problems(arguments.tree)
    if problems:
        print('Release pins are not final:', file=sys.stderr)
        for problem in problems:
            print('  ' + problem, file=sys.stderr)
        sys.exit(1)
    print('Release pins are final' + (' and match the published assets' if arguments.remote else ''))


if __name__ == '__main__':
    main()
