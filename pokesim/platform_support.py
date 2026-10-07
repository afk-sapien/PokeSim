"""Explain, instead of showing an import traceback, why PokeSim cannot run on an unsupported platform."""
import importlib.util
import platform
import sys

MESSAGE = (
    'PokeSim 0.5 has no emulator build for this platform ({system} {machine}).\n'
    'Supported: Linux x86-64 and ARM64 (glibc), macOS Intel and Apple Silicon, and Windows x64.\n'
    'The Docker image (linux/amd64) is the alternative.\n'
    'Do not run "pip install pokesim": that installs an unrelated project from PyPI. The emulator packages\n'
    '(pyboy-rs and pokesim-core) are published only as GitHub release files, never from PyPI.')


def require_emulator():
    """Exit with a clear message when the emulator packages are absent. Does nothing where they are installed."""
    try:
        import pokesim_core  # noqa: F401  (Core imports its emulator backend itself)
        missing = importlib.util.find_spec('pyboy_rs') is None
    except ImportError as error:
        sys.exit(MESSAGE.format(system=platform.system() or sys.platform, machine=platform.machine()) + f'\n({error})')
    if missing:
        sys.exit(MESSAGE.format(system=platform.system() or sys.platform, machine=platform.machine()) + '\n(pyboy-rs is not installed)')
