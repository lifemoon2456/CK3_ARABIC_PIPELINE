"""Reusable CK3 Arabic-localization pipeline.

Run this file from the project's ``tools`` directory.  It accepts either a
mod root (containing localization/english) or the localization directory.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import zipfile
from pathlib import Path


def localization_dir(target: Path) -> Path:
    target = target.resolve()
    candidate = target / "localization" / "english"
    if candidate.is_dir():
        return candidate
    if target.is_dir() and any(target.rglob("*.yml")):
        return target
    raise SystemExit("Target must be a CK3 mod root or a localization directory containing YML files.")


def make_backup(root: Path, tools: Path) -> Path:
    backups = tools / "backups"
    backups.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive = backups / f"{root.parent.name}_before_arabic_{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(root.rglob("*.yml")):
            zipped.write(path, path.relative_to(root))
    return archive


def verify(root: Path) -> tuple[int, int]:
    files = list(root.rglob("*.yml"))
    bom_missing = sum(not path.read_bytes().startswith(b"\xef\xbb\xbf") for path in files)
    return len(files), bom_missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate and shape CK3 Arabic localization.")
    parser.add_argument("target", type=Path, help="Mod root or localization/english directory")
    parser.add_argument("--shape-only", action="store_true", help="Skip Gemini translation and only shape raw Arabic")
    parser.add_argument("--dry-run", action="store_true", help="Report shaping changes without modifying files")
    args = parser.parse_args()

    tools = Path(__file__).resolve().parent
    root = localization_dir(args.target)
    sys.path.insert(0, str(tools))
    import reshape_ck3_with_libraries as shaper

    if args.dry_run:
        changed = sum(shaper.process_file(path, dry_run=True) for path in root.rglob("*.yml"))
        print(f"Would shape {changed} values in {root}.")
        return

    backup = make_backup(root, tools)
    print(f"Backup created: {backup}")

    if not args.shape_only:
        import translate_ck3_ar as translator
        translator.ROOT = str(root)
        translator.BACKUP = str(backup)
        translator.LOG_PATH = str(tools / "translate_ck3_ar.log")
        sys.argv = [sys.argv[0], "run"]
        translator.main()

    changed = sum(shaper.process_file(path, dry_run=False) for path in root.rglob("*.yml"))
    files, bom_missing = verify(root)
    print(f"Shaped {changed} values. Checked {files} YML files; BOM missing: {bom_missing}.")


if __name__ == "__main__":
    main()
