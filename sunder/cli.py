"""CLI: embed, classify, report, organize."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sunder import __version__
from sunder.classify import DEFAULT_MIN_MARGIN, DEFAULT_THRESHOLD, classify_cache, read_results_csv
from sunder.embeddings import MODEL_ID, EmbeddingCache, embed_library
from sunder.organize import organize_results
from sunder.report import write_report
from sunder.tags import tag_rows


def classify_destinations(args: argparse.Namespace) -> tuple[bool, bool]:
    """Return (write_csv, write_tags) from --save-file / --embed-track."""
    write_csv = bool(args.save_file)
    write_tags = bool(args.embed_track)
    if not write_csv and not write_tags:
        raise ValueError("Pass --save-file and/or --embed-track")
    return write_csv, write_tags


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sunder",
        description="Categorize ambience tracks with zero-shot CLAP.",
    )
    parser.add_argument("--version", action="version", version=f"sunder {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    embed = sub.add_parser("embed", help="Compute and cache CLAP audio embeddings")
    embed.add_argument("path", type=Path, help="Folder of audio files (scanned recursively by default)")
    embed.add_argument("--cache", type=Path, default=Path(".sunder_cache"))
    embed.add_argument("--model", default=MODEL_ID)
    embed.add_argument("--device", default=None, help="cuda, cpu, or mps (default: auto)")
    embed.add_argument("--limit", type=int, default=None, help="Only embed the first N files")
    embed.add_argument("--force", action="store_true", help="Re-embed even if cached")
    embed.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="scan all nested subfolders (default: on). Use --no-recursive for the top folder only",
    )

    classify = sub.add_parser("classify", help="Assign categories from cached embeddings")
    classify.add_argument("--categories", type=Path, default=Path("categories.yaml"))
    classify.add_argument("--cache", type=Path, default=Path(".sunder_cache"))
    classify.add_argument("--out", type=Path, default=Path("results.csv"))
    classify.add_argument("--device", default=None)
    classify.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    classify.add_argument("--min-margin", type=float, default=DEFAULT_MIN_MARGIN)
    classify.add_argument(
        "--save-file",
        action="store_true",
        help="write results.csv",
    )
    classify.add_argument(
        "--embed-track",
        action="store_true",
        help="write category tags into each audio file",
    )

    report = sub.add_parser("report", help="Write an HTML review report")
    report.add_argument("--results", type=Path, default=Path("results.csv"))
    report.add_argument("--out", type=Path, default=Path("report.html"))

    organize = sub.add_parser("organize", help="Copy or move files into category folders")
    organize.add_argument("--results", type=Path, default=Path("results.csv"))
    organize.add_argument("--dest", type=Path, default=Path("organized"))
    organize.add_argument(
        "--mode",
        choices=("copy", "move"),
        default="copy",
        help="copy (default, safe) or move originals into category folders",
    )

    tag = sub.add_parser("tag", help="Write category tags from results.csv into audio files")
    tag.add_argument("--results", type=Path, default=Path("results.csv"))
    tag.add_argument("--cache", type=Path, default=Path(".sunder_cache"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "embed":
            embed_library(
                args.path,
                args.cache,
                limit=args.limit,
                force=args.force,
                device=args.device,
                model_id=args.model,
                recursive=args.recursive,
            )
            return 0
        if args.command == "classify":
            write_csv, write_tags = classify_destinations(args)
            classify_cache(
                args.cache,
                args.categories,
                args.out,
                threshold=args.threshold,
                min_margin=args.min_margin,
                device=args.device,
                write_csv=write_csv,
                write_tags=write_tags,
            )
            return 0
        if args.command == "report":
            write_report(args.results, args.out)
            return 0
        if args.command == "organize":
            if args.mode == "move":
                print(
                    "Move mode will relocate original files into category folders.",
                    flush=True,
                )
            organize_results(args.results, args.dest, mode=args.mode)
            return 0
        if args.command == "tag":
            rows = read_results_csv(args.results)
            if not rows:
                raise RuntimeError(f"No rows in {args.results}. Run classify first.")
            cache = EmbeddingCache(args.cache) if args.cache.exists() else None
            written, errors = tag_rows(rows, cache=cache)
            print(f"Wrote tags on {written} files ({errors} failed)", flush=True)
            return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command {args.command}")
    return 2
