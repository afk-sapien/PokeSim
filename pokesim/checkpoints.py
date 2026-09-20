"""Checkpoint files, manifests, validation, and retention independent of SQLite."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from .platform_io import sync_directory

log = logging.getLogger(__name__)


class CheckpointStore:
    def __init__(self, states: Path):
        self.states = Path(states)
        self.states.mkdir(parents=True, exist_ok=True)

    def autosave_path(self) -> Path:
        return self.states / f"auto-v1-{time.time_ns()}.state"

    def autosaves(self) -> list[Path]:
        return sorted(self.states.glob("auto-*.state"), key=lambda p: p.stat().st_mtime_ns)

    def latest_state(self) -> Path | None:
        saves = self.autosaves()
        return saves[-1] if saves else None

    def prune_autosaves(self, keep: int):
        for p in self.autosaves()[:-keep] if keep > 0 else []:
            p.unlink(missing_ok=True)
            p.with_suffix(".json").unlink(missing_ok=True)

    def state_path(self, name: str) -> Path | None:
        if Path(name).name != name or "\\" in name or not name.endswith(".state"):
            return None
        p = self.states / name
        try:
            return p if p.resolve().parent == self.states.resolve() and p.is_file() else None
        except (OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    def atomic_write(path: Path, data: bytes):
        """Publish a complete file only after its contents reach disk."""
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def write_checkpoint(self, state: bytes, metadata: dict, name: str | None = None) -> Path:
        # A named checkpoint sits outside the rotating autosaves, so it is never pruned or resumed by accident.
        path = self.states / name if name else self.autosave_path()
        manifest = dict(metadata, format=1, sha256=hashlib.sha256(state).hexdigest())
        manifest_bytes = json.dumps(manifest).encode()
        try:
            self.atomic_write(path, state)
            self.atomic_write(path.with_suffix(".json"), manifest_bytes)
        except OSError:
            for output in (path, path.with_suffix(".json")):
                try:
                    output.unlink(missing_ok=True)
                except OSError:
                    log.exception("Cannot remove incomplete checkpoint file %s", output)
            raise
        return path

    def checkpoint_metadata(self, path: Path) -> dict | None:
        manifest = path.with_suffix(".json")
        if not manifest.exists() and not path.name.startswith("auto-v1-"):
            return None
        data = json.loads(manifest.read_text())
        if not isinstance(data, dict) or data.get("format") != 1:
            raise ValueError("Unsupported checkpoint format")
        if data.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("Checkpoint checksum does not match")
        if not isinstance(data.get("policy_state"), dict) or not isinstance(data.get("run_memory"), dict):
            raise ValueError("Checkpoint memory is invalid")
        return data
