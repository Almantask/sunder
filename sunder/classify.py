"""Zero-shot category assignment from cached audio embeddings."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sunder.config import flatten_prompts, load_categories
from sunder.embeddings import ClapEmbedder, EmbeddingCache
from sunder.progress import check_cancel, emit as emit_progress

DEFAULT_THRESHOLD = 0.35
DEFAULT_MIN_MARGIN = 0.02
REVIEW_PENDING = "pending"
REVIEW_ACCEPTED = "accepted"
REVIEW_REJECTED = "rejected"
CSV_FIELDS = [
    "path",
    "filename",
    "category",
    "confidence",
    "score",
    "runner_up",
    "runner_up_score",
    "margin",
    "low_confidence",
    "matched_prompt",
    "suggested_category",
    "review",
    "comment",
]


def path_key(path: str | Path) -> str:
    raw = str(path)
    try:
        raw = str(Path(path).resolve())
    except OSError:
        pass
    return os.path.normcase(os.path.normpath(raw))


def normalize_review(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"accepted", "accept", "ok", "yes"}:
        return REVIEW_ACCEPTED
    if raw in {"rejected", "reject", "no"}:
        return REVIEW_REJECTED
    return REVIEW_PENDING


def sanitize_category(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Category is required.")
    if any(char in cleaned for char in '<>:"/\\|?*'):
        raise ValueError("Category contains invalid characters.")
    return cleaned[:80]


def apply_human_overrides(
    rows: list[Classification],
    previous_csv: str | Path | None,
) -> list[Classification]:
    """Keep accept/reject, comments, and custom categories across re-classify."""
    for row in rows:
        if not row.suggested_category:
            row.suggested_category = row.category
        row.review = normalize_review(row.review)
    if not previous_csv:
        return rows
    prev_path = Path(previous_csv)
    if not prev_path.is_file():
        return rows
    try:
        previous = {path_key(old.path): old for old in read_results_csv(prev_path)}
    except (OSError, ValueError, KeyError):
        return rows
    for row in rows:
        old = previous.get(path_key(row.path))
        if not old:
            continue
        row.comment = old.comment or ""
        status = normalize_review(old.review)
        if status in {REVIEW_ACCEPTED, REVIEW_REJECTED}:
            row.review = status
            row.category = old.category
    return rows


@dataclass
class Classification:
    path: Path
    category: str
    confidence: float
    score: float
    runner_up: str
    runner_up_score: float
    margin: float
    low_confidence: bool
    matched_prompt: str
    suggested_category: str = ""
    review: str = REVIEW_PENDING
    comment: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.suggested_category:
            self.suggested_category = self.category
        self.review = normalize_review(self.review)
        self.comment = self.comment or ""


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / np.clip(exp.sum(), 1e-12, None)


def score_track(
    audio_emb: np.ndarray,
    prompt_embs: np.ndarray,
    prompt_labels: list[str],
    prompt_texts: list[str],
    category_order: list[str],
    *,
    logit_scale: float = 14.0,
    threshold: float = DEFAULT_THRESHOLD,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> tuple[str, float, float, str, float, str]:
    """Return (category, confidence, cosine, runner_up, runner_cosine, matched_prompt)."""
    audio = audio_emb.astype(np.float32)
    audio = audio / max(float(np.linalg.norm(audio)), 1e-12)
    prompts = prompt_embs.astype(np.float32)
    norms = np.linalg.norm(prompts, axis=1, keepdims=True)
    prompts = prompts / np.clip(norms, 1e-12, None)

    cosine = prompts @ audio
    best_by_cat: dict[str, tuple[float, str]] = {}
    for index, label in enumerate(prompt_labels):
        value = float(cosine[index])
        current = best_by_cat.get(label)
        if current is None or value > current[0]:
            best_by_cat[label] = (value, prompt_texts[index])

    scores = np.array([best_by_cat[name][0] for name in category_order], dtype=np.float64)
    probs = softmax(logit_scale * scores)
    ranked = np.argsort(scores)[::-1]
    top = int(ranked[0])
    second = int(ranked[1]) if len(ranked) > 1 else top
    category = category_order[top]
    runner_up = category_order[second]
    return (
        category,
        float(probs[top]),
        float(scores[top]),
        runner_up,
        float(scores[second]),
        best_by_cat[category][1],
    )


def classify_embeddings(
    items: list[tuple[Path, np.ndarray]],
    categories: dict[str, list[str]],
    prompt_embs: np.ndarray,
    *,
    logit_scale: float = 14.0,
    threshold: float = DEFAULT_THRESHOLD,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> list[Classification]:
    prompt_texts, prompt_labels = flatten_prompts(categories)
    category_order = list(categories.keys())
    results: list[Classification] = []
    for path, embedding in items:
        category, confidence, score, runner_up, runner_score, prompt = score_track(
            embedding,
            prompt_embs,
            prompt_labels,
            prompt_texts,
            category_order,
            logit_scale=logit_scale,
            threshold=threshold,
            min_margin=min_margin,
        )
        margin = score - runner_score
        low = confidence < threshold or margin < min_margin
        results.append(
            Classification(
                path=path,
                category=category,
                confidence=confidence,
                score=score,
                runner_up=runner_up,
                runner_up_score=runner_score,
                margin=margin,
                low_confidence=low,
                matched_prompt=prompt,
            )
        )
    results.sort(key=lambda row: (row.category.lower(), -row.confidence, row.path.name.lower()))
    return results


def write_results_csv(path: str | Path, rows: list[Classification]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "path": str(row.path),
                    "filename": row.path.name,
                    "category": row.category,
                    "confidence": f"{row.confidence:.6f}",
                    "score": f"{row.score:.6f}",
                    "runner_up": row.runner_up,
                    "runner_up_score": f"{row.runner_up_score:.6f}",
                    "margin": f"{row.margin:.6f}",
                    "low_confidence": "true" if row.low_confidence else "false",
                    "matched_prompt": row.matched_prompt,
                    "suggested_category": row.suggested_category or row.category,
                    "review": normalize_review(row.review),
                    "comment": row.comment or "",
                }
            )


def read_results_csv(path: str | Path) -> list[Classification]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Results file not found: {path}")
    rows: list[Classification] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                Classification(
                    path=Path(raw["path"]),
                    category=raw["category"],
                    confidence=float(raw["confidence"]),
                    score=float(raw["score"]),
                    runner_up=raw["runner_up"],
                    runner_up_score=float(raw["runner_up_score"]),
                    margin=float(raw["margin"]),
                    low_confidence=raw.get("low_confidence", "").lower() in {"true", "1", "yes"},
                    matched_prompt=raw.get("matched_prompt", ""),
                    suggested_category=raw.get("suggested_category", "") or raw["category"],
                    review=raw.get("review", ""),
                    comment=raw.get("comment", ""),
                )
            )
    return rows


def classify_cache(
    cache_dir: str | Path,
    categories_path: str | Path,
    out_csv: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_margin: float = DEFAULT_MIN_MARGIN,
    device: str | None = None,
    write_csv: bool = True,
    write_tags: bool = True,
    progress=None,
    should_cancel=None,
) -> list[Classification]:
    cache = EmbeddingCache(cache_dir)
    items = cache.items()
    if not items:
        raise RuntimeError("No embeddings in cache. Run `python -m sunder embed <folder>` first.")

    check_cancel(should_cancel)
    categories = load_categories(categories_path)
    prompt_texts, _labels = flatten_prompts(categories)
    emit_progress(
        progress,
        stage="load_model",
        message="Loading text encoder…",
        current=0,
        total=len(items),
    )
    embedder = ClapEmbedder(model_id=cache.model_id, device=device)
    print(f"Classifying {len(items)} tracks into {len(categories)} categories...", flush=True)
    prompt_embs = embedder.encode_texts(prompt_texts)
    check_cancel(should_cancel)
    emit_progress(
        progress,
        stage="score",
        message="Scoring tracks…",
        current=0,
        total=len(items),
    )
    rows = classify_embeddings(
        items,
        categories,
        prompt_embs,
        logit_scale=embedder.logit_scale,
        threshold=threshold,
        min_margin=min_margin,
    )
    for row in rows:
        row.suggested_category = row.category
    apply_human_overrides(rows, out_csv)
    if not write_csv and not write_tags:
        raise ValueError("Nothing to write: pass --save-file and/or --embed-track")
    if write_csv:
        write_results_csv(out_csv, rows)
    low = sum(1 for row in rows if row.low_confidence)
    if write_csv:
        print(f"Wrote {out_csv}  ({low} low-confidence / {len(rows)})", flush=True)
    else:
        print(
            f"Classified {len(rows)} tracks ({low} low-confidence); CSV skipped",
            flush=True,
        )
    if write_tags:
        from sunder.tags import tag_rows

        written, tag_errors = tag_rows(
            rows,
            cache=cache,
            progress=progress,
            should_cancel=should_cancel,
        )
        print(f"Wrote tags on {written} files ({tag_errors} failed)", flush=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.category] = counts.get(row.category, 0) + 1
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower())):
        print(f"  {count:5d}  {name}", flush=True)
    emit_progress(
        progress,
        stage="done",
        message=f"Classified {len(rows)} tracks ({low} low-confidence)",
        current=len(rows),
        total=len(rows),
    )
    return rows
