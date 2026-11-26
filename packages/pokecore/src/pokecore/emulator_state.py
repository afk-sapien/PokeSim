"""Backend provenance and explicitly supported checkpoint compatibility."""
from functools import lru_cache
import hashlib
from importlib.metadata import distribution
from pathlib import Path

# A PyBoy 2.7.0 format 15 state. PyBoy and pyboy-rs 0.1.9 and older save it with nothing after it.
# pyboy-rs 0.2 and later save a section of their own after that body, and name the format with a plus
# sign and the section, so an older build that requires this exact name refuses their checkpoints.
LEGACY_STATE_FORMAT = "pyboy-format-15"
LEGACY_PYBOY_VERSION = "2.7.0"


@lru_cache(maxsize=1)
def backend_formats():
    """The state format the installed pyboy-rs writes, and every format it loads, as it names them."""
    from pyboy_rs import execution
    return execution.STATE_FORMAT, frozenset(execution.STATE_FORMATS)


def _body(state_format):
    """The PyBoy format of a state's body, the part before any pyboy-rs section."""
    return str(state_format or "").partition("+")[0]


@lru_cache(maxsize=1)
def _runtime_provenance():
    installed = distribution("pyboy-rs")
    native = sorted(installed.locate_file(p) for p in installed.files or ()
                    if str(p).startswith("pyboy_rs/") and str(p).endswith((".so", ".pyd")))
    if len(native) != 1:
        raise RuntimeError("Cannot identify the installed native emulator")
    wrapper = Path(native[0]).parent / "pyboy.py"
    binding = hashlib.sha256(wrapper.read_bytes())
    for name in ('execution.py', 'diagnostics.py'):
        component = wrapper.with_name(name)
        if component.exists():
            binding.update(component.read_bytes())
    return {"backend": "pyboy-rs", "version": installed.version, "state_format": backend_formats()[0],
            "native_sha256": hashlib.sha256(Path(native[0]).read_bytes()).hexdigest(),
            "binding_sha256": binding.hexdigest()}


def runtime_provenance():
    return dict(_runtime_provenance())


def validate_runtime(metadata, *, exact=False, version=False):
    """Allow known legacy imports, require the original build for exact resume.

    exact compares the full provenance, including the compiled binary hashes, which change
    with every rebuild and platform. version requires the same backend version without the
    hashes. The default checks only the backend and that the installed backend loads the state format.
    """
    source = metadata.get("emulator")
    if source is None:
        if not exact and metadata.get("pyboy_version") == LEGACY_PYBOY_VERSION:
            return
        if "pyboy_version" in metadata and not exact:
            raise ValueError("Checkpoint requires a different or unsupported emulator version")
        raise ValueError("Checkpoint requires explicit emulator provenance")
    if not isinstance(source, dict):
        raise ValueError("Invalid emulator provenance")
    if source.get("backend") != "pyboy-rs" or source.get("state_format") not in backend_formats()[1]:
        raise ValueError("Unsupported checkpoint emulator or state format")
    current = runtime_provenance() if exact or version else None
    if version and source.get("version") != current["version"]:
        raise ValueError(f"Checkpoint was saved by {source.get('backend')} {source.get('version')}, "
                         f"but this build is {current['version']}")
    if exact and source != current:
        raise ValueError("Resume requires the original emulator build")


def _legacy_fields(metadata):
    """The PyBoy 2.7.0 version tag, only when a PyBoy 2.7.0 build could load these states.

    pyboy-rs writes a PyBoy 2.7.0 format 15 body, and PyBoy 2.7.0 loads it and leaves any pyboy-rs
    section after it unread. A clock lock is the exception: PyBoy 2.7.0 has no lock, so a checkpoint
    saved while locked is not tagged.
    """
    if _body(runtime_provenance()["state_format"]) != LEGACY_STATE_FORMAT:
        return {}
    if metadata.get("rtc_clock") is not None:
        return {}
    return {"pyboy_version": LEGACY_PYBOY_VERSION}


def checkpoint_metadata(*, rtc_clock=None):
    """Provenance for a checkpoint about to be written, with the PyBoy 2.7.0 tag that lets an
    older application still load it. Pass the checkpoint's rtc_clock so a locked save is not tagged."""
    return {"emulator": dict(runtime_provenance()), **_legacy_fields({"rtc_clock": rtc_clock})}


def runtime_identity(metadata):
    if "emulator" in metadata:
        return metadata["emulator"]
    return {"backend": "pyboy", "version": metadata.get("pyboy_version")}


def retag_checkpoint(metadata):
    """Describe newly serialized Rust output while retaining its source lineage."""
    previous = dict(runtime_identity(metadata))
    current = runtime_provenance()
    result = dict(metadata)
    result.pop("pyboy_version", None)
    result["emulator"] = current
    # Keep the PyBoy 2.7.0 tag when the source lineage and the new output both have a format 15 body,
    # so a downgrade to an application that still requires it can load the checkpoint.
    legacy_source = (previous.get("backend") == "pyboy" and previous.get("version") == LEGACY_PYBOY_VERSION) \
        or (previous.get("backend") == "pyboy-rs" and _body(previous.get("state_format")) == LEGACY_STATE_FORMAT)
    if legacy_source:
        result.update(_legacy_fields(metadata))
    if previous != current:
        result["emulator_migration"] = {"from": previous, "to": dict(current)}
    return result


def same_runtime_or_recorded_migration(source, output):
    before, after = runtime_identity(source), runtime_identity(output)
    if before == after:
        return True
    try:
        validate_runtime(source)
        validate_runtime(output)
    except ValueError:
        return False
    return output.get("emulator_migration") == {"from": before, "to": after}
