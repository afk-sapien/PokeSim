"""Keep every pinned PokeSim version equal to the package version, and move them all at once.

The release Compose files, installers and docs name the exact release they install. A release that bumps
pyproject.toml but misses one of them ships a quickstart that installs the previous version, so the release
pin checks fail while any pin differs from the package version. Prepare a release with:

    python tools/release_version.py 0.6.2       # rewrite every pin to 0.6.2
    python tools/release_version.py --check     # list pins that differ from pyproject.toml

After a release is published, main moves to the next development version, such as 0.7.0.dev0. A
development version moves only the package pins. The install pins keep naming the published release,
since no image or download exists for a development version.
"""
import argparse
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = r'\d+\.\d+\.\d+(?:rc\d+)?'
DEVELOPMENT = r'\d+\.\d+\.\d+\.dev\d+'
VERSION = r'(?P<version>' + RELEASE + ')'
PACKAGE_VERSION = r'(?P<version>' + RELEASE + '|' + DEVELOPMENT + ')'
IMAGE = r'ghcr\.io/afk-sapien/pokesim:' + VERSION + r'\b'
WHEEL = r'releases/download/v' + VERSION + r'/pokesim-(?P=version)-py3'
# The package pins name the version being built. The rest install a published release.
PACKAGE_PINS = [
    ('pyproject.toml', r'^version = "' + PACKAGE_VERSION + '"$'),
    ('pokesim/__init__.py', r'^__version__ = "' + PACKAGE_VERSION + '"$'),
    ('uv.lock', r'^name = "pokesim"\nversion = "' + PACKAGE_VERSION + '"$'),
    ('Dockerfile', r'^ARG VERSION=' + PACKAGE_VERSION + '$'),
]
# (path, pattern). Each pattern must match at least once, and its version group is the pin.
PINS = PACKAGE_PINS + [
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
    ('docs/publishing.md', r'(?:\bv|PokeSim )' + VERSION + r'\b'),
    ('deploy/stores/unraid/pokesim.xml', IMAGE),
    ('deploy/stores/casaos/docker-compose.yml', IMAGE),
    ('deploy/stores/umbrel/pokesim/docker-compose.yml', IMAGE),
    ('deploy/stores/umbrel/pokesim/umbrel-app.yml', r'^version: "' + VERSION + '"$'),
    ('deploy/stores/truenas/pokesim/app.yaml', r'^app_version: ' + VERSION + '$'),
    ('deploy/stores/truenas/pokesim/ix_values.yaml', r'^    tag: ' + VERSION + '$'),
]


def package_version(root=ROOT):
    return tomllib.loads((Path(root) / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']


def installed_version(root=ROOT):
    """The published release most install pins name, or None when no install pin is found."""
    root = Path(root)
    versions = Counter(match.group('version') for name, pattern in PINS[len(PACKAGE_PINS):] if (root / name).is_file()
                       for match in re.finditer(pattern, (root / name).read_text(encoding='utf-8'), re.M))
    return versions.most_common(1)[0][0] if versions else None


def version_problems(root=ROOT):
    """Every pin that is missing or names a version other than the package version.

    Under a development version, the install pins must instead agree on one published release."""
    root = Path(root)
    package = package_version(root)
    development = re.fullmatch(DEVELOPMENT, package)
    problems = []
    found = {}
    for name, pattern in PINS:
        path = root / name
        if not path.is_file():
            problems.append(f'{name} is missing')
            continue
        versions = [match.group('version') for match in re.finditer(pattern, path.read_text(encoding='utf-8'), re.M)]
        if not versions:
            problems.append(f'{name} has no version pin matching {pattern!r}')
        found[name, pattern] = versions
    release = installed_version(root) if development else package
    for pin, versions in found.items():
        expected = package if pin in PACKAGE_PINS else release
        problems.extend(f'{pin[0]} pins {version}, not {expected}' for version in versions if version != expected)
    return problems


def bump(root, version):
    """Rewrite every pin to `version`, or only the package pins for a development version.

    Fails before writing anything if a pin cannot be found."""
    development = re.fullmatch(DEVELOPMENT, version)
    if not development and not re.fullmatch(RELEASE, version):
        raise ValueError(f'Invalid release version: {version}')
    root = Path(root)
    contents = {}
    for name, pattern in PACKAGE_PINS if development else PINS:
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
