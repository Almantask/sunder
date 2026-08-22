"""Background jobs that wrap the CLI pipeline for the desktop app."""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from collections import deque
from typing import Any, Callable

from sunder.classify import classify_cache, read_results_csv
from sunder.desktop.settings import device_arg, load_settings, resolve_path
from sunder.embeddings import EmbeddingCache, embed_library, scan_audio
from sunder.organize import organize_results
from sunder.progress import Cancelled
from sunder.report import write_report
from sunder.tags import tag_rows

LOG_LIMIT = 400


class _PrintTee:
    def __init__(self, callback: Callable[[str], None], stream):
        self.callback = callback
        self.stream = stream
        self._buf = ""

    def write(self, data) -> int:
        if not data:
            return 0
        text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
        if self.stream is not None:
            try:
                self.stream.write(text)
                self.stream.flush()
            except Exception:
                pass
        self._buf += text.replace("\r", "\n")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            stripped = line.strip()
            if stripped:
                self.callback(stripped)
        return len(text)

    def flush(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.flush()
        except Exception:
            pass


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._job: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._job:
                return None
            job = dict(self._job)
            job["log"] = list(job["log"])
            return job

    def busy(self) -> bool:
        with self._lock:
            return bool(self._job and self._job["status"] == "running")

    def cancel(self) -> bool:
        with self._lock:
            if not self._job or self._job["status"] != "running":
                return False
            self._cancel.set()
            self._job["message"] = "Cancelling…"
            return True

    def start(self, kind: str, worker: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise RuntimeError("A job is already running.")
            self._cancel.clear()
            self._job = {
                "kind": kind,
                "status": "running",
                "message": "Starting…",
                "current": 0,
                "total": 0,
                "stage": "queued",
                "started": time.time(),
                "finished": None,
                "error": None,
                "result": None,
                "log": deque(maxlen=LOG_LIMIT),
            }
            snapshot = dict(self._job)
            snapshot["log"] = list(snapshot["log"])
        thread = threading.Thread(target=self._run, args=(kind, worker), daemon=True, name=f"sunder-{kind}")
        thread.start()
        return snapshot

    def _append(self, line: str) -> None:
        with self._lock:
            if self._job:
                self._job["log"].append({"t": time.time(), "line": line})

    def _progress(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if not self._job:
                return
            if "message" in payload and payload["message"]:
                self._job["message"] = str(payload["message"])
            if "current" in payload:
                self._job["current"] = int(payload["current"] or 0)
            if "total" in payload:
                self._job["total"] = int(payload["total"] or 0)
            if "stage" in payload:
                self._job["stage"] = str(payload["stage"])

    def _run(self, kind: str, worker: Callable[[], dict[str, Any] | None]) -> None:
        tee_out = _PrintTee(self._append, sys.__stdout__)
        tee_err = _PrintTee(self._append, sys.__stderr__)
        try:
            with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
                result = worker()
        except Cancelled:
            with self._lock:
                if self._job:
                    self._job["status"] = "cancelled"
                    self._job["message"] = "Cancelled."
                    self._job["finished"] = time.time()
                    self._job["error"] = None
            self._append("Cancelled.")
            return
        except Exception as exc:
            with self._lock:
                if self._job:
                    self._job["status"] = "error"
                    self._job["message"] = str(exc)
                    self._job["error"] = str(exc)
                    self._job["finished"] = time.time()
            self._append(f"error: {exc}")
            return
        with self._lock:
            if self._job:
                self._job["status"] = "done"
                self._job["message"] = (result or {}).get("message") or "Done."
                self._job["result"] = result
                self._job["finished"] = time.time()
                if result and result.get("current") is not None:
                    self._job["current"] = result["current"]
                if result and result.get("total") is not None:
                    self._job["total"] = result["total"]


JOBS = JobManager()


def _hooks():
    return {
        "progress": JOBS._progress,
        "should_cancel": JOBS._cancel.is_set,
    }


def cache_stats(cache_dir: str) -> dict[str, Any]:
    path = resolve_path(cache_dir)
    if not path.exists():
        return {"tracks": 0, "model": None, "root": None}
    cache = EmbeddingCache(path)
    root = cache.audio_root
    return {
        "tracks": len(cache),
        "model": cache.model_id,
        "root": str(root) if root else None,
    }


def results_summary(results_path: str) -> dict[str, Any]:
    path = resolve_path(results_path)
    if not path.is_file():
        return {"tracks": 0, "low": 0, "categories": 0, "exists": False}
    rows = read_results_csv(path)
    cats = {row.category for row in rows}
    low = sum(1 for row in rows if row.low_confidence)
    return {
        "tracks": len(rows),
        "low": low,
        "categories": len(cats),
        "exists": True,
    }


def scan_library(library: str, recursive: bool, limit: int | None = None) -> dict[str, Any]:
    root = resolve_path(library)
    files = scan_audio(root, recursive=recursive)
    if limit:
        files = files[:limit]
    return {
        "root": str(root),
        "count": len(files),
        "sample": [path.name for path in files[:12]],
        "recursive": recursive,
    }


def run_embed(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    library = str(cfg.get("library") or "").strip()
    if not library:
        raise RuntimeError("Choose a library folder first.")
    hooks = _hooks()
    cache = embed_library(
        resolve_path(library),
        resolve_path(cfg["cache"]),
        limit=cfg.get("limit"),
        force=bool(cfg.get("force")),
        device=device_arg(cfg),
        recursive=bool(cfg.get("recursive", True)),
        **hooks,
    )
    return {
        "message": f"Embedded library · {len(cache)} tracks in cache",
        "tracks": len(cache),
        "kind": "embed",
    }


def run_classify(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    write_csv = bool(cfg.get("save_file"))
    write_tags = bool(cfg.get("embed_track"))
    if not write_csv and not write_tags:
        write_csv = True
    hooks = _hooks()
    rows = classify_cache(
        resolve_path(cfg["cache"]),
        resolve_path(cfg["categories"]),
        resolve_path(cfg["results"]),
        threshold=float(cfg["threshold"]),
        min_margin=float(cfg["min_margin"]),
        device=device_arg(cfg),
        write_csv=write_csv,
        write_tags=write_tags,
        **hooks,
    )
    low = sum(1 for row in rows if row.low_confidence)
    return {
        "message": f"Classified {len(rows)} tracks ({low} low-confidence)",
        "tracks": len(rows),
        "low": low,
        "kind": "classify",
        "current": len(rows),
        "total": len(rows),
    }


def run_report(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    out = write_report(resolve_path(cfg["results"]), resolve_path(cfg["report"]))
    return {"message": f"Wrote {out}", "path": str(out.resolve()), "kind": "report"}


def run_tag(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    rows = read_results_csv(resolve_path(cfg["results"]))
    if not rows:
        raise RuntimeError("No rows in results.csv. Classify first.")
    cache_dir = resolve_path(cfg["cache"])
    cache = EmbeddingCache(cache_dir) if cache_dir.exists() else None
    hooks = _hooks()
    written, errors = tag_rows(
        rows,
        cache=cache,
        progress=hooks["progress"],
        should_cancel=hooks["should_cancel"],
    )
    return {
        "message": f"Wrote tags on {written} files ({errors} failed)",
        "written": written,
        "errors": errors,
        "kind": "tag",
    }


def run_organize(dest: str, mode: str, confirm_move: bool = False) -> dict[str, Any]:
    if mode not in {"copy", "move"}:
        raise ValueError("mode must be copy or move")
    if mode == "move" and not confirm_move:
        raise RuntimeError("Move mode relocates original files. Confirm to continue.")
    cfg = load_settings()
    hooks = _hooks()
    copied, skipped, missing = organize_results(
        resolve_path(cfg["results"]),
        resolve_path(dest),
        mode=mode,
        **hooks,
    )
    verb = "Copied" if mode == "copy" else "Moved"
    return {
        "message": f"{verb} {copied} files (skipped {skipped}, missing {missing})",
        "copied": copied,
        "skipped": skipped,
        "missing": missing,
        "kind": "organize",
        "mode": mode,
    }


def run_pipeline(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    run_embed(cfg)
    if JOBS._cancel.is_set():
        raise Cancelled("Cancelled.")
    classify_cfg = dict(cfg)
    classify_cfg["save_file"] = True
    classified = run_classify(classify_cfg)
    if JOBS._cancel.is_set():
        raise Cancelled("Cancelled.")
    report = run_report(cfg)
    return {
        "message": classified["message"],
        "tracks": classified.get("tracks"),
        "low": classified.get("low"),
        "report": report.get("path"),
        "kind": "pipeline",
    }
