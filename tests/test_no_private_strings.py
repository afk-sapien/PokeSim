"""Fail if homelab or personal specifics reappear in tracked files."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Built from pieces so this file does not contain the strings it forbids.
FORBIDDEN = [
    'tyn' + 'et', 'serv' + 'arr', 'prox' + 'mox', 'varl' + 'amore',
    'pokeb' + 'ench', 'open' + 'claw', 'proton' + r'\.me', 'unhelp' + 'ful',
    'pokesim-' + '(?:red|blue)',
    r'192\.' + '168' + r'\.', '/dock' + 'er/pokesim', '/ho' + 'me/ty',
    r'[/\\]' + 'down' + r'loads[/\\]',
    # Private network addresses: 10.x.x.x and 172.16-31.x.x
    r'(?<![\w.])10(?:\.\d{1,3}){3}(?![\w.])',
    r'(?<![\w.])172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}(?![\w.])',
]
PATTERN = re.compile('|'.join(FORBIDDEN), re.IGNORECASE)


def tracked():
    """Tracked files, or a loud failure. A silent pass would hide a missing scan."""
    try:
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        pytest.fail(f'git is required to list tracked files for the private-string scan: {error}')
    return [ROOT / name for name in out.decode().split('\0') if name]


def test_no_homelab_or_personal_strings_in_tracked_files():
    files = tracked()
    assert files, 'git ls-files returned nothing'
    hits = []
    for path in files:
        if path == Path(__file__).resolve() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                hits.append(f'{path.relative_to(ROOT)}:{number}')
    assert not hits, 'private strings found: ' + ', '.join(hits[:20])


@pytest.mark.parametrize('text', [
    'C:\\Users\\x\\Downloads\\roms', '/home/x/downloads/rom', 'host 10.1.2.3', 'ssh 172.20.0.5',
    'PokeBench', 'OpenClaw', 'User@Proton.me', 'POKESIM-BLUE.example',
])
def test_pattern_catches_each_class_case_insensitively(text):
    assert PATTERN.search(text), text


@pytest.mark.parametrize('text', ['version 0.10.1.2', 'downloads are verified', 'docker 110.1.2.3', '172.32.0.1'])
def test_pattern_ignores_ordinary_text(text):
    assert not PATTERN.search(text), text


def test_missing_git_fails_loudly(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError('git')
    monkeypatch.setattr(subprocess, 'run', missing)
    with pytest.raises(pytest.fail.Exception, match='git is required'):
        tracked()
