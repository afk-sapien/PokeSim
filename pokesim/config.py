import math
import os
from urllib.parse import urlsplit
from pathlib import Path


def _env(name, default):
    return os.environ.get(name, default)


ROM_PATH = Path(_env("ROM_PATH", "roms/pokered.gb"))
DATA_DIR = Path(_env("DATA_DIR", "data"))
SPEED = float(_env("SPEED", "1"))            # emulation speed multiplier, 0 = unlimited
POLICY = _env("POLICY", "strategic")
FAST_TEXT = _env("FAST_TEXT", "1") == "1"                  # force text speed FAST via wOptions
BATTLE_ANIMATIONS = _env("BATTLE_ANIMATIONS", "1") == "1"  # 0 = turn battle animations off (faster)
SEED = int(_env("SEED", "0")) or None
NTFY_URL = _env("NTFY_URL", "")              # e.g. https://ntfy.example.com/pokesim, empty = off
NTFY_TOKEN = _env("NTFY_TOKEN", "")
NTFY_MIN_PRIORITY = int(_env("NTFY_MIN_PRIORITY", "2"))   # 1..5: only push events at or above this priority
NTFY_MUTE = {t.strip() for t in _env("NTFY_MUTE", "").split(",") if t.strip()}   # event types never pushed
PUBLIC_URL = _env("PUBLIC_URL", "http://localhost:8000").rstrip("/")
PORT = int(_env("PORT", "8000"))
AUTOSAVE_SECONDS = int(_env("AUTOSAVE_SECONDS", "60"))
KEEP_AUTOSAVES = int(_env("KEEP_AUTOSAVES", "20"))
STUCK_RELOAD_SECONDS = int(_env("STUCK_RELOAD_SECONDS", "600"))
BATTLE_TIMEOUT_SECONDS = int(_env("BATTLE_TIMEOUT_SECONDS", "900"))
STREAM_FPS = int(_env("STREAM_FPS", "15"))
FEED_TITLE = _env("FEED_TITLE", "pokesim")

# Clean Pokemon Red (USA, Europe) dump. A mismatch is only a warning.
KNOWN_ROM_SHA1 = {
    "ea9bcae617fdf159b045185467ae58b2e4a48b9a": "Pokemon Red (USA, Europe)",
    "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2": "Pokemon Blue (USA, Europe)",
}

HOST = _env("HOST", "127.0.0.1")
VIEWER_ONLY = _env("VIEWER_ONLY", "0") == "1"
EVENT_RETENTION_DAYS = int(_env("EVENT_RETENTION_DAYS", "0"))


def validate():
    """Reject invalid configuration before starting the emulator."""
    ranges = {
        "SPEED": (SPEED, 0, 16),
        "PORT": (PORT, 1, 65535),
        "AUTOSAVE_SECONDS": (AUTOSAVE_SECONDS, 1, 86400),
        "KEEP_AUTOSAVES": (KEEP_AUTOSAVES, 1, 10000),
        "STUCK_RELOAD_SECONDS": (STUCK_RELOAD_SECONDS, 1, 604800),
        "BATTLE_TIMEOUT_SECONDS": (BATTLE_TIMEOUT_SECONDS, 1, 604800),
        "STREAM_FPS": (STREAM_FPS, 1, 60),
        "NTFY_MIN_PRIORITY": (NTFY_MIN_PRIORITY, 1, 5),
        "EVENT_RETENTION_DAYS": (EVENT_RETENTION_DAYS, 0, 36500),
    }
    for name, (value, low, high) in ranges.items():
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
    if SPEED and SPEED < 0.1:
        raise ValueError("SPEED must be 0 for unlimited, or between 0.1 and 16")
    if POLICY not in {"strategic", "smart_random", "guided_random"}:
        raise ValueError("POLICY must be strategic, smart_random, or guided_random")
    for name in ("FAST_TEXT", "BATTLE_ANIMATIONS", "VIEWER_ONLY"):
        if _env(name, "0") not in {"0", "1"}:
            raise ValueError(f"{name} must be 0 or 1")
    for name, value in (("PUBLIC_URL", PUBLIC_URL), ("NTFY_URL", NTFY_URL)):
        if name == "NTFY_URL" and not value:
            continue
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError(f"{name} must be an HTTP or HTTPS URL without credentials")
    if not ROM_PATH.is_file():
        raise ValueError(f"ROM_PATH must point to a readable ROM file: {ROM_PATH}")
    with ROM_PATH.open("rb") as rom:
        if not rom.read(1):
            raise ValueError("ROM_PATH points to an empty file")
