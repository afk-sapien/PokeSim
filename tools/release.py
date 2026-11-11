"""Check and prepare a PokeSim or pokecore release, one command per step.

    python tools/release.py check-pins [--tree DIR] [--remote]
    python tools/release.py finalize-pins MANIFEST [--tree DIR]
    python tools/release.py pin-pokecore VERSION [--root DIR]
    python tools/release.py check-pokecore TAG [--notes FILE] [--wheel FILE] [--root DIR]
    python tools/release.py version VERSION | --check
    python tools/release.py floating-tags VERSION [PUBLISHED ...]
    python tools/release.py check-gates --sha SHA [--repo OWNER/NAME] [--tree DIR] [--timeout S] [--interval S]
    python tools/release.py assemble DIR --version V --revision SHA [--without-desktop] [--image I --index-digest D]
    python tools/release.py check-image IMAGE [--tested IMAGE] [--platform P] [--index PLATFORMS | --unchanged]

Each command keeps the options, output and exit codes of the tool it replaced, and `--help` on a command
says what it checks. Only the standard library loads, so the release workflow runs this with a bare Python.
"""
import argparse
from collections import Counter
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]

# Release pins. The 0.5.0 release candidate pointed its two emulator dependencies (pokecore and pyboy-rs) at
# copies of their wheels stored in this repository, because the upstream GitHub releases did not exist yet.
# Those temporary pins must never reach a public tag.

# Files whose content carries dependency pins or installer URLs. Docs and tests may mention the markers.
PIN_FILES = ['pyproject.toml', 'uv.lock', 'Dockerfile', 'install.sh', 'install.ps1',
             'compose.yaml', 'compose.quickstart.yaml', 'compose.build.yaml']
# Anything matching one of these in a pin file means the temporary wheels are still in use.
TEMP_PATTERNS = [r'refs/heads/', r'temp-wheels', r'TEMP_REMOVE_BEFORE_RELEASE', r'TEMP-\d+\.\d+\.\d+-']
TEMP_PATHS = ['tools/temp-wheels', 'TEMP_REMOVE_BEFORE_RELEASE.md']
EMULATOR_PACKAGES = ('pyboy-rs', 'pokecore')
SHA256 = re.compile(r'[0-9a-f]{64}')


def read_lock(root):
    return tomllib.loads((Path(root) / 'uv.lock').read_text(encoding='utf-8'))


def direct_urls(lock):
    """Return {url: sha256} for every locked package whose source is a direct URL (the emulator wheels)."""
    found = {}
    for package in lock.get('package', []):
        if package['name'] not in EMULATOR_PACKAGES:
            continue
        for wheel in package.get('wheels', []):
            # A wheel locked from a local path has no URL. pin_problems reports it as missing from the lock.
            if 'url' in wheel:
                found[wheel['url']] = wheel['hash'].removeprefix('sha256:')
    return found


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def read_pyproject(root):
    return tomllib.loads((Path(root) / 'pyproject.toml').read_text(encoding='utf-8'))


def emulator_pins(project):
    """Yield (name, url, fragment) for every emulator package that pyproject pins to a URL."""
    for requirement in project.get('project', {}).get('dependencies', []):
        match = re.match(r'\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*@\s*(\S+)', requirement)
        if match and normalize(match.group(1)) in EMULATOR_PACKAGES:
            url, _, fragment = match.group(2).partition('#')
            yield normalize(match.group(1)), url, fragment


def workspace_members(root):
    """Return {name: (version, member directory)} for packages pyproject takes from its uv workspace."""
    root = Path(root)
    uv = read_pyproject(root).get('tool', {}).get('uv', {})
    sourced = {normalize(name) for name, source in uv.get('sources', {}).items()
               if isinstance(source, dict) and source.get('workspace')}
    members = {}
    for pattern in uv.get('workspace', {}).get('members', []):
        for directory in sorted(root.glob(pattern)):
            if not (directory / 'pyproject.toml').is_file():
                continue
            project = tomllib.loads((directory / 'pyproject.toml').read_text(encoding='utf-8')).get('project', {})
            name = normalize(project.get('name', ''))
            if name in sourced:
                members[name] = (project.get('version'), directory)
    return members


def member_pin_problems(root, name, member, url, fragment):
    """A workspace member's URL pin must be its own wheel at the member's version, with a hash fragment."""
    version, directory = member
    relative = directory.relative_to(Path(root)).as_posix()
    problems = []
    wheel = re.fullmatch(rf'{re.escape(name.replace("-", "_"))}-([^-]+)-py3-none-any\.whl', url.rsplit('/', 1)[-1])
    if not url.startswith('https://') or wheel is None:
        problems.append(f'pyproject pin for {name} is not an https URL of a {name} wheel: {url}')
    elif wheel.group(1) != version:
        problems.append(f'pyproject pins {name} {wheel.group(1)} but {relative} is {version}: {url}')
    if not re.fullmatch(r'sha256=[0-9a-f]{64}', fragment):
        problems.append(f'pyproject URL lacks a #sha256 fragment: {url}')
    return problems


def wheel_source_problems(blob, name, directory, url):
    """Compare a released wheel's package files with the member's source tree, file by file."""
    package = name.replace('-', '_')
    source = Path(directory) / 'src' / package
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            released = {info.filename: archive.read(info) for info in archive.infolist()
                        if info.filename.startswith(package + '/') and not info.is_dir()}
    except zipfile.BadZipFile:
        return [f'published asset is not a wheel: {url}']
    current = {f'{package}/{path.relative_to(source).as_posix()}': path.read_bytes() for path in source.rglob('*')
               if path.is_file() and '__pycache__' not in path.parts}
    differ = sorted(path for path in released.keys() | current.keys() if released.get(path) != current.get(path))
    if differ:
        shown = ', '.join(differ[:5]) + (f' and {len(differ) - 5} more' if len(differ) > 5 else '')
        return [f'published {name} wheel differs from the workspace source: {shown}']
    return []


def locked_version(lock, name):
    versions = {package['version'] for package in lock.get('package', []) if package['name'] == name}
    return versions.pop() if len(versions) == 1 else None


def dockerfile_args(text):
    return dict(re.findall(r'^ARG (EMULATOR_SOURCE_[A-Z0-9_]+)=(\S*)', text, re.M))


def temp_problems(root):
    """Every sign that the temporary wheels or their bookkeeping are still present."""
    root = Path(root)
    problems = []
    for relative in TEMP_PATHS:
        if (root / relative).exists():
            problems.append(f'{relative} still exists')
    for name in PIN_FILES:
        path = root / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for pattern in TEMP_PATTERNS:
                if re.search(pattern, line):
                    problems.append(f'{name}:{number} matches {pattern!r}')
                    break
    return problems


def pin_problems(root):
    """Pyproject URLs need #sha256 fragments equal to the locked hashes; the Dockerfile needs a real checksum.

    A workspace member is locked from its directory, not its URL, so its pin is checked against the member's
    version instead of the lock.
    """
    root = Path(root)
    problems = []
    lock = read_lock(root)
    hashes = direct_urls(lock)
    if not hashes:
        problems.append('uv.lock has no direct-URL emulator wheels')
    members = workspace_members(root)
    seen = set()
    for name, url, fragment in emulator_pins(read_pyproject(root)):
        if name in members:
            problems.extend(member_pin_problems(root, name, members[name], url, fragment))
            continue
        seen.add(url)
        expected = hashes.get(url)
        if expected is None:
            problems.append(f'pyproject URL is not in uv.lock: {url}')
        elif fragment != 'sha256=' + expected:
            problems.append(f'pyproject URL lacks a matching #sha256 fragment: {url}')
    for url in hashes:
        # pip and uv install exactly the URLs pyproject names, so every locked wheel must be named there.
        if url not in seen:
            problems.append(f'locked wheel is not required by pyproject: {url}')
    problems.extend(dockerfile_problems(root, lock))
    return problems


def dockerfile_problems(root, lock=None):
    root = Path(root)
    lock = lock or read_lock(root)
    args = dockerfile_args((root / 'Dockerfile').read_text(encoding='utf-8'))
    problems = []
    checksum = args.get('EMULATOR_SOURCE_SHA256', '')
    if not SHA256.fullmatch(checksum):
        problems.append('Dockerfile EMULATOR_SOURCE_SHA256 is empty or not a SHA-256 hex digest')
    url = args.get('EMULATOR_SOURCE_URL', '')
    version = locked_version(lock, 'pyboy-rs')
    name = url.rsplit('/', 1)[-1]
    if not url:
        problems.append('Dockerfile EMULATOR_SOURCE_URL is empty')
    elif version is None:
        problems.append('uv.lock does not pin exactly one pyboy-rs version')
    elif not re.fullmatch(rf'pyboy[_-]rs-{re.escape(version)}\.tar\.gz', name):
        problems.append(f'Dockerfile source archive {name} does not match the locked pyboy-rs {version}')
    return problems


def local_problems(root=ROOT):
    return temp_problems(root) + pin_problems(root)


def fetch(url):
    with urlopen(url.partition('#')[0], timeout=120) as response:
        return response.read()


def remote_problems(root=ROOT, opener=fetch):
    """Download every locked emulator wheel and the Dockerfile source archive and compare their SHA-256.

    A workspace member's pinned wheel is compared with its #sha256 fragment and with the member's source.
    """
    root = Path(root)
    problems = []
    for url, expected in direct_urls(read_lock(root)).items():
        try:
            actual = hashlib.sha256(opener(url)).hexdigest()
        except OSError as error:
            problems.append(f'could not download {url}: {error}')
            continue
        if actual != expected:
            problems.append(f'published asset differs from uv.lock: {url} is {actual}, locked {expected}')
    members = workspace_members(root)
    for name, url, fragment in emulator_pins(read_pyproject(root)):
        if name not in members:
            continue
        try:
            blob = opener(url)
        except OSError as error:
            problems.append(f'could not download {url}: {error}')
            continue
        actual = hashlib.sha256(blob).hexdigest()
        if fragment != 'sha256=' + actual:
            problems.append(f'published asset differs from the pyproject fragment: {url} is {actual}')
        problems.extend(wheel_source_problems(blob, name, members[name][1], url))
    args = dockerfile_args((root / 'Dockerfile').read_text(encoding='utf-8'))
    url = args.get('EMULATOR_SOURCE_URL', '')
    if url:
        try:
            actual = hashlib.sha256(opener(url)).hexdigest()
        except OSError as error:
            problems.append(f'could not download {url}: {error}')
        else:
            if actual != args.get('EMULATOR_SOURCE_SHA256'):
                problems.append(f'published source archive differs from the Dockerfile checksum: {url} is {actual}')
    return problems


def check_release_pins(arguments):
    """Fail unless the release pins are final: no temporary wheels, matching hashes, matching Dockerfile checksum.

    pokecore is a uv workspace member in packages/pokecore. uv, CI and the container install it from there, and
    the pyproject URL pin is the released wheel that pip and pipx users get. So that pin must name the member's
    version and carry a #sha256 fragment, and the remote check downloads it and compares its files with the
    member's source.

    The release workflow runs this in its validate job, and the gate runs the local checks. Run it by hand
    with:

        python tools/release.py check-pins            # local checks only
        python tools/release.py check-pins --remote   # also download every release asset and compare hashes
    """
    # A release must not ship a Compose file or installer that still names the previous version.
    problems = local_problems(arguments.tree) + version_problems(arguments.tree)
    if arguments.remote and not problems:
        problems = remote_problems(arguments.tree)
    if problems:
        print('Release pins are not final:', file=sys.stderr)
        for problem in problems:
            print('  ' + problem, file=sys.stderr)
        sys.exit(1)
    print('Release pins are final' + (' and match the published assets' if arguments.remote else ''))


# Finalizing the temporary pins.
TEMP_URL = re.compile(r'https://raw\.githubusercontent\.com/[^\s"\'#]*?/temp-wheels/([^\s"\'#]+)(?:#sha256=[0-9a-f]{64})?')
TEMP_PATH = re.compile(r'\b(path|filename) = "(?:tools/temp-wheels/)?([^"/]+\.whl)"')


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    assets = manifest['assets']
    for name, asset in assets.items():
        if not SHA256.fullmatch(asset['sha256']):
            raise SystemExit(f'{name}: sha256 must be 64 lowercase hex digits')
        if not asset['url'].startswith('https://') or '#' in asset['url'] or 'refs/heads/' in asset['url']:
            raise SystemExit(f'{name}: url must be an https release asset URL without a fragment or branch ref')
        if not asset['url'].endswith('/' + name):
            raise SystemExit(f'{name}: url must end with the asset name')
    sdist = manifest['pyboy_rs_sdist']
    if sdist not in assets:
        raise SystemExit(f'{sdist}: the source archive must be listed in assets')
    return assets, sdist


def swap_urls(text, assets, fragment):
    missing = set()

    def replace(match):
        name = match.group(1)
        if name not in assets:
            missing.add(name)
            return match.group(0)
        return assets[name]['url'] + (('#sha256=' + assets[name]['sha256']) if fragment else '')

    return TEMP_URL.sub(replace, text), missing


def swap_lock_paths(text, assets):
    """Turn uv.lock path sources in tools/temp-wheels into URL sources of the final assets."""
    missing = set()

    def replace(match):
        if match.group(1) == 'path' and 'temp-wheels/' not in match.group(0):
            return match.group(0)
        name = match.group(2)
        if name not in assets:
            missing.add(name)
            return match.group(0)
        return f'url = "{assets[name]["url"]}"'

    return TEMP_PATH.sub(replace, text), missing


def drop_temp_sources(text):
    """Remove [tool.uv.sources] entries that read tools/temp-wheels, and the table and its TEMP comment once empty."""
    text = re.sub(r'^[^\n]*= \{[^\n]*\bpath = "tools/temp-wheels/[^\n]*\n', '', text, flags=re.M)
    return re.sub(r'^(?:# TEMP:[^\n]*\n)*\[tool\.uv\.sources\]\n(?:\n|(?=\[)|\Z)', '', text, flags=re.M)


def finalize(root, assets, sdist):
    root = Path(root)
    lock_text = (root / 'uv.lock').read_text(encoding='utf-8')
    # uv.lock carries plain URLs and separate hash fields, so no fragment there.
    lock_text, missing = swap_urls(lock_text, assets, fragment=False)
    lock_text, more = swap_lock_paths(lock_text, assets)
    missing |= more
    pyproject_text, more = swap_urls((root / 'pyproject.toml').read_text(encoding='utf-8'), assets, fragment=True)
    pyproject_text = drop_temp_sources(pyproject_text)
    missing |= more
    if missing:
        raise SystemExit('The manifest lacks: ' + ', '.join(sorted(missing)))
    # Hash fields follow their URL in uv.lock, so replace the hash after each final wheel URL.
    for name, asset in assets.items():
        if name == sdist:
            continue
        pattern = re.compile(r'(\{ url = "' + re.escape(asset['url']) + r'", hash = "sha256:)[0-9a-f]{64}(")')
        lock_text, count = pattern.subn(lambda m: m.group(1) + asset['sha256'] + m.group(2), lock_text)
        if count == 0:
            raise SystemExit(f'{name}: no wheel entry in uv.lock')
    dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
    dockerfile = re.sub(r'^# TEMP-[^\n]*\n', '', dockerfile, flags=re.M)
    dockerfile = re.sub(r'^(?:# TEMP:[^\n]*\n)*COPY tools/temp-wheels [^\n]*\n', '', dockerfile, flags=re.M)
    dockerfile, count = re.subn(r'^(ARG EMULATOR_SOURCE_URL=)\S*', lambda m: m.group(1) + assets[sdist]['url'], dockerfile, flags=re.M)
    dockerfile, count2 = re.subn(r'^(ARG EMULATOR_SOURCE_SHA256=)\S*', lambda m: m.group(1) + assets[sdist]['sha256'],
                                 dockerfile, flags=re.M)
    if count != 1 or count2 != 1:
        raise SystemExit('Dockerfile must have exactly one EMULATOR_SOURCE_URL and one EMULATOR_SOURCE_SHA256 ARG')
    rewritten = {'uv.lock': lock_text, 'pyproject.toml': pyproject_text, 'Dockerfile': dockerfile}
    originals = {name: (root / name).read_text(encoding='utf-8') for name in rewritten}
    # Move the temporary copies aside instead of deleting them, so a failed check can put everything back.
    with tempfile.TemporaryDirectory(dir=root) as aside:
        moved = []
        for relative in TEMP_PATHS:
            if (root / relative).exists():
                target = Path(aside) / str(len(moved))
                (root / relative).rename(target)
                moved.append((relative, target))
        for name, text in rewritten.items():
            (root / name).write_text(text, encoding='utf-8')
        problems = local_problems(root)
        if problems:
            for name, text in originals.items():
                (root / name).write_text(text, encoding='utf-8')
            for relative, target in moved:
                target.rename(root / relative)
            raise SystemExit('Finalizing would leave problems, so nothing was changed:\n  ' + '\n  '.join(problems))


def finalize_release_pins(arguments):
    """Point the emulator dependencies at the real upstream release assets and drop the temporary copies.

    Run this once the pokesim-core and pyboy-rs GitHub releases exist, from a clean checkout of the release
    branch, with a manifest naming every final asset. The manifest is JSON:

        {"assets": {"<file name>": {"url": "https://github.com/.../releases/download/.../<file name>",
                                    "sha256": "<64 hex digits>"}, ...},
         "pyboy_rs_sdist": "pyboy_rs-0.1.1.tar.gz"}

    Asset file names must be exactly the temporary copies' names in tools/temp-wheels (the same wheels), so
    each URL is swapped by name. The command then rewrites, consistently:

    * pyproject.toml: every temporary URL (with any #sha256= fragment) becomes the final URL plus a #sha256=
      fragment, and the [tool.uv.sources] entries that read a wheel from tools/temp-wheels are removed.
    * uv.lock: the same URL swap, path sources in tools/temp-wheels become URL sources, and the wheel hash fields
      are set. A hash change is allowed only if the manifest says so.
    * Dockerfile: the source archive URL and EMULATOR_SOURCE_SHA256, and the TEMP comments and the COPY of
      tools/temp-wheels are removed.
    * tools/temp-wheels and TEMP_REMOVE_BEFORE_RELEASE.md are deleted.

    It refuses to continue when a name is missing from the manifest and, afterwards, runs the local checks of
    check-pins. If they fail, every file is put back as it was, so a half-finished rewrite fails loudly and
    leaves nothing behind. Afterwards run `uv lock --check` (network needed) and commit.
    """
    assets, sdist = load_manifest(arguments.manifest)
    finalize(arguments.tree, assets, sdist)
    print('Pins finalized. Next: uv lock --check, then python tools/release.py check-pins --remote, then commit.')


# The pokecore pin and the pokecore release.
RELEASES = 'https://github.com/afk-sapien/PokeSim/releases/download'
# The quoted pokecore requirement up to the end of its #sha256 fragment. Extras and markers sit outside it.
REQUIREMENT = re.compile(r'(?P<head>"pokecore(?:\[[^\]"]*\])?\s*@\s*)https://[^\s"#]+#sha256=[0-9a-f]{64}')
MEMBER = Path('packages/pokecore')
TAG = re.compile(r'pokecore-v(\d+\.\d+\.\d+(?:rc\d+)?)')


def wheel_url(version):
    return f'{RELEASES}/pokecore-v{version}/pokecore-{version}-py3-none-any.whl'


def listed_sums(text):
    """Return {file name: sha256} from a sha256sum listing."""
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and SHA256.fullmatch(parts[0]):
            sums[parts[1].lstrip('*')] = parts[0]
    return sums


def pin(root, version, opener=fetch):
    """Rewrite the pin to the released wheel and return the problems. A problem leaves pyproject.toml as it was."""
    root = Path(root)
    members = workspace_members(root)
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
    problems = wheel_source_problems(blob, 'pokecore', directory, url)
    if problems:
        return problems
    path = root / 'pyproject.toml'
    before = path.read_text(encoding='utf-8')
    after, count = REQUIREMENT.subn(lambda match: f'{match["head"]}{url}#sha256={digest}', before)
    if count != 1:
        return [f'pyproject.toml has {count} pokecore URL requirements, expected exactly one']
    path.write_text(after, encoding='utf-8')
    problems = [problem for pinned, pinned_url, fragment in emulator_pins(read_pyproject(root))
                if pinned == 'pokecore'
                for problem in member_pin_problems(root, pinned, members['pokecore'], pinned_url, fragment)]
    if problems:
        path.write_text(before, encoding='utf-8')
    return problems


def pin_pokecore(arguments):
    """Point the pokecore URL pin in pyproject.toml at a published pokecore release.

    Run it in the PokeSim release pull request, once the pokecore release workflow has published
    pokecore-v<version> from the same `packages/pokecore` source:

        python tools/release.py pin-pokecore 0.11.1

    It downloads that release's wheel and SHA256SUMS.txt. It refuses when the version is not the workspace
    member's, when the wheel's SHA-256 is not the one SHA256SUMS.txt lists, or when the wheel's pokecore files
    differ from `packages/pokecore/src/pokecore`. Then it rewrites only the URL and the #sha256 fragment of the
    pokecore requirement, keeping its extras and markers, and checks the new pin as check-pins does.
    `uv.lock` takes pokecore from the workspace, so it does not change.
    """
    problems = pin(arguments.root, arguments.version)
    if problems:
        sys.exit('pyproject.toml was not changed:\n  ' + '\n  '.join(problems))
    print(f'pyproject.toml pins pokecore {arguments.version} from {wheel_url(arguments.version)}')


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


def check_pokecore(root, tag):
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
    return wheel_source_problems(wheel.read_bytes(), 'pokecore', Path(root) / MEMBER, wheel.name)


def pokecore_release(arguments):
    """Check a pokecore release tag against the workspace member, and its built wheel against the source.

    The pokecore release workflow runs this on the tagged commit:

        python tools/release.py check-pokecore pokecore-v0.11.1 --notes notes.md
        python tools/release.py check-pokecore pokecore-v0.11.1 --wheel dist/pokecore-0.11.1-py3-none-any.whl

    It fails unless the tag is pokecore-v<version>, `packages/pokecore/pyproject.toml` and `pokecore.__version__`
    both name that version, and `packages/pokecore/CHANGELOG.md` has a `## <version>` section with text. It
    prints `version=<version>` for the workflow's outputs and writes that section to the notes file. With
    `--wheel` it also fails when the wheel's pokecore files differ from `packages/pokecore/src/pokecore`, the
    same comparison `check-pins --remote` makes against the published wheel later.
    """
    version, notes, problems = check_pokecore(arguments.root, arguments.tag)
    if version and arguments.wheel:
        problems += wheel_problems(arguments.root, version, arguments.wheel)
    if problems:
        sys.exit(f'{arguments.tag} cannot be released:\n  ' + '\n  '.join(problems))
    if arguments.notes:
        arguments.notes.write_text(notes + '\n', encoding='utf-8')
    print(f'version={version}')


# The PokeSim version pins.
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


def release_version(arguments):
    """Keep every pinned PokeSim version equal to the package version, and move them all at once.

    The release Compose files, installers and docs name the exact release they install. A release that bumps
    pyproject.toml but misses one of them ships a quickstart that installs the previous version, so the release
    pin checks fail while any pin differs from the package version. Prepare a release with:

        python tools/release.py version 0.6.2       # rewrite every pin to 0.6.2
        python tools/release.py version --check     # list pins that differ from pyproject.toml

    After a release is published, main moves to the next development version, such as 0.7.0.dev0. A
    development version moves only the package pins. The install pins keep naming the published release,
    since no image or download exists for a development version.
    """
    if arguments.check == bool(arguments.version):
        arguments.parser.error('give either a version or --check')
    if arguments.version:
        bump(ROOT, arguments.version)
    problems = version_problems(ROOT)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        sys.exit(1)
    print(f'Every pin names {package_version(ROOT)}')


# Floating image tags.
STABLE = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')


def stable(tag):
    match = STABLE.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def floating(version, published):
    current = stable(version)
    if current is None:
        return []
    releases = [release for release in map(stable, published) if release] + [current]
    tags = []
    if current >= max(releases):
        tags.append('latest')
    if current >= max(release for release in releases if release[:2] == current[:2]):
        tags.append(f'{current[0]}.{current[1]}')
    return tags


def floating_tags(arguments):
    """Name the floating image tags a published release should move.

    `latest` follows the newest stable release, and `<major>.<minor>` follows the newest stable
    release of that line, so a fix to an older line never moves `latest` back. Release
    candidates move nothing.
    """
    print('\n'.join(floating(arguments.version, arguments.published)))


# Release gates.
# Exact job names that must be present and successful, as GitHub reports them (a matrix job's name carries its
# parameters in parentheses). Matching is exact on purpose: a prefix would let 'install (macos-15' be satisfied
# by the 'macos-15-intel' job and 'container' by a job such as 'container-extra'. tests/test_release_gates.py derives the
# expected names from the workflow files, so adding, renaming or removing a job there fails until this list agrees.
REQUIRED = {
    'ci.yml': [
        'dependency-audit', 'lint', 'tests (3.11)', 'tests (3.12)', 'tests (3.14)',
        'pokecore (3.11)', 'pokecore (3.12)', 'pokecore (3.14)', 'pokecore-native',
        'browser (1/4)', 'browser (2/4)', 'browser (3/4)', 'browser (4/4)',
        'container (amd64)', 'container (arm64)', 'ci gate',
    ],
    'python-install.yml': [
        'native tests (ubuntu-22.04, 1/1)', 'native tests (ubuntu-24.04-arm, 1/1)',
        'native tests (macos-15, 1/1)', 'native tests (macos-15-intel, 1/1)',
        'native tests (windows-latest, 1/4)', 'native tests (windows-latest, 2/4)',
        'native tests (windows-latest, 3/4)', 'native tests (windows-latest, 4/4)',
        'install (ubuntu-22.04)', 'install (ubuntu-24.04-arm)', 'install (windows-latest)',
        'install (macos-15-intel)', 'install (macos-15)', 'acceleration', 'install gate',
    ],
}
# A step that must have succeeded somewhere in the run, so a gate cannot be satisfied by renaming it away.
REQUIRED_STEPS = {
    'ci.yml': ['Exercise real browser flows', 'Reject fixable high and critical image vulnerabilities'],
    'python-install.yml': ['Test native service and Python launcher', 'Verify the user-facing installer and repeat installation'],
}


def api(path, token):
    request = Request('https://api.github.com/' + path, headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def jobs_of(repo, run_id, token):
    jobs, page = [], 1
    while True:
        batch = api(f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}', token)['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def judge(workflow, jobs):
    """Return (state, reason) for one run's jobs: state is ok, wait or fail."""
    if not jobs:
        return 'wait', 'no jobs reported yet'
    if any(job['status'] != 'completed' for job in jobs):
        return 'wait', 'jobs still running'
    bad = [f"{job['name']}={job['conclusion']}" for job in jobs if job['conclusion'] != 'success']
    if bad:
        return 'fail', 'not successful: ' + ', '.join(bad)
    names = [job['name'] for job in jobs]
    for required in REQUIRED[workflow]:
        if required not in names:
            return 'fail', f'required job missing: {required}'
    for step in REQUIRED_STEPS[workflow]:
        ok = any(item['name'] == step and item['conclusion'] == 'success' for job in jobs for item in job.get('steps', []))
        if not ok:
            return 'fail', f'required step did not succeed: {step}'
    return 'ok', f'{len(jobs)} jobs succeeded'


def workflow_state(repo, sha, workflow, token):
    path = f'.github/workflows/{workflow}'
    runs = api(f'repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&per_page=100', token)['workflow_runs']
    runs = [run for run in runs if run['head_sha'] == sha and run['path'] == path
            and run['head_repository']['full_name'] == repo]
    if not runs:
        return 'wait', f'no push run of {workflow} for {sha[:12]} yet', None
    results = []
    for run in sorted(runs, key=lambda item: item['id'], reverse=True):
        state, reason = judge(workflow, jobs_of(repo, run['id'], token))
        results.append((state, f"run {run['id']} ({run['head_branch']}): {reason}", run['html_url']))
        if state == 'ok':
            return 'ok', results[-1][1], run['html_url']
    for state, reason, url in results:
        if state == 'wait':
            return state, reason, url
    return 'fail', '; '.join(reason for _, reason, _ in results), results[0][2]


def check_release_gates(arguments):
    """Require that the CI and Python install workflows already passed for one exact commit.

    The publish workflow uses this instead of repeating the whole verification matrix. A run counts only
    when it is a push run of this repository's workflow file for the exact commit, every job in it
    succeeded (a skipped or cancelled job is not a pass), and every required job is present.
    Runs that are still in progress are awaited. A failed run or a missing run fails the gate.
    """
    token = os.environ['GH_TOKEN']
    deadline = time.monotonic() + arguments.timeout
    if arguments.tree:
        problems = local_problems(arguments.tree)
        if problems:
            sys.exit('Release pins are not final, so this commit cannot be published:\n  ' + '\n  '.join(problems))
        print('Release pins are final', flush=True)
    pending = set(REQUIRED)
    while True:
        for workflow in sorted(pending):
            try:
                state, reason, url = workflow_state(arguments.repo, arguments.sha, workflow, token)
            except HTTPError as error:
                state, reason, url = 'wait', f'GitHub API returned {error.code}', None
            print(f'{workflow}: {state}: {reason} {url or ""}', flush=True)
            if state == 'fail':
                sys.exit(f'Gate failed for {workflow} at {arguments.sha}. Fix and rerun CI before publishing.')
            if state == 'ok':
                pending.discard(workflow)
        if not pending:
            print(f'All required checks passed for {arguments.sha}')
            return
        if time.monotonic() > deadline:
            sys.exit('Timed out waiting for required checks: ' + ', '.join(sorted(pending)))
        time.sleep(arguments.interval)


# Release assembly.
DESKTOP_ARCHIVES = (
    'PokeSim-windows-amd64.zip',
    'PokeSim-darwin-arm64.zip',
    'PokeSim-darwin-x86_64.zip',
    'PokeSim-linux-x86_64.tar.gz',
    'PokeSim-linux-aarch64.tar.gz',
)
# Each architecture is built and tested natively, then published under one multi-platform tag.
IMAGE_ARCHITECTURES = ('amd64', 'arm64')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_identity(identity, version, revision):
    if (identity.get('version') != version or identity.get('revision') != revision
            or identity.get('dirty') is not False):
        raise ValueError('Every package must come from the same clean tagged revision')


def assemble(root, version, revision, *, include_desktop=True, image=None, index_digest=None):
    archives = DESKTOP_ARCHIVES if include_desktop else ()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:rc\d+)?', version):
        raise ValueError('Invalid release version')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid source revision')
    wheel = f'pokesim-{version}-py3-none-any.whl'
    source = f'pokesim-{version}.tar.gz'
    required = {wheel, source, 'python-dependencies.json', 'compose.yaml', 'compose.quickstart.yaml',
                'install.sh', 'install.ps1', 'env.example'}
    for architecture in IMAGE_ARCHITECTURES:
        required.update({f'image-linux-{architecture}.tar.gz', f'image-metadata-linux-{architecture}.json'})
    for name in archives:
        required.update({name, name + '.sha256', name + '.json'})
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise ValueError(f'Missing release assets: {missing}')
    allowed = required | {'manifest.json', 'SHA256SUMS'}
    if include_desktop:
        allowed.add('desktop-manifest.json')
    unexpected = sorted(path.name for path in root.iterdir() if path.name not in allowed or not path.is_file())
    if unexpected:
        raise ValueError(f'Unexpected release assets: {unexpected}')

    with zipfile.ZipFile(root / wheel) as archive:
        check_identity(json.loads(archive.read('pokesim/_build.json')), version, revision)
    with tarfile.open(root / source) as archive:
        check_identity(json.load(archive.extractfile(f'pokesim-{version}/pokesim/_build.json')),
                       version, revision)

    if image is not None:
        if not re.fullmatch(r'ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*:' + re.escape(version), image):
            raise ValueError('Registry image must use GHCR and the exact release version')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', index_digest or ''):
            raise ValueError('Registry image must record the digest of its multi-platform index')
    platforms = {}
    for architecture in IMAGE_ARCHITECTURES:
        metadata = json.loads((root / f'image-metadata-linux-{architecture}.json').read_text(encoding='utf-8'))
        labels = metadata['Config']['Labels']
        if (metadata['Os'] != 'linux' or metadata['Architecture'] != architecture
                or labels['org.opencontainers.image.version'] != version
                or labels['org.opencontainers.image.revision'] != revision):
            raise ValueError('Container identity or platform does not match the release')
        platform = {'image_id': metadata['Id']}
        if image is not None:
            # The publish job pushes each tested image under its own architecture tag before the
            # multi-platform tag is made from them.
            if f'{image}-linux-{architecture}' not in metadata.get('RepoTags', []):
                raise ValueError('Registry image tag is absent from the tested image')
            repository = image.rsplit(':', 1)[0]
            matches = [value for value in metadata.get('RepoDigests', [])
                       if re.fullmatch(re.escape(repository) + r'@sha256:[0-9a-f]{64}', value)]
            if len(matches) != 1:
                raise ValueError('Registry image must have exactly one verified repository digest')
            platform['image_digest'] = matches[0]
        platforms[f'linux/{architecture}'] = platform

    desktop = {}
    for name in archives:
        identity = json.loads((root / (name + '.json')).read_text(encoding='utf-8'))
        check_identity(identity, version, revision)
        checksum = digest(root / name)
        if identity.get('archive') != name or identity.get('sha256') != checksum:
            raise ValueError(f'Desktop archive does not match its build receipt: {name}')
        if (root / (name + '.sha256')).read_text(encoding='utf-8').strip() != f'{checksum}  {name}':
            raise ValueError(f'Desktop checksum mismatch: {name}')
        desktop[name] = identity

    registry_digest = image.rsplit(':', 1)[0] + '@' + index_digest if image else None
    image = image or f'pokesim:{version}'
    settings = root / 'env.example'
    contents = settings.read_text(encoding='utf-8')
    if len(re.findall(r'^POKESIM_IMAGE=.*$', contents, flags=re.M)) != 1:
        raise ValueError('Release settings must select exactly one image')
    settings.write_text(re.sub(r'^POKESIM_IMAGE=.*$', f'POKESIM_IMAGE={image}',
                              contents, flags=re.M), encoding='utf-8')
    image_default = r'\$\{POKESIM_IMAGE:-[^}\s]+\}'
    for name in ('compose.yaml', 'compose.quickstart.yaml'):
        compose = root / name
        contents = compose.read_text(encoding='utf-8')
        if len(re.findall(image_default, contents)) not in (1, 2):
            raise ValueError('Release Compose must select the versioned application image')
        compose.write_text(re.sub(image_default, '${POKESIM_IMAGE:-' + image + '}', contents),
                          encoding='utf-8')
    for name, pattern, replacement in (
        ('install.sh', r'^    version=[^\n]+$', '    version=' + version),
        ('install.ps1', r"^\$version = '[^']+'$", "$version = '" + version + "'"),
    ):
        installer = root / name
        contents, count = re.subn(pattern, lambda match: replacement, installer.read_text(encoding='utf-8'), flags=re.M)
        if count != 1:
            raise ValueError(f'{name} must select exactly one release version')
        installer.write_text(contents, encoding='utf-8')
    if include_desktop:
        (root / 'desktop-manifest.json').write_text(json.dumps({
            'version': version, 'revision': revision, 'archives': desktop,
        }, indent=2) + '\n', encoding='utf-8')
    files = {path.name: digest(path) for path in sorted(root.iterdir())
             if path.name not in {'manifest.json', 'SHA256SUMS'}}
    (root / 'manifest.json').write_text(json.dumps({
        'version': version, 'revision': revision, 'image': image,
        **({'image_digest': registry_digest} if registry_digest else {}),
        'platforms': platforms, 'files': files,
    }, indent=2) + '\n', encoding='utf-8')
    files['manifest.json'] = digest(root / 'manifest.json')
    (root / 'SHA256SUMS').write_text(''.join(f'{checksum}  {name}\n'
                                          for name, checksum in sorted(files.items())), encoding='utf-8')


def assemble_release(arguments):
    """Validate a complete release from one source revision and write its manifests."""
    assemble(arguments.directory, arguments.version, arguments.revision,
             include_desktop=not arguments.without_desktop, image=arguments.image,
             index_digest=arguments.index_digest)
    print('Release assets verified and manifests written')


# The registry image.
def local_identity(image):
    """The platform, creation time, layers and labels of a local image.

    The image ID cannot identify an image across machines. It is the config digest under the classic image
    store and the digest of the pulled tag under the containerd store. These fields are the same under both.
    """
    data = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{json .}}', image]))
    return {'platform': f"{data['Os']}/{data['Architecture']}", 'created': data['Created'],
            'layers': data['RootFS']['Layers'], 'labels': data['Config'].get('Labels') or {}}


def registry_identities(image, env=None):
    """The same identity for each runnable platform the registry serves under `image`."""
    try:
        raw = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', '--format', '{{json .Image}}',
                                       image], env=env, stderr=subprocess.PIPE, timeout=300)
    except subprocess.CalledProcessError as error:
        raise LookupError((error.stderr or b'').decode(errors='replace').strip()) from error
    data = json.loads(raw)
    # A single image gives its config. A multi-platform index gives a config per platform.
    configs = [data] if 'rootfs' in data else [value for value in data.values()
                                               if isinstance(value, dict) and 'rootfs' in value]
    return {f"{config['os']}/{config['architecture']}": {
        'platform': f"{config['os']}/{config['architecture']}", 'created': config['created'],
        'layers': config['rootfs']['diff_ids'], 'labels': config.get('config', {}).get('Labels') or {}}
        for config in configs}


def check_pull(image, tested=None, platform=None):
    """Pull `image` anonymously for `platform` and compare it with the local `tested` image."""
    expected = local_identity(tested or image)
    with tempfile.TemporaryDirectory(prefix='pokesim-anonymous-') as config:
        try:
            subprocess.run(['docker', '--config', config, 'pull',
                            *(['--platform', platform] if platform else []), image],
                           check=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                'Anonymous image pull failed. For the first publication, open the '
                'pokesim package settings on GitHub, change its visibility to Public, '
                'then rerun the release workflow. Also check GHCR availability. '
                'The GitHub release has not been published.') from error
        served = registry_identities(image, env={**os.environ, 'DOCKER_CONFIG': config})
    if served.get(platform or expected['platform']) != expected:
        raise ValueError('The registry image differs from the tested local image')
    print('Anonymous pull matches the tested image', platform or '')


def check_unchanged(image, tested=None, platform=None):
    """Refuse to push over a registry tag that already serves a different image. A missing tag passes."""
    expected = local_identity(tested or image)
    try:
        served = registry_identities(image)
    except LookupError as error:
        if 'not found' not in str(error).lower():
            raise
        print(image, 'is not in the registry yet')
        return
    if served.get(platform or expected['platform']) != expected:
        raise ValueError(f'{image} already serves a different image. Publish a new version instead.')
    print(image, 'already serves the tested image', platform or '')


def check_index(image, platforms):
    """Return the digest of the anonymous multi-platform index after checking its platforms."""
    with tempfile.TemporaryDirectory(prefix='pokesim-anonymous-') as config:
        raw = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', '--raw', image],
                                      env={**os.environ, 'DOCKER_CONFIG': config}, timeout=300)
    index = json.loads(raw)
    # Build attestations appear as unknown/unknown entries and are not runnable platforms.
    found = sorted(f"{entry['platform']['os']}/{entry['platform']['architecture']}"
                   for entry in index.get('manifests', [])
                   if entry.get('platform', {}).get('os', 'unknown') != 'unknown')
    if found != sorted(platforms):
        raise ValueError(f'The registry image serves {found or "no platform list"}, not {sorted(platforms)}')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def check_registry_image(arguments):
    """Require an anonymous pull of the exact image tested before publication."""
    if arguments.index:
        print(check_index(arguments.image, arguments.index.split(',')))
    elif arguments.unchanged:
        check_unchanged(arguments.image, arguments.tested, arguments.platform)
    else:
        check_pull(arguments.image, arguments.tested, arguments.platform)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    def command(name, run, raw=False):
        """A subcommand whose help line and description come from its function's docstring."""
        sub = commands.add_parser(name, help=run.__doc__.splitlines()[0], description=inspect.cleandoc(run.__doc__),
                                  formatter_class=argparse.RawDescriptionHelpFormatter if raw else argparse.HelpFormatter)
        sub.set_defaults(run=run, parser=sub)
        return sub

    sub = command('check-pins', check_release_pins, raw=True)
    sub.add_argument('--tree', type=Path, default=ROOT, help='checkout to inspect')
    sub.add_argument('--remote', action='store_true',
                     help='download every locked emulator asset and compare it with uv.lock and the Dockerfile')

    sub = command('finalize-pins', finalize_release_pins, raw=True)
    sub.add_argument('manifest', type=Path)
    sub.add_argument('--tree', type=Path, default=ROOT)

    sub = command('pin-pokecore', pin_pokecore, raw=True)
    sub.add_argument('version', help='a published pokecore version, for example 0.11.1')
    sub.add_argument('--root', type=Path, default=ROOT)

    sub = command('check-pokecore', pokecore_release, raw=True)
    sub.add_argument('tag')
    sub.add_argument('--notes', type=Path, help='write the changelog section for the version here')
    sub.add_argument('--wheel', type=Path, help='a built wheel to compare with the member source')
    sub.add_argument('--root', type=Path, default=ROOT)

    sub = command('version', release_version, raw=True)
    sub.add_argument('version', nargs='?', help='new release version')
    sub.add_argument('--check', action='store_true', help='only report pins that differ from pyproject.toml')

    sub = command('floating-tags', floating_tags)
    sub.add_argument('version')
    sub.add_argument('published', nargs='*', help='tags of the published releases')

    sub = command('check-gates', check_release_gates)
    sub.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    sub.add_argument('--sha', required=True)
    sub.add_argument('--timeout', type=int, default=1800, help='seconds to wait for runs that are still going')
    sub.add_argument('--tree', type=Path, help='checkout of the release revision whose pins must be final')
    sub.add_argument('--interval', type=int, default=20)

    sub = command('assemble', assemble_release)
    sub.add_argument('directory', type=Path)
    sub.add_argument('--version', required=True)
    sub.add_argument('--revision', required=True)
    sub.add_argument('--without-desktop', action='store_true', help='Assemble the Python and Docker release')
    sub.add_argument('--image', help='Verified GHCR image tagged with the release version')
    sub.add_argument('--index-digest', help='Digest of the multi-platform index behind --image')

    sub = command('check-image', check_registry_image)
    sub.add_argument('image')
    sub.add_argument('--tested', help='local image the pull must match (default: the image itself)')
    sub.add_argument('--platform', help='platform to pull from a multi-platform image')
    sub.add_argument('--index', metavar='PLATFORMS',
                     help='comma-separated platforms the index must serve. Prints the index digest.')
    sub.add_argument('--unchanged', action='store_true',
                     help='before a push: fail if the registry tag exists and serves a different image')

    arguments = parser.parse_args(argv)
    arguments.run(arguments)


if __name__ == '__main__':
    main()
