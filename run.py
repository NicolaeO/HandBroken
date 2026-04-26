"""
run.py — main entry point for the batch transcoder.

Usage:
  python run.py scan   <folder> [--out scan.json]
  python run.py encode [--dry-run] [--clean]
  python run.py run    <folder> [--dry-run] [--clean]
  python run.py clean

  scan   : probe all video files in <folder>, write results/<timestamp>_scan.json
  encode : pick a scan JSON, transcode files marked "transcode"
  run    : scan + encode in one step
  clean  : pick a scan JSON, delete all _ORIG_ files from those folders

Flags:
  --dry-run   show what would be done, but do not encode or delete anything
  --clean     after encoding, also delete the _ORIG_ files (same as running clean afterwards)

Outputs:
  logs/YYYY-MM-DD_HH-MM-SS.log   one log file per run
  results/<timestamp>_scan.json  scan output (same timestamp as the log)
"""

import argparse
import logging
import random
import re
import string
import sys
from datetime import datetime
from pathlib import Path

from scanner import VideoScanner
from optimizer import SettingsOptimizer
from transcoder import Transcoder

BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"
RESULTS_DIR = BASE_DIR / "results"


# Folder names that are too generic to use alone (would collide across series/movies)
_GENERIC_NAMES = {
    "season", "specials", "extras", "bonus", "featurettes",
    "movies", "films", "video", "videos", "media",
    "downloads", "converted", "encode", "encoded",
}
_GENERIC_PATTERNS = [
    re.compile(r"^season\s*\d+$", re.IGNORECASE),
    re.compile(r"^s\d{1,2}$", re.IGNORECASE),
    re.compile(r"^disc\s*\d+$", re.IGNORECASE),
    re.compile(r"^part\s*\d+$", re.IGNORECASE),
    re.compile(r"^vol(ume)?\s*\d+$", re.IGNORECASE),
]


def _scan_json_name(folder: Path, timestamp: str) -> Path:
    """Build a results filename from the scanned folder name + timestamp."""
    raw = folder.resolve().name
    # Sanitize to filesystem-safe characters
    safe = re.sub(r"[^\w\-]", "_", raw).strip("_") or "scan"

    is_generic = (
        raw.lower() in _GENERIC_NAMES
        or any(p.match(raw) for p in _GENERIC_PATTERNS)
    )
    if is_generic:
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        safe = f"{safe}_{rand}"

    return RESULTS_DIR / f"{safe}.json"


# ── logging ───────────────────────────────────────────────────────────────────

_LOG_FMT = "%(asctime)s %(levelname)-8s %(message)s"


def _init_logging() -> None:
    """Stdout-only logging used until we know the action + folder name."""
    logging.basicConfig(level=logging.INFO, format=_LOG_FMT,
                        handlers=[logging.StreamHandler(sys.stdout)])


def _add_file_logging(action: str, folder_name: str, timestamp: str) -> None:
    """Add a file handler once we know the action and folder.

    Log name: {action}_{folder}_{YYYY-MM-DD_HH-MM-SS}.log
    """
    LOGS_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", folder_name).strip("_") or "unknown"
    date = timestamp[:10]           # YYYY-MM-DD
    time_part = timestamp[11:]      # HH-MM-SS
    log_file = LOGS_DIR / f"{action}_{safe}_{date}_{time_part}.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FMT))
    logging.getLogger().addHandler(handler)
    logging.info(f"Log: {log_file}")


# ── shared helpers ────────────────────────────────────────────────────────────

def _pick_scan_json() -> Path | None:
    """List JSON files in results/ newest-first and let the user pick one."""
    RESULTS_DIR.mkdir(exist_ok=True)
    files = sorted(RESULTS_DIR.glob("*.json"), reverse=True)

    if not files:
        logging.error(f"No scan JSON files found in {RESULTS_DIR}")
        return None

    print("\nAvailable scan files:")
    for i, f in enumerate(files, 1):
        size_kb = f.stat().st_size / 1024
        print(f"  [{i}] {f.name}  ({size_kb:.1f} KB)")

    print()
    raw = input(f"Select file [1-{len(files)}]: ").strip()
    try:
        idx = int(raw) - 1
        if not 0 <= idx < len(files):
            raise ValueError
        return files[idx]
    except ValueError:
        logging.error("Invalid selection.")
        return None


def _find_orig_folders(scan_records: list[dict]) -> list[Path]:
    """Return all .originals folders that exist in the scanned paths' directories."""
    folders = {Path(r["path"]).parent for r in scan_records}
    return sorted(f / ".originals" for f in folders if (f / ".originals").is_dir())


def _clean_orig_files(scan_records: list[dict], dry_run: bool = False) -> None:
    orig_dirs = _find_orig_folders(scan_records)

    if not orig_dirs:
        logging.info("No .originals folders found.")
        return

    orig_files = [f for d in orig_dirs for f in sorted(d.iterdir()) if f.is_file()]

    if not orig_files:
        logging.info("No files found inside .originals folders.")
        return

    total_gb = sum(f.stat().st_size for f in orig_files) / 1024 ** 3
    logging.info(f"Found {len(orig_files)} original(s) in {len(orig_dirs)} .originals folder(s)  ({total_gb:.2f} GB)")
    for f in orig_files:
        size_gb = f.stat().st_size / 1024 ** 3
        logging.info(f"  {f.parent.parent.name}/.originals/{f.name}  ({size_gb:.2f} GB)")

    if dry_run:
        logging.info("[DRY RUN] No files deleted.")
        return

    print()
    confirm = input(f"Permanently delete {len(orig_files)} original(s)? (yes/no): ").strip().lower()
    if confirm != "yes":
        logging.info("Clean cancelled.")
        return

    deleted, errors = 0, 0
    for f in orig_files:
        try:
            f.unlink()
            logging.info(f"  Deleted: {f.name}")
            deleted += 1
        except Exception as e:
            logging.error(f"  Failed to delete {f.name}: {e}")
            errors += 1

    # Remove now-empty .originals folders
    for d in orig_dirs:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                logging.info(f"  Removed empty folder: {d}")
        except Exception:
            pass

    logging.info(f"Deleted {deleted} file(s), {errors} error(s)  (freed ~{total_gb:.2f} GB)")


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace, _setup_log: bool = True) -> None:
    if _setup_log:
        _add_file_logging("scan", args.folder.resolve().name, args.timestamp)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = args.out or _scan_json_name(args.folder, args.timestamp)
    scanner = VideoScanner()
    scanner.scan_folder(args.folder)
    scanner.save_json(out)
    logging.info(f"Results: {out}")


def cmd_encode(args: argparse.Namespace, _setup_log: bool = True) -> None:
    scan_path = _pick_scan_json()
    if scan_path is None:
        logging.error("No scan JSON file selected.")
        return

    if _setup_log:
        _add_file_logging("encode", scan_path.stem, args.timestamp)
    logging.info(f"Loading: {scan_path.name}")
    all_records = VideoScanner.load_json(scan_path)
    to_transcode = [r for r in all_records if r["action"] == "transcode"]

    if not to_transcode:
        logging.info("Nothing to transcode.")
        return

    optimizer = SettingsOptimizer()
    transcoder = Transcoder()

    total = len(to_transcode)
    total_est_saving = sum(r["estimated_saving_gb"] for r in to_transcode)

    logging.info("=" * 60)
    logging.info(f"Files to encode : {total}")
    logging.info(f"Estimated saving: ~{total_est_saving:.1f} GB")
    logging.info("=" * 60)

    for i, rec in enumerate(to_transcode, 1):
        v = rec["video"]
        logging.info(
            f"  [{i}/{total}] {Path(rec['path']).name}  "
            f"{v['codec'].upper()} {v['width']}x{v['height']} "
            f"{rec['size_gb']:.1f} GB  →  ~{rec['estimated_saving_gb']:.1f} GB saved"
        )

    if getattr(args, "keep_larger", False):
        logging.info("  --keep-larger: size guard disabled, encoded files kept even if larger than source")

    if args.dry_run:
        logging.info("\n[DRY RUN] No files encoded.")
        if args.clean:
            logging.info("\n[DRY RUN] .originals cleanup that would follow:")
            _clean_orig_files(all_records, dry_run=True)
        return

    print()
    confirm = input(f"Encode {total} file(s)? (yes/no): ").strip().lower()
    if confirm != "yes":
        logging.info("Cancelled.")
        return

    success, failed = [], []

    for i, rec in enumerate(to_transcode, 1):
        name = Path(rec["path"]).name
        logging.info("")
        logging.info(f"[{i}/{total}] {name}")
        logging.info("-" * 60)

        settings = optimizer.get_settings(rec)
        ok = transcoder.transcode(settings, keep_larger=args.keep_larger)

        (success if ok else failed).append(name)

    logging.info("")
    logging.info("=" * 60)
    logging.info("DONE")
    logging.info(f"  Success : {len(success)}")
    logging.info(f"  Failed  : {len(failed)}")
    if failed:
        logging.info("  Failed files:")
        for f in failed:
            logging.info(f"    - {f}")
    logging.info("=" * 60)

    if args.clean:
        logging.info("")
        _clean_orig_files(all_records)


def cmd_clean(args: argparse.Namespace) -> None:
    scan_path = _pick_scan_json()
    if scan_path is None:
        return

    _add_file_logging("clean", scan_path.stem, args.timestamp)
    logging.info(f"Loading: {scan_path.name}")
    all_records = VideoScanner.load_json(scan_path)
    _clean_orig_files(all_records, dry_run=args.dry_run)


def cmd_revert(args: argparse.Namespace) -> None:
    scan_path = _pick_scan_json()
    if scan_path is None:
        return

    _add_file_logging("revert", scan_path.stem, args.timestamp)
    logging.info(f"Loading: {scan_path.name}")
    all_records = VideoScanner.load_json(scan_path)
    orig_dirs = _find_orig_folders(all_records)

    if not orig_dirs:
        logging.info("No .originals folders found — nothing to revert.")
        return

    # Build (original, transcoded) pairs
    pairs: list[tuple[Path, Path]] = []
    for orig_dir in orig_dirs:
        for orig_file in sorted(f for f in orig_dir.iterdir() if f.is_file()):
            transcoded = orig_dir.parent / (orig_file.stem + ".mkv")
            pairs.append((orig_file, transcoded))

    if not pairs:
        logging.info("No files to revert.")
        return

    logging.info(f"Files to revert: {len(pairs)}")
    for orig_file, transcoded in pairs:
        orig_gb = orig_file.stat().st_size / 1024 ** 3
        trans_info = f"{transcoded.stat().st_size / 1024**3:.2f} GB" if transcoded.exists() else "not found"
        logging.info(f"  {transcoded.name} ({trans_info}) ← {orig_file.name} ({orig_gb:.2f} GB)")

    if args.dry_run:
        logging.info("[DRY RUN] No files changed.")
        return

    print()
    confirm = input(f"Revert {len(pairs)} file(s)? This will delete the transcoded versions. (yes/no): ").strip().lower()
    if confirm != "yes":
        logging.info("Cancelled.")
        return

    reverted, errors = 0, 0
    for orig_file, transcoded in pairs:
        dest = orig_file.parent.parent / orig_file.name  # back to the season folder

        # Safety check: don't overwrite something unexpected
        if dest.exists() and dest != transcoded:
            logging.error(f"  Skipped {orig_file.name}: {dest.name} already exists and is not the transcoded file")
            errors += 1
            continue

        try:
            if transcoded.exists():
                transcoded.unlink()
                logging.info(f"  Deleted transcoded: {transcoded.name}")
            orig_file.rename(dest)
            logging.info(f"  Restored: {dest.name}")
            reverted += 1
        except Exception as e:
            logging.error(f"  Error reverting {orig_file.name}: {e}")
            errors += 1

    # Remove now-empty .originals folders
    for d in orig_dirs:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                logging.info(f"  Removed empty folder: {d}")
        except Exception:
            pass

    logging.info(f"Reverted {reverted} file(s), {errors} error(s)")


def cmd_run(args: argparse.Namespace) -> None:
    _add_file_logging("run", args.folder.resolve().name, args.timestamp)
    cmd_scan(args, _setup_log=False)
    cmd_encode(args, _setup_log=False)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _init_logging()

    parser = argparse.ArgumentParser(
        description="Batch HEVC transcoder using ffmpeg + AMD AMF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Probe folder and write scan JSON")
    p_scan.add_argument("folder", type=Path, help="Folder to scan (recursive)")
    p_scan.add_argument("--out", type=Path, default=None,
                        help="Output JSON path (default: results/<timestamp>_<folder>.json)")

    # encode
    p_enc = sub.add_parser("encode", help="Pick a scan JSON and encode")
    p_enc.add_argument("--dry-run", action="store_true", help="Show plan only, do not encode")
    p_enc.add_argument("--clean", action="store_true", help="Delete .originals after encoding")
    p_enc.add_argument("--keep-larger", action="store_true", dest="keep_larger",
                       help="Keep encoded file even if it is larger than the source")

    # clean
    p_cln = sub.add_parser("clean", help="Delete originals from .originals/ after verifying encodes are good")
    p_cln.add_argument("--dry-run", action="store_true", help="Show what would be deleted, do not delete")

    # revert
    p_rev = sub.add_parser("revert", help="Restore originals from .originals/ and delete the transcoded versions")
    p_rev.add_argument("--dry-run", action="store_true", help="Show what would be changed, do not change anything")

    # run (scan + encode)
    p_run = sub.add_parser("run", help="Scan folder then encode in one step")
    p_run.add_argument("folder", type=Path, help="Folder to scan and encode")
    p_run.add_argument("--out", type=Path, default=None,
                       help="Override scan JSON path (default: results/<timestamp>_<folder>.json)")
    p_run.add_argument("--dry-run", action="store_true", help="Show plan only, do not encode")
    p_run.add_argument("--clean", action="store_true", help="Delete .originals after encoding")
    p_run.add_argument("--keep-larger", action="store_true", dest="keep_larger",
                       help="Keep encoded file even if it is larger than the source")

    args = parser.parse_args()
    args.timestamp = timestamp  # made available to all commands for log naming

    dispatch = {"scan": cmd_scan, "encode": cmd_encode, "clean": cmd_clean, "revert": cmd_revert, "run": cmd_run}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
