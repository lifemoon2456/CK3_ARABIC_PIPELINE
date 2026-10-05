"""Shape and visually reorder Arabic CK3 localization with tested libraries."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display

ARABIC = re.compile(r"[\u0621-\u064A\u0670-\u06FF]")
PRESENTATION = re.compile(r"[\uFB50-\uFEFF]")
TAGS = re.compile(r'(\[[^\]]+\]|\$[A-Za-z0-9*.\-]+\$|@[A-Za-z0-9_.\-]+!?|#[A-Za-z0-9_!]+|£[^£\n]+£|\\[\\"ntr])')
LINE = re.compile(r'^(\s*[A-Za-z0-9_.\-]+:\d*\s+)(".*")(.*?)(\r?\n)?$')
RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": False,
    "shift_harakat_position": True,
    "support_ligatures": True,
})


def reshape_value(value: str) -> str:
    # Tatweel and some diacritics remain in the Arabic block after shaping.
    # A presentation-form glyph is an unambiguous marker that this value was
    # already processed, so never reorder it a second time.
    if PRESENTATION.search(value) or not ARABIC.search(value):
        return value
    protected: list[str] = []

    def mask(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        # A Latin run remains intact during the bidi step and is restored below.
        return f"ZzCkTag{len(protected) - 1}Xx"

    masked = TAGS.sub(mask, value)
    displayed = get_display(RESHAPER.reshape(masked))
    for number, item in enumerate(protected):
        displayed = displayed.replace(f"ZzCkTag{number}Xx", item)
    return displayed


def process_file(path: Path, dry_run: bool) -> int:
    source = path.read_text(encoding="utf-8-sig")
    changed = 0
    result: list[str] = []
    for line in source.splitlines(keepends=True):
        match = LINE.match(line)
        if not match:
            result.append(line)
            continue
        prefix, quoted, suffix, ending = match.groups()
        value = quoted[1:-1]
        fixed = reshape_value(value)
        changed += fixed != value
        result.append(f'{prefix}"{fixed}"{suffix}{ending or ""}')
    if changed and not dry_run:
        path.write_text("".join(result), encoding="utf-8-sig", newline="")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    files = sorted(args.directory.rglob("*.yml"))
    count = sum(process_file(path, args.dry_run) for path in files)
    print(f"{'Would update' if args.dry_run else 'Updated'} {count} values in {len(files)} files.")


if __name__ == "__main__":
    main()
