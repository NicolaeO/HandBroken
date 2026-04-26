"""
check_env.py — verify all dependencies before running.

  python check_env.py

Checks:
  1. Python 3.10+
  2. ffmpeg in PATH (or configured path)
  3. ffprobe in PATH (or configured path)
  4. Selected encoder is functional (driver / hardware test encode)
"""

import shutil
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))
import config as cfg
import encoders


def _ok(msg: str) -> bool:
    print(f"  [OK]   {msg}")
    return True


def _fail(msg: str) -> bool:
    print(f"  [FAIL] {msg}")
    return False


def check_python() -> bool:
    v = sys.version_info
    if v >= (3, 10):
        return _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    return _fail(f"Python {v.major}.{v.minor} found — requires 3.10+")


def check_tool(label: str, path: str) -> bool:
    found = shutil.which(path)
    if found:
        return _ok(f"{label} found  →  {found}")
    return _fail(
        f"{label} not found in PATH (configured path: '{path}')\n"
        f"         Download: https://ffmpeg.org/download.html  (gyan.dev full build recommended)"
    )


def check_selected_encoder(conf: dict) -> bool:
    encoder = conf["encoder"]

    if encoder not in encoders.PROFILES:
        known = ", ".join(encoders.PROFILES)
        return _fail(f"Unknown encoder '{encoder}' in config.json — valid options: {known}")

    profile = encoders.PROFILES[encoder]
    print(f"  Testing {profile['name']} with a 1-second null encode …")

    if encoders.check_encoder(encoder, conf["ffmpeg_path"]):
        return _ok(f"{profile['name']} is working")

    return _fail(
        f"{profile['name']} is NOT available\n"
        f"         Requirements: {profile['requirements']}"
    )


def main() -> None:
    print("Checking environment…\n")
    conf = cfg.load()
    print(f"  Encoder : {conf['encoder']}")
    print(f"  ffmpeg  : {conf['ffmpeg_path']}")
    print(f"  ffprobe : {conf['ffprobe_path']}")
    print()

    results = [
        check_python(),
        check_tool("ffmpeg",  conf["ffmpeg_path"]),
        check_tool("ffprobe", conf["ffprobe_path"]),
        check_selected_encoder(conf),
    ]

    print()
    failed = results.count(False)
    if failed == 0:
        print("All checks passed — ready to encode.")
        sys.exit(0)
    else:
        print(f"{failed} check(s) failed. Fix the issues above and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
