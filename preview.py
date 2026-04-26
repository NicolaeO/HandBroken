"""
preview.py — generate quality calibration clips for your encoder.

Encodes a 10-second segment of a source file at every preset quality level
for the configured encoder, plus an untouched copy of the same segment.
Open the output folder in your media player and compare to find the quality
level that looks right for your library.

Usage:
  python preview.py <file>
  python preview.py <file> --start 120      # start at 2 minutes in
  python preview.py <file> --duration 15    # 15-second clips
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import config as cfg
import encoders as enc

PREVIEW_DIR = Path(__file__).parent / ".preview"
DEFAULT_DURATION = 10  # seconds

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _probe_duration(src: Path, ffprobe: str) -> float:
    cmd = [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(json.loads(r.stdout)["format"].get("duration", 0))
    except Exception:
        return 0.0


def _auto_start(src: Path, ffprobe: str) -> int:
    """Pick a start time at 30% through the file, at least 30s in."""
    duration = _probe_duration(src, ffprobe)
    return max(30, int(duration * 0.30)) if duration else 30


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-500:])  # last 500 chars of stderr


def _file_stats(path: Path) -> str:
    kb = path.stat().st_size / 1024
    if kb >= 1024:
        return f"{kb / 1024:.2f} MB"
    return f"{kb:.0f} KB"


# ── clip generators ───────────────────────────────────────────────────────────

def _extract_source(src: Path, start: int, duration: int,
                    out: Path, ffmpeg: str) -> None:
    """Stream-copy the source segment — no re-encode, exact original quality."""
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-i", str(src),
        "-t", str(duration),
        "-c", "copy",
        "-y", str(out),
    ])


def _encode_clip(src: Path, start: int, duration: int, quality: int,
                 encoder: str, out: Path, ffmpeg: str) -> None:
    """Encode a preview clip at the given quality level."""
    vs = {
        "quality":      quality,
        "bitdepth":     8,      # 8-bit for preview speed; HDR content may differ
        "maxrate_kbps": 0,      # no cap — let quality drive bitrate freely
    }
    video_flags = enc.build_video_flags(encoder, vs)

    # Colour metadata (bt709 defaults — good for SDR preview content)
    setparams = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"

    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-i", str(src),
        "-t", str(duration),
        "-vf", setparams,
        *video_flags,
        "-color_primaries", "bt709",
        "-color_trc",       "bt709",
        "-colorspace",      "bt709",
        "-c:a", "copy",
        "-y", str(out),
    ])


# ── main ──────────────────────────────────────────────────────────────────────

def run_preview(file_path: str,
                start: int | None = None,
                duration: int = DEFAULT_DURATION) -> None:
    conf    = cfg.load()
    encoder = conf["encoder"]
    profile = enc.PROFILES[encoder]
    ffmpeg  = conf["ffmpeg_path"]
    ffprobe = conf["ffprobe_path"]

    src = Path(file_path)
    if not src.exists():
        logger.error(f"File not found: {src}")
        sys.exit(1)

    if start is None:
        logger.info("Probing file duration …")
        start = _auto_start(src, ffprobe)

    qualities = profile["preview_qualities"]
    label     = profile["quality_label"]

    out_dir = PREVIEW_DIR / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("")
    logger.info(f"  Source   : {src.name}")
    logger.info(f"  Encoder  : {profile['name']}")
    logger.info(f"  Clip     : {start}s – {start + duration}s  ({duration}s)")
    logger.info(f"  Levels   : {label} {qualities}  ({len(qualities)} clips)")
    logger.info(f"  Output   : {out_dir}")
    logger.info(f"  Note     : .preview is a hidden folder — on Windows enable 'Show hidden items'")
    logger.info(f"             in Explorer; on macOS/Linux use  ls -a  or  open -a Finder .")
    logger.info("")

    results: list[tuple[str, str, str]] = []  # (label, filename, size)

    # ── 00_source — stream copy, no re-encode ────────────────────────────────
    src_file = out_dir / "00_source.mkv"
    logger.info("  Extracting source …")
    try:
        _extract_source(src, start, duration, src_file, ffmpeg)
        size = _file_stats(src_file)
        logger.info(f"  [source ]  {size:>8}  →  {src_file.name}")
        results.append(("source (original)", src_file.name, size))
    except RuntimeError as e:
        logger.warning(f"  [source ]  FAILED: {e}")

    # ── quality level clips ───────────────────────────────────────────────────
    for i, quality in enumerate(qualities, 1):
        tag      = f"{label.lower()}{quality}"
        out_file = out_dir / f"{i:02d}_{encoder}_{tag}.mkv"
        is_transparent = (quality == profile["quality_transparent"])
        is_efficient   = (quality == profile["quality_efficient"])
        note = " ← transparent default" if is_transparent else (
               " ← efficient default"   if is_efficient   else "")

        logger.info(f"  Encoding {label} {quality} …")
        try:
            _encode_clip(src, start, duration, quality, encoder, out_file, ffmpeg)
            size = _file_stats(out_file)
            logger.info(f"  [{label} {quality:<3}]  {size:>8}  →  {out_file.name}{note}")
            results.append((f"{label} {quality}{note}", out_file.name, size))
        except RuntimeError as e:
            logger.warning(f"  [{label} {quality:<3}]  FAILED: {e}")

    # ── summary ───────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("  Done. Open the files below in your media player and compare:")
    logger.info(f"  {out_dir}")
    logger.info("")
    logger.info(f"  {'Setting':<30} {'Size':>8}  File")
    logger.info(f"  {'-'*30} {'--------':>8}  ----")
    for setting, fname, size in results:
        logger.info(f"  {setting:<30} {size:>8}  {fname}")
    logger.info("")
    logger.info(f"  Update encoders.py → quality_transparent / quality_efficient")
    logger.info(f"  with whichever {label} level looks best.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate quality calibration clips for your encoder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("file",       help="Source video file to sample from")
    parser.add_argument("--start",    type=int, default=None,
                        help="Start time in seconds (default: 30%% into the file)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Clip length in seconds (default: {DEFAULT_DURATION})")
    args = parser.parse_args()
    run_preview(args.file, args.start, args.duration)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
