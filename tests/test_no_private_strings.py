"""Fail if homelab or personal specifics reappear in tracked files."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Built from pieces so this file does not contain the strings it forbids.
FORBIDDEN = [
    'tyn' + 'et', 'serv' + 'arr', 'prox' + 'mox', 'varl' + 'amore',
    r'192\.' + '168' + r'\.', '/dock' + 'er/pokesim', '/ho' + 'me/ty',
]
PATTERN = re.compile('|'.join(FORBIDDEN))


def tracked():
    try:
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [ROOT / name for name in out.decode().split('\0') if name]


def test_no_homelab_or_personal_strings_in_tracked_files():
    files = tracked()
    if files is None:
        return  # source archive without git metadata
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
