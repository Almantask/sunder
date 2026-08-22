"""Copy or move classified tracks into per-category folders."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from sunder.classify import Classification, read_results_csv

WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WIN_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_folder_name(name: str) -> str:
    cleaned = WIN_INVALID.sub("_", name).strip(" .")
    if not cleaned:
        return "unnamed"
    if cleaned.upper() in WIN_RESERVED:
        return f"{cleaned}_"
    return cleaned


def unique_dest(directory: Path, filename: str) -> Path:
    dest = directory / filename
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def organize_rows(
    rows: list[Classification],
    dest_root: str | Path,
    mode: str = "copy",
) -> tuple[int, int, int]:
    if mode not in {"copy", "move"}:
        raise ValueError("mode must be 'copy' or 'move'")
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    missing = 0
    action = shutil.copy2 if mode == "copy" else shutil.move
    for row in rows:
        source = row.path
        if not source.is_file():
            missing += 1
            print(f"MISSING {source}", flush=True)
            continue
        folder = dest_root / safe_folder_name(row.category)
        folder.mkdir(parents=True, exist_ok=True)
        dest = unique_dest(folder, source.name)
        if dest.exists() and dest.resolve() == source.resolve():
            skipped += 1
            continue
        action(str(source), str(dest))
        copied += 1
    return copied, skipped, missing


def organize_results(
    results_csv: str | Path,
    dest_root: str | Path,
    mode: str = "copy",
) -> tuple[int, int, int]:
    rows = read_results_csv(results_csv)
    if not rows:
        raise RuntimeError(f"No rows in {results_csv}. Run classify first.")
    copied, skipped, missing = organize_rows(rows, dest_root, mode=mode)
    verb = "Copied" if mode == "copy" else "Moved"
    print(
        f"{verb} {copied} files into {dest_root}  (skipped {skipped}, missing {missing})",
        flush=True,
    )
    return copied, skipped, missing
