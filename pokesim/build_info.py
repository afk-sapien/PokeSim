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
                                               text=True, stderr=subprocess.DEVNULL).strip()
            dirty = bool(subprocess.check_output(
                ['git', '-C', str(root), 'status', '--porcelain'], text=True, stderr=subprocess.DEVNULL))
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
