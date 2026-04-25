"""
run.py — main entry point for the batch transcoder.

Usage:
  python run.py scan   <folder> [--out scan.json]
  python run.py encode <scan.json> [--dry-run]
  python run.py run    <folder> [--out scan.json] [--dry-run]

  scan   : probe all video files in <folder>, write scan.json
  encode : read an existing scan.json and transcode files marked "transcode"
  run    : scan + encode in one step

Options:
  --out <path>   where to write/read the scan JSON  [default: scan_results.json]
  --dry-run      show what would be done, but do not encode anything
"""

import argparse
import logging
import sys
from pathlib import Path

from scanner import VideoScanner
from optimizer import SettingsOptimizer
from transcoder import Transcoder


# ── logging ───────────────────────────────────────────────────────────────────

def _setup_logging(log_file: str = "transcode.log") -> None:
    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> None:
    scanner = VideoScanner()
    scanner.scan_folder(args.folder)
    scanner.save_json(args.out)


def cmd_encode(args: argparse.Namespace) -> None:
    results = VideoScanner.load_json(args.out)
    to_transcode = [r for r in results if r["action"] == "transcode"]

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

    # Print plan table
    for i, rec in enumerate(to_transcode, 1):
        v = rec["video"]
        logging.info(
            f"  [{i}/{total}] {Path(rec['path']).name}  "
            f"{v['codec'].upper()} {v['width']}x{v['height']} "
            f"{rec['size_gb']:.1f} GB  →  ~{rec['estimated_saving_gb']:.1f} GB saved"
        )

    if args.dry_run:
        logging.info("\n[DRY RUN] No files encoded.")
        return

    # Confirmation
    print()
    confirm = input(f"Encode {total} file(s)? (yes/no): ").strip().lower()
    if confirm != "yes":
        logging.info("Cancelled.")
        return

    success, failed, skipped = [], [], []

    for i, rec in enumerate(to_transcode, 1):
        name = Path(rec["path"]).name
        logging.info("")
        logging.info(f"[{i}/{total}] {name}")
        logging.info("-" * 60)

        settings = optimizer.get_settings(rec)
        ok = transcoder.transcode(settings)

        if ok:
            success.append(name)
        else:
            failed.append(name)

    # Summary
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


def cmd_run(args: argparse.Namespace) -> None:
    cmd_scan(args)
    cmd_encode(args)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Batch HEVC transcoder using ffmpeg + AMD AMF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Probe folder and write scan JSON")
    p_scan.add_argument("folder", type=Path, help="Folder to scan (recursive)")
    p_scan.add_argument("--out", type=Path, default=Path("scan_results.json"),
                        help="Output JSON path (default: scan_results.json)")

    # encode
    p_enc = sub.add_parser("encode", help="Encode files listed in a scan JSON")
    p_enc.add_argument("out", nargs="?", type=Path, default=Path("scan_results.json"),
                       help="Scan JSON to read (default: scan_results.json)")
    p_enc.add_argument("--dry-run", action="store_true", help="Show plan only, do not encode")

    # run (scan + encode)
    p_run = sub.add_parser("run", help="Scan folder then encode in one step")
    p_run.add_argument("folder", type=Path, help="Folder to scan and encode")
    p_run.add_argument("--out", type=Path, default=Path("scan_results.json"),
                       help="Intermediate JSON path (default: scan_results.json)")
    p_run.add_argument("--dry-run", action="store_true", help="Show plan only, do not encode")

    args = parser.parse_args()

    dispatch = {"scan": cmd_scan, "encode": cmd_encode, "run": cmd_run}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
