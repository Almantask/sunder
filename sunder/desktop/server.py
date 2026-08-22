"""Local HTTP API + static UI for the Sunder desktop app."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import yaml

from sunder import __version__
from sunder.classify import (
    normalize_review,
    path_key,
    read_results_csv,
    sanitize_category,
    write_results_csv,
)
from sunder.config import CategoryConfigError, load_categories, normalize_categories
import sunder.desktop.jobs as jobmod
from sunder.desktop.media import decode_media_path, is_allowed_media, send_audio
from sunder.desktop.runtime import static_dir
from sunder.desktop.settings import load_settings, resolve_path, save_settings
from sunder.embeddings import EmbeddingCache

STATIC_DIR = static_dir()
STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _send_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def _send_error(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    _send_json(handler, {"error": message}, status=status)


def _send_static(handler: BaseHTTPRequestHandler, rel: str) -> None:
    name = rel.lstrip("/") or "index.html"
    if name in {"", "/"}:
        name = "index.html"
    path = (STATIC_DIR / name).resolve()
    try:
        path.relative_to(STATIC_DIR.resolve())
    except ValueError:
        _send_error(handler, "Not found", 404)
        return
    if not path.is_file():
        _send_error(handler, "Not found", 404)
        return
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", STATIC_MIME.get(path.suffix.lower(), "application/octet-stream"))
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(data)


def _media_roots(settings: dict[str, Any]) -> tuple[list[Path], set[Path]]:
    roots: list[Path] = []
    library = str(settings.get("library") or "").strip()
    if library:
        roots.append(resolve_path(library))
    cache_dir = resolve_path(settings["cache"])
    if cache_dir.exists():
        root = EmbeddingCache(cache_dir).audio_root
        if root:
            roots.append(root)
    extra: set[Path] = set()
    results = resolve_path(settings["results"])
    if results.is_file():
        try:
            for row in read_results_csv(results):
                extra.add(row.path)
        except (OSError, ValueError, KeyError):
            pass
    return roots, extra


def _row_payload(row) -> dict[str, Any]:
    path = str(row.path)
    return {
        "path": path,
        "filename": row.path.name,
        "category": row.category,
        "confidence": row.confidence,
        "score": row.score,
        "runner_up": row.runner_up,
        "runner_up_score": row.runner_up_score,
        "margin": row.margin,
        "low_confidence": row.low_confidence,
        "matched_prompt": row.matched_prompt,
        "suggested_category": row.suggested_category or row.category,
        "review": row.review,
        "comment": row.comment or "",
        "media": "/media?p=" + quote(path, safe=""),
    }


def handle_bootstrap(_handler, _query, _body) -> tuple[Any, int]:
    settings = load_settings()
    return {
        "version": __version__,
        "cwd": str(Path.cwd()),
        "settings": settings,
        "cache": jobmod.cache_stats(settings["cache"]),
        "results": jobmod.results_summary(settings["results"]),
        "job": jobmod.JOBS.snapshot(),
        "categories_exists": resolve_path(settings["categories"]).is_file(),
    }, 200


def handle_settings_save(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    return {"settings": save_settings(body)}, 200


def handle_scan(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    library = str(body.get("library") or settings.get("library") or "").strip()
    if not library:
        raise RuntimeError("Choose a library folder first.")
    recursive = bool(body.get("recursive", settings.get("recursive", True)))
    return jobmod.scan_library(library, recursive), 200


def handle_device(_handler, _query, _body) -> tuple[Any, int]:
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
        name = torch.cuda.get_device_name(0) if cuda else None
        mps_mod = getattr(torch.backends, "mps", None)
        mps = bool(mps_mod is not None and mps_mod.is_available())
        default = "cuda" if cuda else ("mps" if mps else "cpu")
        return {"cuda": cuda, "mps": mps, "name": name, "default": default}, 200
    except Exception as exc:
        return {"cuda": False, "mps": False, "name": None, "default": "cpu", "error": str(exc)}, 200


def handle_job_get(_handler, _query, _body) -> tuple[Any, int]:
    return {"job": jobmod.JOBS.snapshot()}, 200


def handle_job_cancel(_handler, _query, _body) -> tuple[Any, int]:
    return {"cancelled": jobmod.JOBS.cancel(), "job": jobmod.JOBS.snapshot()}, 200


def _start(kind: str, worker) -> tuple[Any, int]:
    job = jobmod.JOBS.start(kind, worker)
    return {"job": job}, 202


def handle_embed(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    return _start("embed", partial(jobmod.run_embed, settings))


def handle_classify(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    return _start("classify", partial(jobmod.run_classify, settings))


def handle_pipeline(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    settings = dict(settings)
    settings["save_file"] = True
    return _start("pipeline", partial(jobmod.run_pipeline, settings))


def handle_report(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    return _start("report", partial(jobmod.run_report, settings))


def handle_tag(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    return _start("tag", partial(jobmod.run_tag, settings))


def handle_organize(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    settings = save_settings(body) if body else load_settings()
    dest = str(body.get("organize_dest") or settings.get("organize_dest") or "organized")
    mode = str(body.get("mode") or "copy")
    confirm = bool(body.get("confirm_move"))
    if mode == "move" and not confirm:
        raise RuntimeError("Move mode relocates original files. Confirm to continue.")
    return _start("organize", partial(jobmod.run_organize, dest, mode, confirm))


def handle_categories_get(_handler, _query, _body) -> tuple[Any, int]:
    settings = load_settings()
    path = resolve_path(settings["categories"])
    if not path.is_file():
        raise FileNotFoundError(f"Category file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        mapping = load_categories(path)
        error = None
    except (CategoryConfigError, Exception) as exc:
        mapping = {}
        error = str(exc)
    return {
        "path": str(path),
        "yaml": text,
        "count": len(mapping),
        "names": list(mapping.keys()),
        "error": error,
    }, 200


def handle_categories_put(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    text = body.get("yaml")
    if not isinstance(text, str):
        raise ValueError("yaml text is required")
    settings = load_settings()
    path = resolve_path(settings["categories"])
    try:
        raw = yaml.safe_load(text)
        normalize_categories(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    mapping = load_categories(path)
    return {"ok": True, "count": len(mapping), "path": str(path)}, 200


def handle_results(_handler, query: dict[str, list[str]], _body) -> tuple[Any, int]:
    settings = load_settings()
    path = resolve_path(settings["results"])
    if not path.is_file():
        return {
            "rows": [],
            "total": 0,
            "low": 0,
            "pending": 0,
            "reviewed": 0,
            "accepted": 0,
            "rejected": 0,
            "offset": 0,
            "limit": 80,
            "categories": [],
            "exists": False,
        }, 200
    rows = read_results_csv(path)
    q = (query.get("q") or [""])[0].strip().lower()
    category = (query.get("category") or [""])[0].strip()
    low_only = (query.get("low") or [""])[0] in {"1", "true", "yes"}
    review_filter = (query.get("review") or [""])[0].strip().lower()
    try:
        offset = max(0, int((query.get("offset") or ["0"])[0]))
        limit = min(200, max(1, int((query.get("limit") or ["80"])[0])))
    except ValueError:
        offset, limit = 0, 80

    pending = sum(1 for row in rows if row.review == "pending")
    accepted = sum(1 for row in rows if row.review == "accepted")
    rejected = sum(1 for row in rows if row.review == "rejected")
    reviewed = accepted + rejected
    low = sum(1 for row in rows if row.low_confidence)

    def in_queue(row) -> bool:
        if review_filter in {"", "all"}:
            return True
        if review_filter == "reviewed":
            return row.review in {"accepted", "rejected"}
        if review_filter in {"pending", "accepted", "rejected"}:
            return row.review == review_filter
        return True

    counts: dict[str, int] = {}
    filtered = []
    for row in rows:
        if not in_queue(row):
            continue
        if low_only and not row.low_confidence:
            continue
        if q:
            hay = f"{row.path.name} {row.category} {row.runner_up} {row.matched_prompt} {row.comment}".lower()
            if q not in hay:
                continue
        counts[row.category] = counts.get(row.category, 0) + 1
        if category and row.category != category:
            continue
        filtered.append(row)
    page = filtered[offset : offset + limit]
    categories = [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]
    return {
        "rows": [_row_payload(row) for row in page],
        "total": len(filtered),
        "all": len(rows),
        "queue": sum(counts.values()),
        "low": low,
        "pending": pending,
        "reviewed": reviewed,
        "accepted": accepted,
        "rejected": rejected,
        "offset": offset,
        "limit": limit,
        "categories": categories,
        "exists": True,
    }, 200


def handle_review(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    if jobmod.JOBS.busy():
        raise RuntimeError("Wait for the current job to finish.")
    target = str(body.get("path") or "").strip()
    if not target:
        raise ValueError("path is required")
    settings = load_settings()
    csv_path = resolve_path(settings["results"])
    if not csv_path.is_file():
        raise RuntimeError("Classify a library first.")
    rows = read_results_csv(csv_path)
    key = path_key(target)
    found = next((row for row in rows if path_key(row.path) == key), None)
    if found is None:
        raise FileNotFoundError("Track is not in results.csv")
    if "comment" in body and body["comment"] is not None:
        found.comment = str(body["comment"])
    if "category" in body and body["category"] is not None:
        found.category = sanitize_category(str(body["category"]))
    if "review" in body and body["review"] is not None:
        found.review = normalize_review(str(body["review"]))
        if found.review == "accepted":
            found.category = sanitize_category(found.category)
    write_results_csv(csv_path, rows)
    return {"ok": True, "row": _row_payload(found)}, 200


def handle_open_report(_handler, _query, _body) -> tuple[Any, int]:
    settings = load_settings()
    path = resolve_path(settings["report"])
    if not path.is_file():
        path = jobmod.run_report(settings)["path"]
        path = Path(path)
    webbrowser.open(path.resolve().as_uri())
    return {"ok": True, "path": str(path.resolve())}, 200


def handle_reveal(_handler, _query, body: dict[str, Any]) -> tuple[Any, int]:
    raw = str(body.get("path") or "").strip()
    if not raw:
        raise ValueError("path is required")
    path = Path(raw).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    reveal_in_explorer(path)
    return {"ok": True}, 200


def handle_pick_folder(_handler, _query, _body) -> tuple[Any, int]:
    path = pick_folder_dialog()
    return {"path": path or ""}, 200


def reveal_in_explorer(path: Path) -> None:
    path = path.resolve()
    if sys.platform == "win32":
        if path.is_file():
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        else:
            os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        cmd = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
        subprocess.run(cmd, check=False)
        return
    target = str(path if path.is_dir() else path.parent)
    subprocess.run(["xdg-open", target], check=False)


def pick_folder_dialog() -> str:
    try:
        import webview

        if webview.windows:
            flag = getattr(webview, "FOLDER_DIALOG", None)
            if flag is None:
                flag = webview.FileDialog.FOLDER
            result = webview.windows[0].create_file_dialog(flag)
            if result:
                return str(result[0])
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.wm_attributes("-topmost", 1)
        except tk.TclError:
            pass
        chosen = filedialog.askdirectory(title="Choose audio library")
        root.destroy()
        return chosen or ""
    except Exception:
        return ""


ROUTES = {
    ("GET", "/api/bootstrap"): handle_bootstrap,
    ("GET", "/api/job"): handle_job_get,
    ("GET", "/api/device"): handle_device,
    ("GET", "/api/categories"): handle_categories_get,
    ("GET", "/api/results"): handle_results,
    ("POST", "/api/results/review"): handle_review,
    ("POST", "/api/settings"): handle_settings_save,
    ("POST", "/api/scan"): handle_scan,
    ("POST", "/api/embed"): handle_embed,
    ("POST", "/api/classify"): handle_classify,
    ("POST", "/api/pipeline"): handle_pipeline,
    ("POST", "/api/report"): handle_report,
    ("POST", "/api/tag"): handle_tag,
    ("POST", "/api/organize"): handle_organize,
    ("POST", "/api/job/cancel"): handle_job_cancel,
    ("POST", "/api/open-report"): handle_open_report,
    ("POST", "/api/reveal"): handle_reveal,
    ("POST", "/api/pick-folder"): handle_pick_folder,
    ("PUT", "/api/categories"): handle_categories_put,
}


class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/media" or path.startswith("/media/"):
                self._media(query)
                return
            route = ROUTES.get((self.command if self.command != "HEAD" else "GET", path))
            if route:
                body = {}
                if self.command in {"POST", "PUT"}:
                    body = _json_body(self)
                payload, status = route(self, query, body)
                _send_json(self, payload, status)
                return
            if self.command in {"GET", "HEAD"}:
                _send_static(self, path)
                return
            _send_error(self, "Not found", 404)
        except (FileNotFoundError, RuntimeError, ValueError, CategoryConfigError) as exc:
            _send_error(self, str(exc), 400)
        except BrokenPipeError:
            return
        except Exception as exc:
            _send_error(self, str(exc), 500)

    def _media(self, query: dict[str, list[str]]) -> None:
        raw = (query.get("p") or query.get("path") or [""])[0]
        if not raw:
            _send_error(self, "Missing path", 400)
            return
        path = decode_media_path(raw)
        settings = load_settings()
        roots, extra = _media_roots(settings)
        if not is_allowed_media(path, roots, extra):
            _send_error(self, "File is not in the library", 403)
            return
        try:
            send_audio(self, path.resolve())
        except OSError as exc:
            _send_error(self, str(exc), 404)


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    httpd.daemon_threads = True
    return httpd
