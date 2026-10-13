"""Point the emulator dependencies at the real upstream release assets and drop the temporary copies.

Run this once the pokesim-core and pyboy-rs GitHub releases exist, from a clean checkout of the release
branch, with a manifest naming every final asset. The manifest is JSON:

    {"assets": {"<file name>": {"url": "https://github.com/.../releases/download/.../<file name>",
                                "sha256": "<64 hex digits>"}, ...},
     "pyboy_rs_sdist": "pyboy_rs-0.1.1.tar.gz"}

Asset file names must be exactly the temporary copies' names in tools/temp-wheels (the same wheels), so
each URL is swapped by name. The script then rewrites, consistently:

* pyproject.toml: every temporary URL (with any #sha256= fragment) becomes the final URL plus a #sha256=
  fragment, and the [tool.uv.sources] entries that read a wheel from tools/temp-wheels are removed.
* uv.lock: the same URL swap, path sources in tools/temp-wheels become URL sources, and the wheel hash fields
  are set. A hash change is allowed only if the manifest says so.
* Dockerfile: the source archive URL and EMULATOR_SOURCE_SHA256, and the TEMP comments and the COPY of
  tools/temp-wheels are removed.
* tools/temp-wheels and TEMP_REMOVE_BEFORE_RELEASE.md are deleted.

It refuses to continue when a name is missing from the manifest and, afterwards, runs the same checks as the
release workflow (tools/release_pins.py). If they fail, every file is put back as it was, so a half-finished
rewrite fails loudly and leaves nothing behind. Afterwards run
`uv lock --check` (network needed) and commit.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_pins  # noqa: E402

TEMP_URL = re.compile(r'https://raw\.githubusercontent\.com/[^\s"\'#]*?/temp-wheels/([^\s"\'#]+)(?:#sha256=[0-9a-f]{64})?')
TEMP_PATH = re.compile(r'\b(path|filename) = "(?:tools/temp-wheels/)?([^"/]+\.whl)"')


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    assets = manifest['assets']
    for name, asset in assets.items():
        if not release_pins.SHA256.fullmatch(asset['sha256']):
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
        for relative in release_pins.TEMP_PATHS:
            if (root / relative).exists():
                target = Path(aside) / str(len(moved))
                (root / relative).rename(target)
                moved.append((relative, target))
        for name, text in rewritten.items():
            (root / name).write_text(text, encoding='utf-8')
        problems = release_pins.local_problems(root)
        if problems:
            for name, text in originals.items():
                (root / name).write_text(text, encoding='utf-8')
            for relative, target in moved:
                target.rename(root / relative)
            raise SystemExit('Finalizing would leave problems, so nothing was changed:\n  ' + '\n  '.join(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--tree', type=Path, default=release_pins.ROOT)
    arguments = parser.parse_args()
    assets, sdist = load_manifest(arguments.manifest)
    finalize(arguments.tree, assets, sdist)
    print('Pins finalized. Next: uv lock --check, then python tools/check_release_pins.py --remote, then commit.')


if __name__ == '__main__':
    main()
