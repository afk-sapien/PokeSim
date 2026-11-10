"""Point the pokecore URL pin in pyproject.toml at a published pokecore release.

Run it in the PokeSim release pull request, once the pokecore release workflow has published
pokecore-v<version> from the same `packages/pokecore` source:

    python tools/pin_pokecore.py 0.11.1

It downloads that release's wheel and SHA256SUMS.txt. It refuses when the version is not the workspace
member's, when the wheel's SHA-256 is not the one SHA256SUMS.txt lists, or when the wheel's pokecore files
differ from `packages/pokecore/src/pokecore`. Then it rewrites only the URL and the #sha256 fragment of the
pokecore requirement, keeping its extras and markers, and checks the new pin as `tools/check_release_pins.py`
does. `uv.lock` takes pokecore from the workspace, so it does not change.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_pins  # noqa: E402

ROOT = release_pins.ROOT
RELEASES = 'https://github.com/afk-sapien/PokeSim/releases/download'
# The quoted pokecore requirement up to the end of its #sha256 fragment. Extras and markers sit outside it.
REQUIREMENT = re.compile(r'(?P<head>"pokecore(?:\[[^\]"]*\])?\s*@\s*)https://[^\s"#]+#sha256=[0-9a-f]{64}')


def wheel_url(version):
    return f'{RELEASES}/pokecore-v{version}/pokecore-{version}-py3-none-any.whl'


def listed_sums(text):
    """Return {file name: sha256} from a sha256sum listing."""
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and release_pins.SHA256.fullmatch(parts[0]):
            sums[parts[1].lstrip('*')] = parts[0]
    return sums


def pin(root, version, opener=release_pins.fetch):
    """Rewrite the pin to the released wheel and return the problems. A problem leaves pyproject.toml as it was."""
    root = Path(root)
    members = release_pins.workspace_members(root)
    if 'pokecore' not in members:
        return ['pyproject.toml takes no pokecore from its uv workspace']
    member_version, directory = members['pokecore']
    if version != member_version:
        return [f'packages/pokecore is {member_version}, not {version}, so its source is not that release']
    url = wheel_url(version)
    name = url.rsplit('/', 1)[-1]
    try:
        blob = opener(url)
        sums = listed_sums(opener(url.rsplit('/', 1)[0] + '/SHA256SUMS.txt').decode('utf-8'))
    except OSError as error:
        return [f'could not download the pokecore-v{version} release files: {error}']
    digest = hashlib.sha256(blob).hexdigest()
    if sums.get(name) != digest:
        return [f'{name} is {digest}, but SHA256SUMS.txt lists {sums.get(name)}']
    problems = release_pins.wheel_source_problems(blob, 'pokecore', directory, url)
    if problems:
        return problems
    path = root / 'pyproject.toml'
    before = path.read_text(encoding='utf-8')
    after, count = REQUIREMENT.subn(lambda match: f'{match["head"]}{url}#sha256={digest}', before)
    if count != 1:
        return [f'pyproject.toml has {count} pokecore URL requirements, expected exactly one']
    path.write_text(after, encoding='utf-8')
    problems = [problem for pinned, pinned_url, fragment in release_pins.emulator_pins(release_pins.read_pyproject(root))
                if pinned == 'pokecore'
                for problem in release_pins.member_pin_problems(root, pinned, members['pokecore'], pinned_url, fragment)]
    if problems:
        path.write_text(before, encoding='utf-8')
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('version', help='a published pokecore version, for example 0.11.1')
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args(argv)
    problems = pin(arguments.root, arguments.version)
    if problems:
        sys.exit('pyproject.toml was not changed:\n  ' + '\n  '.join(problems))
    print(f'pyproject.toml pins pokecore {arguments.version} from {wheel_url(arguments.version)}')


if __name__ == '__main__':
    main()
