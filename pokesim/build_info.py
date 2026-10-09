"""Identify running source and retain its identity in built distributions."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess

from . import __version__


def source_info(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    result = {'version': __version__, 'revision': None, 'dirty': None}
    if (root / '.git').exists():
        try:
            revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                               text=True, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL).strip()
            dirty = bool(subprocess.check_output(
                ['git', '-C', str(root), 'status', '--porcelain'], text=True, stdin=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL))
            return dict(result, revision=revision, dirty=dirty)
        except (OSError, subprocess.CalledProcessError):
            pass
    metadata = root / 'pokesim' / '_build.json'
    if metadata.is_file():
        data = json.loads(metadata.read_text(encoding='utf-8'))
        if data.get('version') != __version__:
            raise RuntimeError('Build identity does not match the application version')
        result.update(revision=data.get('revision'), dirty=data.get('dirty'))
    revision = os.environ.get('POKESIM_REVISION', '')
    if re.fullmatch(r'[0-9a-f]{40}', revision):
        result.update(revision=revision, dirty=None)
    return result


@lru_cache(maxsize=1)
def build_info():
    return source_info()


def version_label(info=None):
    """Name the running build as people see it: the release and its short commit."""
    info = build_info() if info is None else info
    revision = info.get('revision') or ''
    return f"v{info.get('version') or __version__}" + (f' · {revision[:7]}' if revision else '')
