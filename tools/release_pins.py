"""Checks that the release pins are final: no temporary wheels, matching hashes, matching Dockerfile checksum.

The 0.5.0 release candidate pointed its two emulator dependencies (pokecore and pyboy-rs) at copies of
their wheels stored in this repository, because the upstream GitHub releases did not exist yet. Those
temporary pins must never reach a public tag.

pokecore is a uv workspace member in packages/pokecore. uv, CI and the container install it from there, and
the pyproject URL pin is the released wheel that pip and pipx users get. So that pin must name the member's
version and carry a #sha256 fragment, and the remote check downloads it and compares its files with the
member's source.

This module is used by the release workflow (validate and gate jobs) and by the unit tests. Run it by hand
with:

    python tools/check_release_pins.py            # local checks only
    python tools/check_release_pins.py --remote   # also download every release asset and compare hashes
"""
import hashlib
import io
import re
import tomllib
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

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
            # A wheel locked from a local path has no URL; pin_problems reports it as missing from the lock.
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
