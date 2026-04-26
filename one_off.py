"""
one_off.py — ad-hoc utility functions, run directly.
"""

from pathlib import Path


def strip_orig_prefix(folder: str | Path, recursive: bool = False) -> None:
    """
    Rename all files prefixed with '_ORIG_' in folder by removing that prefix.

    Args:
        folder:     Path to scan for _ORIG_ files.
        recursive:  If True, also scan subfolders.
    """
    folder = Path(folder)
    if not folder.exists():
        print(f"Folder not found: {folder}")
        return

    pattern = "**/_ORIG_*" if recursive else "_ORIG_*"
    files = sorted(folder.glob(pattern))

    if not files:
        print("No _ORIG_ files found.")
        return

    print(f"Found {len(files)} file(s):")
    renames: list[tuple[Path, Path]] = []
    for f in files:
        target = f.parent / f.name.removeprefix("_ORIG_")
        status = " ⚠ TARGET EXISTS — will skip" if target.exists() else ""
        print(f"  {f.name}  →  {target.name}{status}")
        renames.append((f, target))

    print()
    confirm = input("Rename? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    renamed, skipped, errors = 0, 0, 0
    for src, dst in renames:
        if dst.exists():
            print(f"  SKIP (exists): {dst.name}")
            skipped += 1
            continue
        try:
            src.rename(dst)
            print(f"  Renamed: {dst.name}")
            renamed += 1
        except Exception as e:
            print(f"  ERROR {src.name}: {e}")
            errors += 1

    print(f"\nDone — renamed: {renamed}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python one_off.py <folder> [--recursive]")
        sys.exit(1)

    strip_orig_prefix(
        folder=sys.argv[1],
        recursive="--recursive" in sys.argv,
    )
