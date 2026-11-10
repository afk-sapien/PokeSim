"""Check a pokecore release tag against the workspace member, and its built wheel against the source.

The pokecore release workflow runs this on the tagged commit:

    python tools/pokecore_release.py pokecore-v0.11.1 --notes notes.md
    python tools/pokecore_release.py pokecore-v0.11.1 --wheel dist/pokecore-0.11.1-py3-none-any.whl

It fails unless the tag is pokecore-v<version>, `packages/pokecore/pyproject.toml` and `pokecore.__version__`
both name that version, and `packages/pokecore/CHANGELOG.md` has a `## <version>` section with text. It
prints `version=<version>` for the workflow's outputs and writes that section to the notes file. With
`--wheel` it also fails when the wheel's pokecore files differ from `packages/pokecore/src/pokecore`, the
same comparison `tools/check_release_pins.py --remote` makes against the published wheel later.
"""
import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_pins  # noqa: E402

ROOT = release_pins.ROOT
MEMBER = Path('packages/pokecore')
TAG = re.compile(r'pokecore-v(\d+\.\d+\.\d+(?:rc\d+)?)')


def member_versions(root):
    """Return the member's pyproject version and its `__version__`, which is None when it has none."""
    member = Path(root) / MEMBER
    project = tomllib.loads((member / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    init = (member / 'src' / 'pokecore' / '__init__.py').read_text(encoding='utf-8')
    match = re.search(r'''^__version__ = ["']([^"']+)["']$''', init, re.M)
    return project, match.group(1) if match else None


def changelog_section(root, version):
    """The text under `## <version>` in the member's changelog, up to the next `## ` heading."""
    section, inside = [], False
    for line in (Path(root) / MEMBER / 'CHANGELOG.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            if inside:
                break
            inside = line[3:].strip() == version
            continue
        if inside:
            section.append(line)
    return '\n'.join(section).strip()


def check(root, tag):
    """Return (version, release notes, problems) for a release tag."""
    match = TAG.fullmatch(tag)
    if match is None:
        return None, '', [f'{tag!r} is not a pokecore-vX.Y.Z tag']
    version = match.group(1)
    project, init = member_versions(root)
    problems = []
    if project != version:
        problems.append(f'{MEMBER.as_posix()}/pyproject.toml is {project}, not {version}')
    if init != version:
        problems.append(f'pokecore.__version__ is {init}, not {version}')
    notes = changelog_section(root, version)
    if not notes:
        problems.append(f'{MEMBER.as_posix()}/CHANGELOG.md has no "## {version}" section with text')
    return version, notes, problems


def wheel_problems(root, version, wheel):
    """The built wheel must carry this version's name and exactly the member's source files."""
    wheel = Path(wheel)
    expected = f'pokecore-{version}-py3-none-any.whl'
    if wheel.name != expected:
        return [f'built wheel is {wheel.name}, expected {expected}']
    return release_pins.wheel_source_problems(wheel.read_bytes(), 'pokecore', Path(root) / MEMBER, wheel.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tag')
    parser.add_argument('--notes', type=Path, help='write the changelog section for the version here')
    parser.add_argument('--wheel', type=Path, help='a built wheel to compare with the member source')
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args(argv)
    version, notes, problems = check(arguments.root, arguments.tag)
    if version and arguments.wheel:
        problems += wheel_problems(arguments.root, version, arguments.wheel)
    if problems:
        sys.exit(f'{arguments.tag} cannot be released:\n  ' + '\n  '.join(problems))
    if arguments.notes:
        arguments.notes.write_text(notes + '\n', encoding='utf-8')
    print(f'version={version}')


if __name__ == '__main__':
    main()
