"""Point the emulator dependencies at the real upstream release assets and drop the temporary copies.

Run this once the pokesim-core and pyboy-rs GitHub releases exist, from a clean checkout of the release
branch, with a manifest naming every final asset. The manifest is JSON:

    {"assets": {"<file name>": {"url": "https://github.com/.../releases/download/.../<file name>",
                                "sha256": "<64 hex digits>"}, ...},
     "pyboy_rs_sdist": "pyboy_rs-0.1.1.tar.gz"}

Asset file names must be exactly the temporary copies' names in tools/temp-wheels (the same wheels), so
each URL is swapped by name. The script then rewrites, consistently:

* pyproject.toml: every temporary URL becomes the final URL plus a #sha256= fragment.
* uv.lock: the same URL swap and the wheel hash fields. A hash change is allowed only if the manifest says so.
* Dockerfile: the source archive URL and EMULATOR_SOURCE_SHA256, and the TEMP marker comment is removed.
* tools/temp-wheels and TEMP_REMOVE_BEFORE_RELEASE.md are deleted.

It refuses to continue when a name is missing from the manifest and, afterwards, runs the same checks as the
release workflow (tools/release_pins.py), so a half-finished rewrite fails loudly. Afterwards run
`uv lock --check` (network needed) and commit.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_pins  # noqa: E402

TEMP_URL = re.compile(r'https://raw\.githubusercontent\.com/[^\s"\'#]*?/temp-wheels/([^\s"\'#]+)')


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


def finalize(root, assets, sdist):
    root = Path(root)
    lock_text = (root / 'uv.lock').read_text(encoding='utf-8')
    # uv.lock carries plain URLs and separate hash fields, so no fragment there.
    lock_text, missing = swap_urls(lock_text, assets, fragment=False)
    pyproject_text, more = swap_urls((root / 'pyproject.toml').read_text(encoding='utf-8'), assets, fragment=True)
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
    dockerfile, count = re.subn(r'^(ARG EMULATOR_SOURCE_URL=)\S*', lambda m: m.group(1) + assets[sdist]['url'], dockerfile, flags=re.M)
    dockerfile, count2 = re.subn(r'^(ARG EMULATOR_SOURCE_SHA256=)\S*', lambda m: m.group(1) + assets[sdist]['sha256'],
                                 dockerfile, flags=re.M)
    if count != 1 or count2 != 1:
        raise SystemExit('Dockerfile must have exactly one EMULATOR_SOURCE_URL and one EMULATOR_SOURCE_SHA256 ARG')
    (root / 'uv.lock').write_text(lock_text, encoding='utf-8')
    (root / 'pyproject.toml').write_text(pyproject_text, encoding='utf-8')
    (root / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
    shutil.rmtree(root / 'tools/temp-wheels', ignore_errors=True)
    (root / 'TEMP_REMOVE_BEFORE_RELEASE.md').unlink(missing_ok=True)
    problems = release_pins.local_problems(root)
    if problems:
        raise SystemExit('Finalizing left problems:\n  ' + '\n  '.join(problems))


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
