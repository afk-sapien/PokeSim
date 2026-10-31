"""Keep every pinned PokeSim version equal to the package version, and move them all at once.

The release Compose files, installers and docs name the exact release they install. A release that bumps
pyproject.toml but misses one of them ships a quickstart that installs the previous version, so the release
pin checks fail while any pin differs from the package version. Prepare a release with:

    python tools/release_version.py 0.6.2       # rewrite every pin to 0.6.2
    python tools/release_version.py --check     # list pins that differ from pyproject.toml
"""
import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r'(?P<version>\d+\.\d+\.\d+(?:rc\d+)?)'
IMAGE = r'ghcr\.io/afk-sapien/pokesim:' + VERSION + r'\b'
WHEEL = r'releases/download/v' + VERSION + r'/pokesim-(?P=version)-py3'
# (path, pattern). Each pattern must match at least once, and its version group is the pin.
PINS = [
    ('pyproject.toml', r'^version = "' + VERSION + '"$'),
    ('uv.lock', r'^name = "pokesim"\nversion = "' + VERSION + '"$'),
    ('Dockerfile', r'^ARG VERSION=' + VERSION + '$'),
    ('install.sh', r'^    version=' + VERSION + '$'),
    ('install.ps1', r"^\$version = '" + VERSION + "'$"),
    ('compose.yaml', IMAGE),
    ('compose.quickstart.yaml', IMAGE),
    ('.env.example', IMAGE),
    ('deploy/compose.broker.yaml', IMAGE),
    ('deploy/compose.trading.yaml', IMAGE),
    ('docs/licensing.md', IMAGE),
    ('docs/self-hosting.md', IMAGE),
    ('docs/self-hosting.md', r'`download/v' + VERSION + '`'),
    ('README.md', WHEEL),
    ('docs/desktop.md', WHEEL),
    ('deploy/stores/unraid/pokesim.xml', IMAGE),
    ('deploy/stores/casaos/docker-compose.yml', IMAGE),
    ('deploy/stores/umbrel/pokesim/docker-compose.yml', IMAGE),
    ('deploy/stores/umbrel/pokesim/umbrel-app.yml', r'^version: "' + VERSION + '"$'),
    ('deploy/stores/truenas/pokesim/app.yaml', r'^app_version: ' + VERSION + '$'),
    ('deploy/stores/truenas/pokesim/ix_values.yaml', r'^    tag: ' + VERSION + '$'),
]


def package_version(root=ROOT):
    return tomllib.loads((Path(root) / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']


def version_problems(root=ROOT):
    """Every pin that is missing or names a version other than the package version."""
    root = Path(root)
    expected = package_version(root)
    problems = []
    for name, pattern in PINS:
        path = root / name
        if not path.is_file():
            problems.append(f'{name} is missing')
            continue
        found = [match.group('version') for match in re.finditer(pattern, path.read_text(encoding='utf-8'), re.M)]
        if not found:
            problems.append(f'{name} has no version pin matching {pattern!r}')
        problems.extend(f'{name} pins {version}, not {expected}' for version in found if version != expected)
    return problems


def bump(root, version):
    """Rewrite every pin to `version`. Fails before writing anything if a pin cannot be found."""
    if not re.fullmatch(VERSION, version):
        raise ValueError(f'Invalid release version: {version}')
    root = Path(root)
    contents = {}
    for name, pattern in PINS:
        text = contents.get(name) or (root / name).read_text(encoding='utf-8')
        # A wheel URL names the version twice, so every copy inside the match moves.
        text, count = re.subn(pattern, lambda match: match.group(0).replace(match.group('version'), version),
                              text, flags=re.M)
        if not count:
            raise ValueError(f'{name} has no version pin matching {pattern!r}')
        contents[name] = text
    for name, text in contents.items():
        (root / name).write_text(text, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('version', nargs='?', help='new release version')
    parser.add_argument('--check', action='store_true', help='only report pins that differ from pyproject.toml')
    arguments = parser.parse_args()
    if arguments.check == bool(arguments.version):
        parser.error('give either a version or --check')
    if arguments.version:
        bump(ROOT, arguments.version)
    problems = version_problems(ROOT)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        sys.exit(1)
    print(f'Every pin names {package_version(ROOT)}')


if __name__ == '__main__':
    main()
