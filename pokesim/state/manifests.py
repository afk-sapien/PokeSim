"""The rewinding state of an adventure as its newest autosave keeps it, read from files alone.

The policy state, the run memory and the Gen II history live only in each checkpoint's manifest
(docs/design/adventure-state-store.md section 3.5). A tool that watches a running adventure reads
them here, without opening the adventure's store.
"""
from pathlib import Path

from ..checkpoints import read_manifest


def newest(states):
    """The manifest of the newest autosave in an adventure's ``states`` folder, or None when it has none.

    Newest first by the creation time in the name, as CheckpointStore.autosaves breaks its ties. The
    adventure prunes its autosaves as it plays, so one that goes before it is read gives way to the next.
    """
    saves = sorted((path for path in Path(states).glob('auto-v1-*.json') if path.stem[8:].isdecimal()),
                   key=lambda path: int(path.stem[8:]), reverse=True)
    for path in saves:
        try:
            manifest = read_manifest(path)
        except (OSError, EOFError, ValueError):
            continue
        if isinstance(manifest, dict):
            return manifest
    return None
