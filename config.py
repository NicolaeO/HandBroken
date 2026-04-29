"""Load user configuration from config.json (falls back to defaults if missing)."""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"

_DEFAULTS: dict = {
    "encoder":           "amd",          # amd | nvidia | cpu
    "ffmpeg_path":       "ffmpeg",
    "ffprobe_path":      "ffprobe",
    "mkvpropedit_path":  "mkvpropedit",  # optional — part of MKVToolNix
}


def load() -> dict:
    """Return merged config: file values override defaults."""
    if not _CONFIG_PATH.exists():
        return _DEFAULTS.copy()
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {**_DEFAULTS, **data}
