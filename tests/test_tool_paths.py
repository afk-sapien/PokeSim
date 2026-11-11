"""Every ``tools/`` path that CI, the container, the deploy units, the docs or the code names exists.

Moving or deleting a tool must update each place that runs or documents it. History stays as it was
written, so the changelog, ``docs/history`` and the records in ``docs/validation`` are not read. This
file is not read either, because RECORDS would name itself. A few notes name a tool that is gone on
purpose, and RECORDS lists each one with where it went.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# The pokecore jobs run their steps in packages/pokecore, so a tools/ path there is that package's.
BASES = (ROOT, ROOT / 'packages' / 'pokecore')
PATH = re.compile(r'(?<![\w./-])tools/[\w./-]*\w')
SOURCES = ('Dockerfile', 'compose*.yaml', 'pyproject.toml', 'MANIFEST.in', 'install.sh', 'install.ps1', '*.md',
           '.github/**/*', 'deploy/**/*', 'docs/**/*.md', 'tools/*', 'pokesim/**/*.py')
HISTORY = ('CHANGELOG.md', 'docs/history/', 'docs/validation/')
RECORDS = {
    'tools/cable_club_spike.py': 'The cable experiment at commit 705ec4d, which the multi-adventure plan cites',
    'tools/prepare_cable_fixtures.py': 'The cable experiment branch copy. The fixture builder is now tools/verify_cartridge.py cable-fixtures',
    'tools/gen1_wild.py': 'Removed by step 5 of the planner systems note, #203',
    'tools/link_spike.py': 'Removed after commit 7053c654. docs/link-spike.md keeps what it measured',
    'tools/temp-wheels': 'Exists only in the TEMP pin commit that docs/publishing.md describes',
}


def sources():
    """Each file that runs or documents a tool, outside the history, and its text."""
    paths = {path for pattern in SOURCES for path in ROOT.glob(pattern) if path.is_file()}
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        if not name.startswith(HISTORY) and '__pycache__' not in path.parts:
            yield name, path.read_text(encoding='utf-8', errors='ignore')


def named(text):
    """The tools/ paths a text names. A path inside another folder's tools/ is not one."""
    return {match.group(0) for match in PATH.finditer(text)}


def exists(path):
    return any((base / path).exists() for base in BASES)


def test_every_tool_a_file_names_exists():
    missing = sorted(f'{name} names {path}' for name, text in sources() for path in named(text)
                     if path not in RECORDS and not exists(path))
    assert missing == [], 'Update each file that names a tool you moved or deleted.'


@pytest.mark.parametrize('path', RECORDS)
def test_each_record_still_names_a_tool_that_is_gone(path):
    """A record that stops naming its tool, or a tool that comes back, leaves RECORDS."""
    assert any(path in named(text) for _, text in sources())
    assert not exists(path)


def test_the_scan_reads_paths_from_commands_and_prose():
    text = 'Run `python tools/a.py --x`, then sh tools/b.sh. See packages/pokecore/tools/c.py and the tools/ folder.'
    assert named(text) == {'tools/a.py', 'tools/b.sh'}
